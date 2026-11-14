from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_token, current_user
from app.models import User
from app.core.audit import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
class UserOut(BaseModel):
    id: int
    email: str
    model_config = {"from_attributes": True}
@router.post("/register")
def register(body: Credentials, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password)); db.add(user)
    try:
        db.flush()
        record_audit(db, action="auth.register", owner_id=user.id, resource_type="user", resource_id=user.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    db.refresh(user)
    return {"access_token":create_token(user.id),"token_type":"bearer","user":UserOut.model_validate(user)}
@router.post("/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash): raise HTTPException(401, "Invalid email or password")
    record_audit(db, action="auth.login", owner_id=user.id, resource_type="user", resource_id=user.id)
    db.commit()
    return {"access_token":create_token(user.id),"token_type":"bearer","user":UserOut.model_validate(user)}
@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)): return user

from fastapi import Query
from fastapi.responses import RedirectResponse
import httpx
from app.core.security import decode_token, encrypt_credential
from app.core.config import get_settings

@router.get("/github/start")
def github_oauth_start(user: User = Depends(current_user)):
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(503, "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.")
    state = create_token(user.id)
    from urllib.parse import urlencode
    params = urlencode({"client_id":settings.github_client_id,"redirect_uri":f"{settings.public_api_url.rstrip('/')}/api/v1/auth/github/callback",
        "scope":"read:user repo", "state":state})
    return {"authorization_url":f"https://github.com/login/oauth/authorize?{params}"}

@router.get("/github/callback", include_in_schema=False)
async def github_oauth_callback(code: str = Query(min_length=1), state: str = Query(min_length=1), db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        user_id = decode_token(state)
        user = db.get(User, user_id)
        if not user: raise ValueError("unknown user")
        async with httpx.AsyncClient(timeout=30) as client:
            token_response = await client.post("https://github.com/login/oauth/access_token",
                headers={"Accept":"application/json"}, json={"client_id":settings.github_client_id,
                    "client_secret":settings.github_client_secret,"code":code})
            token_response.raise_for_status()
            token_data = token_response.json()
            access_token = token_data.get("access_token")
            if not access_token: raise ValueError("OAuth token exchange failed")
            profile = await client.get("https://api.github.com/user",
                headers={"Authorization":f"Bearer {access_token}","Accept":"application/vnd.github+json"})
            profile.raise_for_status()
        user.github_access_token_encrypted = encrypt_credential(access_token)
        record_audit(db, action="github.oauth_connected", owner_id=user.id, resource_type="user", resource_id=user.id)
        db.commit()
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/?github=connected", status_code=303)
    except Exception:
        db.rollback()
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/?github=error", status_code=303)

@router.get("/github/status")
def github_oauth_status(user: User = Depends(current_user)):
    return {"connected": bool(user.github_access_token_encrypted)}

@router.delete("/github")
def github_oauth_disconnect(db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.github_access_token_encrypted = None
    record_audit(db, action="github.oauth_disconnected", owner_id=user.id, resource_type="user", resource_id=user.id)
    db.commit()
    return {"connected":False}
