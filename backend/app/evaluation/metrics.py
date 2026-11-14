"""Small offline retrieval-quality metrics for curated relevance judgments."""
import math

def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if k <= 0: return 0.0
    return sum(item in relevant for item in retrieved[:k]) / k

def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant: return 0.0
    return sum(item in relevant for item in retrieved[:k]) / len(relevant)

def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for index, item in enumerate(retrieved, start=1):
        if item in relevant: return 1.0 / index
    return 0.0

def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    dcg = sum((1.0 / math.log2(index + 1)) for index,item in enumerate(retrieved[:k], start=1) if item in relevant)
    ideal = sum(1.0 / math.log2(index + 1) for index in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0

def evaluate_retrieval(retrieved: list[str], relevant: set[str], k: int = 10) -> dict[str, float]:
    return {"precision_at_k":precision_at_k(retrieved,relevant,k),
            "recall_at_k":recall_at_k(retrieved,relevant,k),
            "mrr":reciprocal_rank(retrieved,relevant),"ndcg_at_k":ndcg_at_k(retrieved,relevant,k)}
