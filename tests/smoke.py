"""Fast pre-stage check, no LLM: edition, every SQL++ recipe through the read-only MCP server,
and the read-only refusal. Run after `uv run coffee reset`:  uv run python tests/smoke.py"""

import asyncio

import requests

from coffee import config
from coffee.embeddings import embed_query
from coffee.mcp import Sql, client


async def main() -> None:
    pools = requests.get("http://localhost:8091/pools", auth=(config.CB_USERNAME, config.CB_PASSWORD), timeout=5).json()
    assert not pools["isEnterprise"], "expected Community Edition"
    print(f"✓ Couchbase {pools['implementationVersion']} (Community Edition)")

    tools = {t.name: t for t in await client().get_tools()}
    assert set(tools) == set(config.MCP_ALLOWED_TOOLS), f"unexpected MCP tools: {sorted(tools)}"
    run = Sql(tools["run_sql_plus_plus_query"])
    print(f"✓ MCP server up, read-only, exposing {sorted(tools)}")

    similar = await run(
        config.sql("01_similar_complaints.sql"),
        feedback_id="FB-HERO",
        keywords="burnt bitter musty smell stale sour kadwa",
    )
    assert similar[0]["roast_lot_id"] == "RL-4471" and similar[0]["similar_complaints"] >= 25, similar
    print(
        f"✓ hybrid search: {similar[0]['similar_complaints']} similar complaints, {similar[0]['outlets']} outlets, lot RL-4471"
    )

    lots = await run(config.sql("02_trace_component_lot.sql"), roast_lot_id="RL-4471")
    assert {"RL-4471", "RL-4480"} <= {r["roast_lot_id"] for r in lots if r["lot"] == "GB-88"}, lots
    print("✓ supply-chain trace: green-bean batch GB-88 also roasted into RL-4480")

    impact = await run(config.sql("03_assess_impact.sql"), roast_lot_ids=["RL-4471", "RL-4480"])
    pending = sum(r["pending_deliveries"] for r in impact)
    assert pending == 361, impact
    print(f"✓ impact: {pending} pending deliveries, {sum(r['bags_in_transit'] for r in impact)} bags in transit")

    sop = await run(config.sql("04_search_policies.sql"), qv=embed_query("what is the quality hold procedure?"))
    assert sop[0]["doc_id"] == "SOP-QUALITY", sop
    print("✓ RAG: SOP-QUALITY is the top passage")

    refused = await run("UPDATE deliveries SET status = 'on_hold' WHERE roast_lot_id = 'RL-4471'")
    assert isinstance(refused, str) and "read-only" in refused, refused
    print("✓ write through MCP refused (read-only mode)")


if __name__ == "__main__":
    asyncio.run(main())
