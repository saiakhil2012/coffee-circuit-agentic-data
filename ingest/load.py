"""Load the generated dataset into Couchbase CE, embedding tickets and SOP chunks with Ollama.

Vectors are stored as plain JSON arrays on the documents. Ranking happens in SQL++
with VECTOR_DISTANCE() - no vector index (Community Edition), exact nearest neighbours.
"""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions
from rich.progress import track

from coffee.embeddings import embed_documents as embed

DATA = Path(__file__).resolve().parent.parent / "data" / "generated"


def chunks(text: str, size: int = 280) -> list[str]:
    """Sentence-packing chunker: keeps sentences whole, ~size characters per chunk."""
    out, cur = [], ""
    for s in text.replace("? ", "?|").replace(". ", ".|").split("|"):
        if cur and len(cur) + len(s) > size:
            out.append(cur.strip())
            cur = ""
        cur += s + " "
    if cur.strip():
        out.append(cur.strip())
    return out


def main() -> None:
    if not DATA.exists():
        sys.exit("run `uv run python data/generate.py` first")
    cluster = Cluster(
        os.getenv("CB_CONNECTION_STRING", "couchbase://localhost"),
        ClusterOptions(
            PasswordAuthenticator(os.getenv("CB_USERNAME", "Administrator"), os.getenv("CB_PASSWORD", "password"))
        ),
    )
    cluster.wait_until_ready(timedelta(seconds=30))
    scope = cluster.bucket("store").scope("ops")

    for name in ["suppliers", "blends", "roast_lots", "bills", "deliveries"]:
        coll = scope.collection(name)
        rows = json.loads((DATA / f"{name}.json").read_text())
        coll.upsert_multi({r["id"]: {**r, "type": name.rstrip("s")} for r in rows})
        print(f"  {name:10s} {len(rows):5d}")

    tickets = json.loads((DATA / "feedback.json").read_text())
    coll = scope.collection("feedback")
    for i in track(range(0, len(tickets), 32), description="  embedding feedback"):
        batch = tickets[i : i + 32]
        vecs = embed([t["text"] for t in batch])
        coll.upsert_multi(
            {t["id"]: {**t, "type": "feedback", "embedding": v} for t, v in zip(batch, vecs, strict=True)}
        )
    print(f"  feedback   {len(tickets):5d}")

    sops = json.loads((DATA / "sop_docs.json").read_text())
    coll = scope.collection("sop_docs")
    n = 0
    for doc in sops:
        parts = chunks(doc["text"])
        for j, (text, v) in enumerate(zip(parts, embed(parts), strict=True)):
            coll.upsert(
                f"{doc['id']}::{j}",
                {
                    "type": "sop_chunk",
                    "doc_id": doc["id"],
                    "title": doc["title"],
                    "chunk": j,
                    "text": text,
                    "embedding": v,
                },
            )
            n += 1
    print(f"  sop chunks {n:5d}")


if __name__ == "__main__":
    main()
