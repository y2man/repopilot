"""Run the curated offline retrieval smoke benchmark and print aggregate metrics."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.evaluation.metrics import evaluate_retrieval
from app.models import CodeChunk
from app.rag.retrieval import retrieve
from app.services.embeddings import embed_texts

DATASET = Path(__file__).resolve().parents[1] / "evaluation" / "data" / "retrieval_golden.json"


def run(k: int = 5) -> dict:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        docs = dataset["documents"]
        vectors = embed_texts([doc["content"] for doc in docs])
        chunks = []
        for index, doc in enumerate(docs):
            chunk = CodeChunk(repository_id=1, file_path=doc["path"], language=doc["language"],
                start_line=1, end_line=max(1, len(doc["content"].splitlines())), content=doc["content"])
            if vectors:
                chunk.embedding = vectors[index]
            chunks.append(chunk)
        db.add_all(chunks)
        db.commit()
        per_query = []
        for case in dataset["queries"]:
            results = retrieve(db, 1, case["question"], limit=k)
            ranked_paths = [row["path"] for row in results]
            metrics = evaluate_retrieval(ranked_paths, set(case["relevant_paths"]), k=k)
            per_query.append({"question": case["question"], "ranked_paths": ranked_paths, **metrics})
    aggregate = {
        key: sum(item[key] for item in per_query) / max(1, len(per_query))
        for key in ("precision_at_k", "recall_at_k", "mrr", "ndcg_at_k")
    }
    return {"dataset_version": dataset["version"], "queries": len(per_query),
            "k": k, "retrieval_mode": "hybrid" if vectors is not None else "lexical_fallback",
            "embedding_model_available": vectors is not None,
            "aggregate": aggregate, "results": per_query}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
