from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.database import Base
from app.models import CodeChunk
from app.rag.retrieval import retrieve

def test_retrieval_returns_line_aware_relevant_chunks():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([CodeChunk(repository_id=1,file_path='auth/login.py',language='Python',start_line=10,end_line=20,content='def login_user(password): return verify_password(password)'),CodeChunk(repository_id=1,file_path='ui/home.tsx',language='TSX',start_line=1,end_line=8,content='export function Home() { return null }')]);db.commit()
        result=retrieve(db,1,'Where is password login verification?',limit=3)
        assert result and result[0]['path']=='auth/login.py'
        assert result[0]['start_line']==10
    Base.metadata.drop_all(engine)


def test_retrieval_evaluation_metrics():
    from app.evaluation.metrics import evaluate_retrieval
    metrics = evaluate_retrieval(["a", "x", "b"], {"a", "b"}, k=3)
    assert metrics["precision_at_k"] == 2/3
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 1.0
    assert 0 < metrics["ndcg_at_k"] <= 1


def test_context_builder_respects_budget_and_preserves_citations():
    from app.rag.context import build_context
    sources = [{"path":"src/a.py","start_line":4,"end_line":8,"content":"x"*1000}]
    context = build_context(sources, max_tokens=100)
    assert "src/a.py:4-8" in context
    assert len(context) <= 400


def test_curated_retrieval_golden_dataset_runs_without_external_model(monkeypatch):
    monkeypatch.setattr("app.rag.retrieval.embed_texts", lambda texts: None)
    from scripts import evaluate_retrieval
    monkeypatch.setattr(evaluate_retrieval, "embed_texts", lambda texts: None)
    report = evaluate_retrieval.run(k=5)
    assert report["queries"] == 8
    assert report["dataset_version"] == 1
    assert set(report["aggregate"]) == {"precision_at_k", "recall_at_k", "mrr", "ndcg_at_k"}
    assert all(0 <= value <= 1 for value in report["aggregate"].values())
