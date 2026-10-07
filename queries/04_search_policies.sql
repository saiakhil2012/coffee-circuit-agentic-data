/* RAG retrieval: nearest SOP chunks to the question vector ($qv is computed by the client with Ollama). */
SELECT p.doc_id, p.title, p.text, ROUND(VECTOR_DISTANCE(p.embedding, $qv, "cosine"), 3) AS distance
FROM sop_docs p
ORDER BY distance
LIMIT 3
