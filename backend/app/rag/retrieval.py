"""Hybrid retrieval with reciprocal-rank fusion and source-preserving metadata."""
import math, re
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CodeChunk
from app.services.embeddings import embed_texts
from functools import lru_cache
from app.core.config import get_settings

STOP = {"the","and","for","with","from","that","this","what","where","how","does","into","are","you","your","can","which","when","then","have","has","about","please","explain"}
RRF_K = 60

@lru_cache(maxsize=1)
def _cross_encoder():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(get_settings().reranker_model)

def _terms(question: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", question) if t.lower() not in STOP}

def _lexical(chunks, terms):
    scored=[]
    for chunk in chunks:
        body=chunk.content.lower(); path=chunk.file_path.lower()
        hits=sum(body.count(term) for term in terms)
        path_hits=sum(3 for term in terms if term in path)
        if hits or path_hits:
            scored.append((hits + path_hits, chunk))
    scored.sort(key=lambda item:(item[0], item[1].file_path, -item[1].start_line), reverse=True)
    return scored

def _cosine(a,b):
    dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0

def retrieve(db: Session, repository_id: int, question: str, limit: int = 8,
             language: str | None = None) -> list[dict]:
    terms = _terms(question)
    if not terms: return []
    query = select(CodeChunk).where(CodeChunk.repository_id == repository_id)
    if language: query = query.where(CodeChunk.language == language)
    chunks = db.scalars(query.limit(10000)).all()
    if not chunks: return []
    lexical = _lexical(chunks, terms)
    lexical_rank = {c.id: rank for rank, (_, c) in enumerate(lexical[:limit * 4], start=1)}
    semantic_rank = {}
    vector = embed_texts([question])
    if vector and any(c.embedding is not None for c in chunks):
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            distance = CodeChunk.embedding.cosine_distance(vector[0]).label("distance")
            vector_query = select(CodeChunk, distance).where(CodeChunk.repository_id == repository_id,
                CodeChunk.embedding.is_not(None))
            if language: vector_query = vector_query.where(CodeChunk.language == language)
            rows = db.execute(vector_query.order_by(distance).limit(limit * 4)).all()
            semantic_rows = [(1.0 - float(dist), chunk) for chunk, dist in rows]
        else:
            semantic_rows = [(_cosine(vector[0], c.embedding), c) for c in chunks if c.embedding is not None]
            semantic_rows.sort(key=lambda item:item[0], reverse=True)
        semantic_rank = {c.id: rank for rank, (_, c) in enumerate(semantic_rows[:limit * 4], start=1)}
    by_id = {c.id: c for _, c in lexical[:limit * 4]}
    for c in chunks:
        if c.id in semantic_rank: by_id[c.id] = c
    fused = []
    for chunk_id, chunk in by_id.items():
        lr, sr = lexical_rank.get(chunk_id), semantic_rank.get(chunk_id)
        score = (1 / (RRF_K + lr) if lr else 0) + (1 / (RRF_K + sr) if sr else 0)
        if score:
            fused.append((score, chunk, "hybrid" if lr and sr else "semantic" if sr else "lexical"))
    fused.sort(key=lambda item:item[0], reverse=True)
    candidates = fused[:max(limit, min(limit * 3, 30))]
    reranked = False
    if get_settings().reranker_enabled and candidates:
        try:
            model = _cross_encoder()
            scores = model.predict([(question, chunk.content) for _, chunk, _ in candidates])
            candidates = sorted(zip(scores, candidates), key=lambda pair: float(pair[0]), reverse=True)
            fused = [(float(score), item[1], item[2]) for score, item in candidates]
            reranked = True
        except Exception:
            # Optional reranker unavailable: preserve deterministic RRF ranking.
            pass
    return [{"path":c.file_path,"language":c.language,"start_line":c.start_line,
        "end_line":c.end_line,"content":c.content,"score":float(score),
        "retrieval":"cross-encoder+" + method if reranked else method}
        for score,c,method in fused[:limit]]
