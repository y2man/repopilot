from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
import json
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import current_user
from app.models import User, Conversation, Message
from app.api.repositories import owned_repo
from app.rag.retrieval import retrieve
from app.services.llm import answer, stream_answer
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["repository AI"])
class ChatRequest(BaseModel):
    repository_id: int
    question: str = Field(min_length=3, max_length=6000)
    conversation_id: int | None = None

@router.post("/chat")
async def chat(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    repo = owned_repo(db, body.repository_id, user.id)
    conversation = None
    if body.conversation_id:
        conversation = db.scalar(select(Conversation).where(Conversation.id == body.conversation_id,
            Conversation.owner_id == user.id, Conversation.repository_id == body.repository_id))
        if not conversation: raise HTTPException(404, "Conversation not found")
    else:
        conversation = Conversation(owner_id=user.id, repository_id=body.repository_id,
            title=body.question[:120])
        db.add(conversation); db.commit(); db.refresh(conversation)
    conversation.updated_at = datetime.now(timezone.utc)
    sources = retrieve(db, body.repository_id, body.question)
    db.add(Message(conversation_id=conversation.id, role="user", content=body.question))
    try:
        response = await answer(body.question, sources)
    except Exception:
        db.rollback()
        raise
    source_rows = [{"path":s["path"],"language":s["language"],"start_line":s["start_line"],
        "end_line":s["end_line"],"score":s["score"]} for s in sources]
    db.add(Message(conversation_id=conversation.id, role="assistant", content=response, sources=source_rows))
    db.commit()
    return {"answer":response,"sources":source_rows,"conversation_id":conversation.id}

@router.get("/conversations")
def conversations(repository_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(db, repository_id, user.id)
    rows = db.scalars(select(Conversation).where(Conversation.owner_id == user.id,
        Conversation.repository_id == repository_id).order_by(Conversation.updated_at.desc()).limit(100)).all()
    return [{"id":c.id,"title":c.title,"created_at":c.created_at,"updated_at":c.updated_at} for c in rows]

@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id,
        Conversation.owner_id == user.id))
    if not conversation: raise HTTPException(404, "Conversation not found")
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)).all()
    return [{"id":m.id,"role":m.role,"content":m.content,"sources":m.sources,"created_at":m.created_at} for m in rows]


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(db, body.repository_id, user.id)
    if not get_settings().groq_api_key:
        raise HTTPException(status_code=503, detail="AI provider is not configured. Set GROQ_API_KEY on the backend.")
    conversation = None
    if body.conversation_id:
        conversation = db.scalar(select(Conversation).where(Conversation.id == body.conversation_id,
            Conversation.owner_id == user.id, Conversation.repository_id == body.repository_id))
        if not conversation: raise HTTPException(404, "Conversation not found")
    else:
        conversation = Conversation(owner_id=user.id, repository_id=body.repository_id, title=body.question[:120])
        db.add(conversation); db.commit(); db.refresh(conversation)
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(Message(conversation_id=conversation.id, role="user", content=body.question)); db.commit()
    conversation_id = conversation.id
    async def event_stream():
        collected=[]
        source_rows=[]
        try:
            yield "data: " + json.dumps({"status":"retrieving"}) + "\n\n"
            sources = retrieve(db, body.repository_id, body.question)
            source_rows = [{"path":s["path"],"language":s["language"],"start_line":s["start_line"],
                "end_line":s["end_line"],"score":s["score"]} for s in sources]
            yield "data: " + json.dumps({"status":"generating"}) + "\n\n"
            async for token in stream_answer(body.question, sources):
                collected.append(token)
                yield "data: " + json.dumps({"token":token}, ensure_ascii=False) + "\n\n"
            db.add(Message(conversation_id=conversation_id, role="assistant", content="".join(collected), sources=source_rows))
            db.commit()
            yield "data: " + json.dumps({"done":True,"conversation_id":conversation_id,"sources":source_rows}) + "\n\n"
        except Exception as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc, HTTPException) else "AI streaming failed"
            yield "event: error\ndata: " + json.dumps({"detail":detail}) + "\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})
