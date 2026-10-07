/* Executed inside ONE distributed ACID transaction (Python SDK cluster.transactions.run).
   All three succeed together or none do. Keyspaces are fully qualified inside transactions. */
UPDATE `store`.ops.deliveries SET status = "on_hold", hold_reason = $reason, held_at = NOW_STR()
 WHERE roast_lot_id IN $roast_lot_ids AND status = "pending"
 RETURNING META().id;

UPDATE `store`.ops.feedback f SET f.status = "credit_offered", f.resolution = "Free coffee credit (quality hold " || $hold_id || ")"
 WHERE f.status = "open" AND f.bill_id IN (SELECT RAW b.id FROM `store`.ops.bills b WHERE b.roast_lot_id IN $roast_lot_ids)
 RETURNING META(f).id;

UPDATE `store`.ops.roast_lots r SET r.status = "quarantined", r.hold = {"id": $hold_id, "green_bean_lot": $lot, "reason": $reason, "approved_by": $approved_by, "at": NOW_STR()}
 WHERE META(r).id IN $roast_lot_ids AND r.status = "active"
 RETURNING META(r).id;
