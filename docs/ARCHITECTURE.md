# Architecture

The diagram is in the [README](../README.md#architecture). This page covers the walkthrough step by step, where
each pattern lives in the code, and why the main design choices were made.

## The walkthrough, step by step

A customer at Indiranagar says her filter coffee tasted burnt and musty. The agent works out what happened and,
with a human's approval, acts on it safely:

| step | you do | what happens | what you see |
| --- | --- | --- | --- |
| 1 | open Meera's feedback, press Start analysis | **hybrid search** (keywords + meaning, one SQL++ query) plus the quality SOP it retrieved (**RAG**) | 35 similar complaints · 14 outlets · all from roast lot RL‑4471 |
| 2 | ask “Who else got these beans?” | a **supply‑chain trace**: roast lot → green‑bean batch → every lot made from it (IDs inside the documents, followed with SQL++ joins) | beans GB‑88 also went into RL‑4480 (no complaints yet) · 361 deliveries on the road |
| 3 | ask “Hold those deliveries.” | the agent tries to write through **MCP**; the server is read‑only | change blocked by the data layer, and a proposed action |
| 4 | approve | a human grants one narrow write tool: **one ACID transaction**, then **n8n** emails the managers | 361 deliveries held · 62 customers credited · 2 lots quarantined |

Any other feedback in the inbox can be opened too, and you can ask your own questions: the agent answers them
with read-only queries it writes itself.

## Where each pattern lives

| Pattern | In this repo |
| --- | --- |
| Embeddings | [`coffee/embeddings.py`](../coffee/embeddings.py): local model; the vector is stored on the JSON document next to the text |
| Hybrid search | [`queries/01_similar_complaints.sql`](../queries/01_similar_complaints.sql): `SEARCH()` + `VECTOR_DISTANCE()` in one statement |
| RAG | [`queries/04_search_policies.sql`](../queries/04_search_policies.sql): SOP chunks ranked by meaning, cited in step 1 |
| Supply‑chain trace | [`queries/02_trace_component_lot.sql`](../queries/02_trace_component_lot.sql): IDs stored in the documents, followed with `UNNEST` and joins |
| MCP | [`coffee/mcp.py`](../coffee/mcp.py): the open‑source Couchbase MCP server in its own container, over streamable HTTP, read‑only; the agent sees one tool |
| Narrow tools | [`coffee/tools.py`](../coffee/tools.py): each tool runs one reviewed SQL++ recipe and returns a compact result |
| Agent loop | [`coffee/session.py`](../coffee/session.py): one incident as a stream of typed events, shared by the console and the terminal |
| Quality console | [`coffee/web.py`](../coffee/web.py), [`coffee/console/`](../coffee/console/): FastAPI plus a small no-build web page |
| Containers | [`Dockerfile`](../Dockerfile), [`docker-compose.yml`](../docker-compose.yml): the app, the MCP server, Couchbase, n8n, Mailpit |
| Safe actions | [`coffee/actions.py`](../coffee/actions.py), [`queries/06_recall_transaction.sql`](../queries/06_recall_transaction.sql): approved, atomic, idempotent |
| Automation | [`n8n/recall-notify.workflow.json`](../n8n/recall-notify.workflow.json): webhook → email |

Context management, agent memory and multi‑agent orchestration are architecture concerns too, but they are out of
scope for this small implementation.

## Design choices

**Why not write through the MCP server?** It can (set `CB_MCP_READ_ONLY_MODE=false` for document upserts and
data-modifying SQL++, with optional confirmation prompts). But the quality hold is three changes that must happen
together: 361 deliveries, 62 feedback records and 2 roast lots. The MCP server has no multi-statement
transaction tool, so three separate calls could leave half a hold behind if one fails. Opening generic writes
would also let the agent change any document. Instead, after approval it gets exactly one action, and that action
runs as a single ACID transaction. The server's own write controls (per-tool confirmation through MCP elicitation,
and read or write scopes on OAuth tokens over HTTP) suit single-document writes; a multi-step business action like
this one is better served by a narrow, purpose-built tool.

**Why is the MCP server its own container?** That is how it runs in production: one long-lived service that any
agent or MCP client can reach over HTTP, with its own credentials and settings, instead of a copy started inside
each app. `MCP_URL=stdio` starts it as a child process of the app instead, which needs no extra service.

**Why does Ollama run outside Docker?** On macOS, containers cannot use the Apple GPU, so the model would be several
times slower. The app container reaches the native Ollama at `host.docker.internal:11434`.

## Community Edition only

The implementation uses only what Couchbase Server **Community Edition** provides (Data, Query, Index and Search
services; SQL++ with joins; distributed ACID transactions). It does not use or re‑implement any Enterprise
Edition or Capella feature.

- Couchbase Server CE 8.0.2 (arm64) Search does not expose vector fields, so vectors are ranked with SQL++
  `VECTOR_DISTANCE()` (exact k‑NN), which is fast at this scale.
- CE does not support the Magma storage engine, so the bucket uses `couchstore`.
- Inside SDK transactions, SQL++ keyspaces are fully qualified.
