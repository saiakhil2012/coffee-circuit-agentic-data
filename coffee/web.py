"""The Quality console: the same agent as the terminal walkthrough, in a browser.

One incident at a time, for one presenter. Each action streams the agent's events back as newline-delimited JSON,
which the page renders as they arrive. Guardrails are unchanged: reads go through the read-only MCP server, and
the single write tool exists only after POST /api/approve.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import actions, config, ui
from .cli import HERO_TEXT, file_feedback, reset
from .session import IncidentSession

STATIC = Path(__file__).parent / "console"
app = FastAPI(title="Coffee Circuit Quality console", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_stale_console(request, call_next):
    """Always revalidate the page and its scripts, so a rebuilt console never runs yesterday's JavaScript."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


_state: dict = {"session": None, "approver": "Akhil (quality lead)"}
_busy = asyncio.Lock()


class Question(BaseModel):
    text: str


class Start(BaseModel):
    feedback_id: str | None = None  # None: Meera's new feedback arrives and is filed first


def _stream(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body():
        try:
            async for event in events:
                yield json.dumps(event, default=str) + "\n"
        except Exception as exc:  # surface the failure in the page instead of a dropped connection
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
        finally:
            _busy.release()

    return StreamingResponse(body(), media_type="application/x-ndjson")


async def _claim(wait: float = 0) -> None:
    """One turn at a time. A stream the browser cancels releases the lock as it closes, so a switch can wait briefly."""
    if wait:
        try:
            await asyncio.wait_for(_busy.acquire(), timeout=wait)
            return
        except TimeoutError:
            pass
    elif not _busy.locked():
        await _busy.acquire()
        return
    raise HTTPException(409, "The agent is still working on the previous step.")


def _session() -> IncidentSession:
    if _state["session"] is None:
        raise HTTPException(409, "Open the incident first.")
    return _state["session"]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def settings() -> dict:
    return {
        "approver": _state["approver"],
        "model": config.CHAT_MODEL,
        "incoming": {"customer": "Meera", "outlet": "Indiranagar", "text": HERO_TEXT},
    }


@app.get("/api/inbox")
def inbox() -> list[dict]:
    rows = actions.cluster().query(
        "SELECT f.id, f.customer, f.outlet, f.text, f.received_on, f.status FROM `store`.ops.feedback f "
        "WHERE f.id != 'FB-HERO' ORDER BY f.received_on DESC, META(f).id DESC LIMIT 8"
    )
    return list(rows)


@app.post("/api/start")
async def start(body: Start | None = None) -> StreamingResponse:
    await _claim(wait=5)

    async def events():
        feedback_id = (body and body.feedback_id) or await run_in_threadpool(file_feedback, HERO_TEXT, None)
        session = await IncidentSession(_state["approver"]).open()
        _state["session"] = session
        async for event in session.start(feedback_id):
            yield event

    return _stream(events())


@app.post("/api/ask")
async def ask(q: Question) -> StreamingResponse:
    session = _session()
    text = q.text.strip()
    if not text:
        raise HTTPException(422, "Type a question first.")
    await _claim()
    return _stream(session.ask(text))


@app.post("/api/approve")
async def approve() -> StreamingResponse:
    session = _session()
    await _claim()
    return _stream(session.approve())


@app.post("/api/reset")
async def reset_data() -> dict:
    await _claim()
    try:
        await run_in_threadpool(reset)
        _state["session"] = None
    finally:
        _busy.release()
    return {"ok": True}


def serve(port: int, approver: str, host: str = "127.0.0.1") -> None:
    import uvicorn

    ui.QUIET = True
    _state["approver"] = approver
    print(f"Quality console: http://localhost:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
