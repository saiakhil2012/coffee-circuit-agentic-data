/* Blast radius per roast lot: cups sold, open feedback, bags still on their way to outlets. */
WITH sold    AS (SELECT b.roast_lot_id, COUNT(*) AS n, COUNT(DISTINCT b.outlet) AS outlets FROM bills b
                 WHERE b.roast_lot_id IN $roast_lot_ids GROUP BY b.roast_lot_id),
     pending AS (SELECT d.roast_lot_id, COUNT(*) AS n, SUM(d.bags) AS bags FROM deliveries d
                 WHERE d.roast_lot_id IN $roast_lot_ids AND d.status = "pending" GROUP BY d.roast_lot_id),
     open_f  AS (SELECT b.roast_lot_id, COUNT(*) AS n FROM feedback f JOIN bills b ON KEYS f.bill_id
                 WHERE b.roast_lot_id IN $roast_lot_ids AND f.status = "open" GROUP BY b.roast_lot_id)
SELECT r.id AS roast_lot_id, r.blend_id, r.status,
       IFMISSINGORNULL(FIRST x.n FOR x IN sold    WHEN x.roast_lot_id = r.id END, 0)       AS cups_sold,
       IFMISSINGORNULL(FIRST x.outlets FOR x IN sold WHEN x.roast_lot_id = r.id END, 0) AS outlets_served,
       IFMISSINGORNULL(FIRST x.n FOR x IN pending WHEN x.roast_lot_id = r.id END, 0)       AS pending_deliveries,
       IFMISSINGORNULL(FIRST x.bags FOR x IN pending WHEN x.roast_lot_id = r.id END, 0)    AS bags_in_transit,
       IFMISSINGORNULL(FIRST x.n FOR x IN open_f  WHEN x.roast_lot_id = r.id END, 0)       AS open_feedback
FROM roast_lots r USE KEYS $roast_lot_ids
