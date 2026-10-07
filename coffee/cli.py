"""coffee - the Coffee Circuit command line.

coffee reset                          regenerate + reload the dataset (fresh dates, everything back to open/pending)
coffee feedback "text" [--bill ID]    a customer leaves feedback: embedded by Ollama and stored in Couchbase
coffee chat FEEDBACK_ID               talk to the Quality agent about it   (/approve grants the hold tool, /quit)
coffee walkthrough                    feedback + chat: the four-step walkthrough in the terminal
coffee web [--port 8000]              the same agent in the Quality console (browser)
"""

import argparse
import asyncio
import os
import runpy
import time
from datetime import date

import requests

from . import actions, config, ui
from .embeddings import embed_documents
from .session import IncidentSession

HERO_TEXT = (
    "My filter coffee at Indiranagar tasted burnt and bitter today, with a musty smell. "
    "Is something wrong with the batch?"
)


async def _show(events) -> None:
    """Print one turn's events as the stage terminal trace (tools print their own result cards)."""
    async for e in events:
        kind = e["type"]
        if kind == "complaint":
            ui.card(
                f"👤  {e['customer']} at {e['outlet']}: “{e['text']}”",
                "new feedback, stored and embedded the moment it arrived",
                "white",
            )
        elif kind == "tool_call":
            ui.tool_call(e["name"], e["args"])
            if e["name"] == "run_sql_plus_plus_query":
                ui.sql("agent-written SQL++", e["query"])
        elif kind == "refused":
            ui.refused(e["message"])
        elif kind == "rows":
            ui.rows(e["rows"])
        elif kind == "tool_error":
            ui.rows(e["message"])
        elif kind == "approved":
            ui.out(
                f"\n[bold yellow]✔ {e['by']} approved.[/] [dim]The agent now has one write tool: place_quality_hold "
                "(atomic, idempotent). Its MCP access stays read-only.[/]"
            )
        elif kind == "answer":
            ui.answer(e["text"])
        elif kind == "done":
            ui.out(f"[dim]  ⏱ {e['seconds']:.1f}s[/]")


async def chat(feedback_id: str, approver: str) -> None:
    session = await IncidentSession(approver).open()
    ui.banner(
        "☕ Coffee Circuit · Quality agent",
        f"{config.CHAT_MODEL} on this laptop (Ollama) · data via couchbase-mcp-server, READ-ONLY · Couchbase CE",
    )
    await _show(session.start(feedback_id))
    while True:
        try:
            text = ui.ask("\n[bold cyan]you ›[/] ")
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text in ("/quit", "/exit"):
            break
        if text == "/sql":
            ui.SHOW_SQL = not ui.SHOW_SQL
            ui.out(f"[dim]SQL display {'on' if ui.SHOW_SQL else 'off'}[/]")
            continue
        await _show(session.approve() if text.startswith("/approve") else session.ask(text))


def file_feedback(text: str, bill_id: str | None) -> str:
    c = actions.cluster()
    scope = c.bucket(config.BUCKET).scope(config.SCOPE)
    if not bill_id:
        bill_id = next(
            iter(
                c.query(
                    "SELECT RAW b.id FROM `store`.ops.bills b WHERE b.roast_lot_id = 'RL-4471' AND b.outlet = 'Indiranagar' "
                    "ORDER BY b.billed_on DESC LIMIT 1"
                )
            )
        )
    fid = "FB-HERO" if text == HERO_TEXT else f"FB-{int(time.time())}"
    bill = scope.collection("bills").get(bill_id).content_as[dict]
    doc = {
        "id": fid,
        "type": "feedback",
        "bill_id": bill_id,
        "customer": "Meera" if fid == "FB-HERO" else bill["customer"],
        "outlet": bill["outlet"],
        "blend_id": bill["blend_id"],
        "text": text,
        "received_on": date.today().isoformat(),
        "status": "open",
        "embedding": embed_documents([text])[0],
    }
    scope.collection("feedback").upsert(fid, doc)
    ui.out(f"[dim]✓ feedback {fid} stored and embedded (768-d, nomic-embed-text) · bill {bill_id}[/]")
    return fid


def reset() -> None:
    runpy.run_path(str(config.ROOT / "data" / "generate.py"), run_name="__main__")
    runpy.run_path(str(config.ROOT / "ingest" / "load.py"), run_name="__main__")
    try:  # empty the Mailpit inbox too
        requests.delete(f"{config.MAILPIT_URL}/api/v1/messages", timeout=5)
    except requests.RequestException:
        pass


def main() -> None:
    p = argparse.ArgumentParser(
        prog="coffee", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reset")
    t = sub.add_parser("feedback")
    t.add_argument("text", nargs="?", default=HERO_TEXT)
    t.add_argument("--bill")
    c = sub.add_parser("chat")
    c.add_argument("feedback_id")
    sub.add_parser("walkthrough")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container")
    for s in (c, sub.choices["walkthrough"], w):
        s.add_argument("--as", dest="approver", default=os.getenv("APPROVER", "Akhil (quality lead)"))
    a = p.parse_args()
    if a.cmd == "reset":
        reset()
    elif a.cmd == "feedback":
        file_feedback(a.text, a.bill)
    elif a.cmd == "chat":
        asyncio.run(chat(a.feedback_id, a.approver))
    elif a.cmd == "walkthrough":
        asyncio.run(chat(file_feedback(HERO_TEXT, None), a.approver))
    elif a.cmd == "web":
        from .web import serve

        serve(a.port, a.approver, a.host)


if __name__ == "__main__":
    main()
