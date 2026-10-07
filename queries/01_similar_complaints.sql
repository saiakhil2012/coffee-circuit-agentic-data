/* Hybrid search: full-text SEARCH() narrows by taste words, VECTOR_DISTANCE() ranks by meaning.
   The query vector is the new feedback's own embedding, already stored on the feedback document. */
WITH qv    AS ((SELECT RAW h.embedding FROM feedback h USE KEYS $feedback_id)[0]),
     asof  AS ((SELECT RAW h.received_on FROM feedback h USE KEYS $feedback_id)[0])
SELECT b.roast_lot_id, b.blend_id,
       COUNT(*)                         AS similar_complaints,
       COUNT(DISTINCT b.outlet)         AS outlets,
       MIN(f.received_on)               AS first_seen,
       ARRAY_AGG(DISTINCT f.text)[0:4]  AS sample_texts
FROM feedback f JOIN bills b ON KEYS f.bill_id
WHERE f.id != $feedback_id
  AND DATE_DIFF_STR(asof, f.received_on, "day") BETWEEN 0 AND 14
  AND SEARCH(f, {"match": $keywords, "field": "text"})
  AND VECTOR_DISTANCE(f.embedding, qv, "cosine") < 0.42
GROUP BY b.roast_lot_id, b.blend_id
ORDER BY similar_complaints DESC
