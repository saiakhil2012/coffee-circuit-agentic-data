"""Domain tools for the agent. Each step of the walkthrough uses one tool; each tool runs reviewed SQL++ recipes through
the read-only Couchbase MCP server, prints one result card in the terminal and returns the data for the web
console. Narrow tools suit a small model."""

from langchain_core.tools import tool

from . import config, ui
from .actions import hold_roast_lots
from .embeddings import embed_query
from .mcp import Sql

DEFAULT_KEYWORDS = "burnt bitter musty smell stale sour kadwa"
BLENDS = {
    "BL-FILTER": "Filter Coffee Classic",
    "BL-STRONG": "Mysore Strong",
    "BL-COLD": "Cold Brew",
    "BL-ESP": "Espresso House",
    "BL-DECAF": "Decaf Filter",
}


def read_tools(run: Sql):
    @tool
    async def find_similar_complaints(feedback_id: str) -> dict | str:
        """Hybrid search (keywords + meaning) for feedback similar to one feedback item over the last 14 days,
        grouped by the roast lot that was served, plus the quality SOP that applies. Use for "are others seeing this?"."""
        stmt = config.sql("01_similar_complaints.sql")
        ui.sql("hybrid search: SEARCH() + VECTOR_DISTANCE()", stmt)
        # Taste-defect complaints use a fixed taste vocabulary (stable between runs); anything else searches by its own words.
        found = await run("SELECT f.text FROM feedback f USE KEYS $id", id=feedback_id)  # MCP rows must be objects
        text = found[0].get("text", "") if isinstance(found, list) and found else ""
        taste = any(w in text.lower() for w in DEFAULT_KEYWORDS.split())
        rows = await run(stmt, feedback_id=feedback_id, keywords=DEFAULT_KEYWORDS if taste else text)
        if isinstance(rows, str) or not rows:
            return rows or "no similar complaints"
        sop = await run(
            config.sql("04_search_policies.sql"), qv=embed_query("quality hold procedure for bad taste complaints")
        )
        top, cite = rows[0], (sop[0] if isinstance(sop, list) and sop else {})
        ui.card(
            f"🔎  {top['similar_complaints']} similar complaints  ·  {top['outlets']} outlets  ·  all from roast lot {top['roast_lot_id']}",
            f"hybrid search: keywords + meaning, one SQL++ query   ·   {cite.get('doc_id', 'SOP')}: 10+ in 14 days → hold the lot",
            "cyan",
        )
        return {
            "top_lot": top["roast_lot_id"],
            "similar_complaints": top["similar_complaints"],
            "outlets": top["outlets"],
            "blend": BLENDS.get(top.get("blend_id"), top.get("blend_id")),
            "other_lots": rows[1:],
            "sop": cite.get("doc_id"),
            "sop_text": cite.get("text", "")[:300],
        }

    @tool
    async def who_else_is_affected(roast_lot_id: str) -> dict | str:
        """Supply-chain trace: find the green-bean batch a roast lot was made from, EVERY roast lot (any blend) made from that
        same batch, and how many of their deliveries are still on the road. Use for "who else got these beans?"."""
        stmt = config.sql("02_trace_component_lot.sql")
        ui.sql("supply-chain trace: roast lot → green-bean batch → sibling lots", stmt)
        rows = await run(stmt, roast_lot_id=roast_lot_id)
        if isinstance(rows, str):
            return rows
        beans = next((r for r in rows if r["part"] == "green beans"), None)
        lots = sorted({r["roast_lot_id"] for r in rows if beans and r["lot"] == beans["lot"]})
        impact = await run(config.sql("03_assess_impact.sql"), roast_lot_ids=lots)
        if isinstance(impact, str):
            return impact
        taste = await run(
            "SELECT b.roast_lot_id, COUNT(*) AS n FROM feedback f JOIN bills b ON KEYS f.bill_id "
            'WHERE b.roast_lot_id IN $ids AND SEARCH(f, {"match": $kw, "field": "text"}) GROUP BY b.roast_lot_id',
            ids=lots,
            kw=DEFAULT_KEYWORDS,
        )
        complaints = {t["roast_lot_id"]: t["n"] for t in taste} if isinstance(taste, list) else {}
        for i in impact:
            i["taste_complaints"] = complaints.get(i["roast_lot_id"], 0)
            i["blend"] = BLENDS.get(i["blend_id"], i["blend_id"])
        others = [i for i in impact if i["roast_lot_id"] != roast_lot_id]
        pending = sum(i["pending_deliveries"] for i in impact)
        sib = ", ".join(
            f"{i['roast_lot_id']} ({BLENDS.get(i['blend_id'], i['blend_id'])}, "
            f"{complaints.get(i['roast_lot_id'], 0) or 'no'} taste complaints yet)"
            for i in others
        )
        ui.card(
            f"🕸  Beans {beans['lot']} ({beans['supplier']}) also went into {sib or 'no other lot'}",
            f"🚚  {pending} deliveries still on the road: "
            + " · ".join(f"{i['roast_lot_id']}: {i['pending_deliveries']}" for i in impact),
            "magenta",
        )
        return {
            "green_bean_lot": beans["lot"],
            "supplier": beans["supplier"],
            "roast_lot_ids": lots,
            "pending_deliveries": pending,
            "lots": impact,
        }

    return [find_similar_complaints, who_else_is_affected]


def write_tools(approved_by: str):
    @tool
    def place_quality_hold(roast_lot_ids: list[str], green_bean_lot: str, reason: str) -> dict:
        """Place an approved quality hold on the given roast lots made from a bad green-bean batch, as ONE atomic
        transaction: hold every pending delivery, credit customers with open feedback, quarantine the lots.
        Safe to retry: running it twice for the same batch changes nothing the second time."""
        stmt = config.sql("06_recall_transaction.sql")
        ui.sql(
            "ACID transaction (3 statements, all-or-nothing)",
            stmt,
            via="Couchbase Python SDK · cluster.transactions.run()",
        )
        out = hold_roast_lots(roast_lot_ids, green_bean_lot, reason, approved_by)
        if out.get("already_done"):
            ui.card("↺  Already on hold: nothing changed (idempotent)", f"hold {out['hold_id']}", "yellow")
        else:
            mail = (
                "📧 area managers emailed"
                if out.get("notification") == "sent via n8n"
                else f"⚠ {out.get('notification')}"
            )
            ui.card(
                f"✅  {out['deliveries_on_hold']} deliveries held  ·  {out['customers_credited']} customers credited  ·  "
                f"{out['lots_quarantined']} lots quarantined",
                f"one ACID transaction  ·  {mail}",
                "green",
            )
        return out

    return [place_quality_hold]
