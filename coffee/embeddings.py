"""Local embeddings with Ollama (nomic-embed-text, 768-d). L2-normalised, so cosine == dot product."""

import math

import requests

from . import config


def _embed(inputs: list[str]) -> list[list[float]]:
    r = requests.post(
        f"{config.OLLAMA_URL}/api/embed", json={"model": config.EMBED_MODEL, "input": inputs}, timeout=120
    )
    r.raise_for_status()
    out = []
    for v in r.json()["embeddings"]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([round(x / n, 6) for x in v])
    return out


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed([f"search_document: {t}" for t in texts])


def embed_query(text: str) -> list[float]:
    return _embed([f"search_query: {text}"])[0]
