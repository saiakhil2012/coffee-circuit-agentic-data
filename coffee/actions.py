"""The one write path: a quality hold executed as a single distributed ACID transaction (Couchbase CE)."""

from datetime import timedelta

import requests
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, TransactionQueryOptions

from . import config

_cluster = None


def cluster() -> Cluster:
    global _cluster
    if _cluster is None:
        _cluster = Cluster(
            config.CB_CONNECTION_STRING, ClusterOptions(PasswordAuthenticator(config.CB_USERNAME, config.CB_PASSWORD))
        )
        _cluster.wait_until_ready(timedelta(seconds=20))
    return _cluster


def hold_roast_lots(roast_lot_ids: list[str], green_bean_lot: str, reason: str, approved_by: str) -> dict:
    """Hold pending deliveries, credit affected customers, quarantine the lots - all or nothing.
    Idempotent per green-bean lot: a second call finds the lots already quarantined and changes nothing."""
    c = cluster()
    hold_id = f"HOLD-{green_bean_lot}"
    deliveries, feedback, lots = [s.strip() for s in config.sql("06_recall_transaction.sql").split(";") if s.strip()]
    counts: dict = {}

    def txn(ctx):
        opts = lambda **p: TransactionQueryOptions(named_parameters=p)  # noqa: E731
        already = ctx.query(
            "SELECT RAW r.status FROM `store`.ops.roast_lots r USE KEYS $ids", opts(ids=roast_lot_ids)
        ).rows()
        if already and all(s == "quarantined" for s in already):
            counts["already_done"] = True
            return
        params = dict(
            roast_lot_ids=roast_lot_ids, reason=reason, hold_id=hold_id, lot=green_bean_lot, approved_by=approved_by
        )
        counts["deliveries_on_hold"] = len(ctx.query(deliveries, opts(**params)).rows())
        counts["customers_credited"] = len(ctx.query(feedback, opts(**params)).rows())
        counts["lots_quarantined"] = len(ctx.query(lots, opts(**params)).rows())

    c.transactions.run(txn)
    result = {"hold_id": hold_id, "roast_lot_ids": roast_lot_ids, "green_bean_lot": green_bean_lot, **counts}
    if not counts.get("already_done"):
        result["notification"] = notify(result, reason, approved_by)
    return result


def notify(result: dict, reason: str, approved_by: str) -> str:
    """Hand off to n8n (self-hosted) which emails the area managers."""
    try:
        r = requests.post(
            config.N8N_NOTIFY_URL, json={**result, "reason": reason, "approved_by": approved_by}, timeout=10
        )
        r.raise_for_status()
        return "sent via n8n"
    except requests.RequestException as e:
        return f"n8n not reachable ({type(e).__name__}) - hold committed, email not sent"
