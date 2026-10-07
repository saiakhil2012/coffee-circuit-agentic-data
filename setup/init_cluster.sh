#!/usr/bin/env bash
# Initialise a single-node Couchbase Server Community Edition cluster for Coffee Circuit.
# Runs from the host; talks to the container via `docker exec` + REST on localhost.
# Uses only Community Edition features: Data, Query, Index (GSI), Search (full-text).
# Note: CE 8.0.2 Search does not advertise the "vectors" feature, so vector ranking uses
# the SQL++ VECTOR_DISTANCE() function (exact KNN) instead of a vector index.
set -euo pipefail

CB_USER="${CB_USERNAME:-Administrator}"
CB_PASS="${CB_PASSWORD:-password}"
BUCKET=store
SCOPE=ops
COLLECTIONS=(feedback bills blends roast_lots suppliers deliveries sop_docs)
HERE="$(cd "$(dirname "$0")" && pwd)"
cli() { docker exec coffee-couchbase /opt/couchbase/bin/couchbase-cli "$@"; }

echo "▸ waiting for Couchbase REST"
until curl -fsS http://localhost:8091/ui/index.html >/dev/null 2>&1; do sleep 2; done

if curl -fsS -u "$CB_USER:$CB_PASS" http://localhost:8091/pools/default >/dev/null 2>&1; then
  echo "▸ cluster already initialised"
else
  # The node is named "couchbase.coffee.internal" so other containers (the app) reach it on the compose network; "localhost" is
  # registered below as its alternate address so tools on the host still connect through the published ports.
  echo "▸ node-init (hostname couchbase.coffee.internal)"
  cli node-init -c localhost -u "$CB_USER" -p "$CB_PASS" --node-init-hostname couchbase.coffee.internal
  echo "▸ cluster-init (data, index, query, fts)"
  cli cluster-init -c localhost --cluster-name coffee-circuit \
    --cluster-username "$CB_USER" --cluster-password "$CB_PASS" \
    --services data,index,query,fts \
    --cluster-ramsize 768 --cluster-index-ramsize 256 --cluster-fts-ramsize 512 \
    --index-storage-setting default
fi

cli setting-alternate-address -c localhost -u "$CB_USER" -p "$CB_PASS" --set --node couchbase.coffee.internal --hostname localhost >/dev/null
curl -fsS -u "$CB_USER:$CB_PASS" http://localhost:8091/pools | python3 -c 'import json,sys; d=json.load(sys.stdin); print("▸ edition:", "Enterprise" if d.get("isEnterprise") else "Community", d.get("implementationVersion"))'

if ! cli bucket-list -c localhost -u "$CB_USER" -p "$CB_PASS" | grep -qx "$BUCKET"; then
  echo "▸ bucket $BUCKET"
  cli bucket-create -c localhost -u "$CB_USER" -p "$CB_PASS" \
    --bucket "$BUCKET" --bucket-type couchbase --bucket-ramsize 512 --bucket-replica 0 --storage-backend couchstore --wait
fi

echo "▸ scope/collections"
cli collection-manage -c localhost -u "$CB_USER" -p "$CB_PASS" --bucket "$BUCKET" --create-scope "$SCOPE" >/dev/null 2>&1 || true
for c in "${COLLECTIONS[@]}"; do
  cli collection-manage -c localhost -u "$CB_USER" -p "$CB_PASS" --bucket "$BUCKET" \
    --create-collection "$SCOPE.$c" >/dev/null 2>&1 || true
done
sleep 3

echo "▸ GSI indexes"
q() {
  curl -fsS -u "$CB_USER:$CB_PASS" http://localhost:8093/query/service \
    --data-urlencode "statement=$1" >/dev/null || echo "  (skipped: $1)"
}
K="\`$BUCKET\`.\`$SCOPE\`"
for c in "${COLLECTIONS[@]}"; do q "CREATE PRIMARY INDEX IF NOT EXISTS ON $K.\`$c\`"; done
q "CREATE INDEX IF NOT EXISTS ix_bills_lot ON $K.bills(roast_lot_id)"
q "CREATE INDEX IF NOT EXISTS ix_deliveries_lot ON $K.deliveries(roast_lot_id, status)"
q "CREATE INDEX IF NOT EXISTS ix_feedback_bill ON $K.feedback(bill_id, status)"

echo "▸ Search (full-text) indexes - vectors are ranked in SQL++ with VECTOR_DISTANCE()"
for idx in feedback_fts sop_fts; do
  curl -fsS -u "$CB_USER:$CB_PASS" -X PUT \
    "http://localhost:8094/api/bucket/$BUCKET/scope/$SCOPE/index/$idx" \
    -H 'Content-Type: application/json' -d @"$HERE/$idx.json" >/dev/null
done

echo "✓ cluster ready · UI at http://localhost:8091 ($CB_USER / $CB_PASS)"
