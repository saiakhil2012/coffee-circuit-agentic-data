"""One incident with the Quality agent, as a stream of typed events.

The terminal CLI and the web console both drive the agent through IncidentSession and render the same events:

  complaint   the feedback that opened the incident
  thinking    the agent has started a turn
  tool_call   the agent called a tool (name, arguments, the query behind it)
  similar     hybrid search result: similar complaints, outlets, roast lot, the SOP it cites
  chain       supply-chain trace result: green-bean batch, supplier, every roast lot made from it
  refused     the read-only MCP server refused a write
  proposal    what an approved hold would change (from data already read; nothing written)
  approved    a person granted the write tool
  resolved    the hold committed in one ACID transaction (or was already in place)
  rows        rows returned by an ad-hoc read query
  tool_error  a tool failed; the message goes back to the model too
  answer      the model's own short reply
  done        the turn finished (seconds)
"""

import ast
import json
import re
import time
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent

from . import config
from .mcp import Sql, client, parse
from .tools import read_tools, write_tools

SYSTEM = """You are the Quality agent for Coffee Circuit, a chain of 300 coffee outlets.
For every user message, call exactly one tool (a real tool call, never written out as text), then reply with one
short, complete sentence using only numbers the tool returned, for example
"Lot RL-4471 has 35 similar complaints across 14 outlets."

Which tool:
* A new complaint, or "are others seeing this?": call find_similar_complaints with the feedback id.
* "Who else got these beans?": call who_else_is_affected with the roast lot id that had the most complaints.
* Asked to hold deliveries while you have no hold tool: call run_sql_plus_plus_query with bucket_name store,
  scope_name ops and an UPDATE on the deliveries collection setting status to on_hold for the affected roast lots.
  Report exactly what the data layer answered. Do not refuse on your own.
* After a human approves: call place_quality_hold with all affected roast lot ids and the green-bean lot.
* If the answer is already in an earlier tool result in this conversation (for example the quality SOP text, or
  open feedback per lot), answer from it in one or two sentences without calling a tool.
* Any other question about the data: call run_sql_plus_plus_query with bucket_name store, scope_name ops and ONE
  read-only SELECT (never UPDATE, INSERT or DELETE for these). Collections and fields:
  feedback(id, bill_id, customer, outlet, text, received_on, status), bills(id, customer, outlet, roast_lot_id,
  blend_id, billed_on), deliveries(id, roast_lot_id, outlet, warehouse, bags, status: pending or on_hold),
  roast_lots(id, blend_id, roasted_on, status), suppliers(id, name, city), blends(id, name).
  Join feedback to bills with: FROM feedback f JOIN bills b ON KEYS f.bill_id. Use GROUP BY and ORDER BY for counts.
  Lists use square brackets, for example WHERE d.roast_lot_id IN ["RL-4471", "RL-4480"]."""

# The reviewed query recipes behind each domain tool, shown in the activity view.
RECIPES = {
    "find_similar_complaints": ["01_similar_complaints.sql", "04_search_policies.sql"],
    "who_else_is_affected": ["02_trace_component_lot.sql", "03_assess_impact.sql"],
    "place_quality_hold": ["06_recall_transaction.sql"],
}


def build_agent(tools, checkpointer):
    model = ChatOllama(
        model=config.CHAT_MODEL,
        base_url=config.OLLAMA_URL,
        temperature=0,
        reasoning=False,
        num_ctx=8192,
        keep_alive="2h",
    )
    # tool errors go back to the model as text instead of crashing the session
    return create_react_agent(model, ToolNode(tools, handle_tool_errors=True), prompt=SYSTEM, checkpointer=checkpointer)


def _data(content):
    """Tool results arrive as text: JSON from MCP, or a printed dict from our own tools."""
    out = parse(content)
    if isinstance(out, str):
        try:
            return ast.literal_eval(out)
        except (ValueError, SyntaxError):
            return out
    return out


def _query_of(name: str, args: dict) -> str:
    if name == "run_sql_plus_plus_query":
        return args.get("query", "")
    return "\n\n".join(config.sql(f) for f in RECIPES.get(name, []))


