/* Supply-chain trace in documents: roast lot -> green-bean batch -> every roast lot made from that batch -> supplier. */
SELECT sib.id AS roast_lot_id, sib.blend_id, c.part, c.lot,
       s.name || " (" || s.city || ")" AS supplier
FROM roast_lots sib
UNNEST sib.components AS c
JOIN suppliers s ON KEYS c.supplier_id
WHERE c.lot IN (SELECT RAW rc.lot FROM roast_lots r USE KEYS $roast_lot_id UNNEST r.components AS rc
                WHERE rc.part = "green beans")
ORDER BY sib.id
