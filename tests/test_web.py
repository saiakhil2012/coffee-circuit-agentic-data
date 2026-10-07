"""End-to-end check of the Quality console API: the four beats over HTTP, with the live model.

Needs the running stack (./scripts/up.sh) and Ollama. Takes about a minute and a half.
    uv run python tests/test_web.py
"""

import json

import requests
from fastapi.testclient import TestClient

from coffee import ui
from coffee.cli import reset
from coffee.web import app


def events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def first(evs: list[dict], kind: str) -> dict:
    found = [e for e in evs if e["type"] == kind]
    errors = [e.get("message") for e in evs if e["type"] == "error"]
    assert found, f"no {kind!r} event in {[e['type'] for e in evs]} {errors}"
    return found[0]


def main() -> None:
    ui.QUIET = True
    reset()
    with TestClient(app) as client:  # one event loop for the whole incident, as under uvicorn
        run(client)
    reset()
    print("✓ data reset for the next run")


def run(client: TestClient) -> None:
    beat1 = events(client.post("/api/start"))
    similar = first(beat1, "similar")
    assert similar["top_lot"] == "RL-4471" and similar["similar_complaints"] >= 25, similar
    print(
        f"✓ beat 1: {similar['similar_complaints']} similar complaints, {similar['outlets']} outlets, {similar['top_lot']}"
    )

    beat2 = events(client.post("/api/ask", json={"text": "Who else got these beans?"}))
    chain = first(beat2, "chain")
    assert "RL-4480" in chain["roast_lot_ids"] and chain["pending_deliveries"] == 361, chain
    print(
        f"✓ beat 2: batch {chain['green_bean_lot']} → {chain['roast_lot_ids']}, {chain['pending_deliveries']} on the road"
    )

    beat3 = events(client.post("/api/ask", json={"text": "Hold those deliveries."}))
    first(beat3, "refused")
    proposal = first(beat3, "proposal")
    assert (proposal["deliveries"], proposal["customers"], len(proposal["roast_lot_ids"])) == (361, 62, 2), proposal
    print("✓ beat 3: write refused by the data layer; proposal 361 / 62 / 2")

    beat4 = events(client.post("/api/approve"))
    done = first(beat4, "resolved")
    assert (done["deliveries_on_hold"], done["customers_credited"], done["lots_quarantined"]) == (361, 62, 2), done
    mail = requests.get("http://localhost:8025/api/v1/messages", timeout=5).json()
    assert any("HOLD-GB-88" in m["Subject"] for m in mail["messages"]), mail
    print("✓ beat 4: approved, one ACID transaction (361 / 62 / 2), area managers emailed")


if __name__ == "__main__":
    main()