class IncidentSession:
    """The agent, its tools and its conversation memory for one incident."""

    def __init__(self, approver: str):
        self.approver = approver
        self.chain: dict | None = None

    async def open(self) -> "IncidentSession":
        mcp_tools = [t for t in await client().get_tools() if t.name == "run_sql_plus_plus_query"]
        self.run = Sql(mcp_tools[0])
        self.tools = read_tools(self.run) + mcp_tools
        self.memory = InMemorySaver()  # conversation state for this incident only (LangGraph, in-process)
        self.agent = build_agent(self.tools, self.memory)
        return self

    async def feedback(self, feedback_id: str) -> dict:
        rows = await self.run(
            "SELECT f.id, f.text, f.customer, f.outlet, f.bill_id, f.blend_id, f.received_on "
            "FROM feedback f USE KEYS $id",
            id=feedback_id,
        )
        return rows[0]

    async def start(self, feedback_id: str) -> AsyncIterator[dict]:
        self.thread = {"configurable": {"thread_id": f"{feedback_id}-{time.time()}"}, "recursion_limit": 30}
        fb = await self.feedback(feedback_id)
        yield {"type": "complaint", **fb}
        first = f'New feedback {feedback_id} from {fb["customer"]} ({fb["outlet"]}): "{fb["text"]}". Are others seeing this?'
        async for event in self.turn(first):
            yield event

    async def ask(self, text: str) -> AsyncIterator[dict]:
        async for event in self.turn(text):
            yield event

    async def approve(self) -> AsyncIterator[dict]:
        """The human gate: only now does the agent get its single write tool. MCP access stays read-only."""
        self.agent = build_agent(self.tools + write_tools(self.approver), self.memory)
        yield {"type": "approved", "by": self.approver}
        async for event in self.turn(
            f"Approved by {self.approver}. Place the quality hold on the affected roast lots now."
        ):
            yield event

    def proposal(self) -> dict | None:
        """What an approved hold would change, from the data the agent already read. Nothing is written."""
        if not self.chain:
            return None
        lots = self.chain.get("lots", [])
        return {
            "roast_lot_ids": self.chain["roast_lot_ids"],
            "green_bean_lot": self.chain["green_bean_lot"],
            "deliveries": sum(i.get("pending_deliveries", 0) for i in lots),
            "customers": sum(i.get("open_feedback", 0) for i in lots),
            "lots": [
                {"roast_lot_id": i["roast_lot_id"], "pending_deliveries": i.get("pending_deliveries", 0)} for i in lots
            ],
        }

    async def turn(self, text: str) -> AsyncIterator[dict]:
        start = time.perf_counter()
        yield {"type": "thinking"}
        async for update in self.agent.astream({"messages": [HumanMessage(text)]}, self.thread, stream_mode="updates"):
            for payload in update.values():
                for msg in payload.get("messages", []) if isinstance(payload, dict) else []:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            yield {
                                "type": "tool_call",
                                "name": call["name"],
                                "args": {
                                    k: v for k, v in call["args"].items() if k not in ("bucket_name", "scope_name")
                                },
                                "query": _query_of(call["name"], call["args"]),
                            }
                        if not msg.tool_calls and msg.content:
                            reply = " ".join(re.sub(r"<think>.*?</think>", "", str(msg.content), flags=re.S).split())
                            if reply:
                                yield {"type": "answer", "text": reply}
                    elif isinstance(msg, ToolMessage):
                        for event in self._result(msg.name, _data(msg.content)):
                            yield event
        yield {"type": "done", "seconds": round(time.perf_counter() - start, 1)}

    def _result(self, name: str, data) -> list[dict]:
        if name == "run_sql_plus_plus_query":
            if isinstance(data, str) and "read-only" in data:
                message = data.replace("Error calling tool 'run_sql_plus_plus_query': ", "")
                proposal = self.proposal()
                return [{"type": "refused", "message": message}] + (
                    [{"type": "proposal", **proposal}] if proposal else []
                )
            if isinstance(data, list):
                return [{"type": "rows", "rows": data[:20]}]
        elif isinstance(data, dict):
            if name == "find_similar_complaints":
                return [{"type": "similar", **data}]
            if name == "who_else_is_affected":
                self.chain = data
                return [{"type": "chain", **data}]
            if name == "place_quality_hold":
                return [{"type": "resolved", **data}]
        return [
            {"type": "tool_error", "name": name, "message": data if isinstance(data, str) else json.dumps(data)[:300]}
        ]
