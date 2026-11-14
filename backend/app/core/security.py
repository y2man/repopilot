import base64, hashlib, hmac, json, secrets, time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"
def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
        return hmac.compare_digest(candidate, digest)
    except ValueError: return False

def _b64(data: bytes) -> str: return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
def create_token(user_id: int) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub":str(user_id),"iat":now,"exp":now+86400}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}"
    secret = get_settings().secret_key.encode()
    signature = _b64(hmac.new(secret, signing.encode(), hashlib.sha256).digest())
    return f"{signing}.{signature}"
def decode_token(token: str) -> int:
    try:
        head, payload, signature = token.split(".")
        signing = f"{head}.{payload}"
        expected = _b64(hmac.new(get_settings().secret_key.encode(), signing.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(data["exp"]) < int(time.time()): raise ValueError()
        return int(data["sub"])
    except Exception as exc: raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials: raise HTTPException(status_code=401, detail="Authentication required")
    user = db.get(User, decode_token(credentials.credentials))
    if not user: raise HTTPException(status_code=401, detail="Account no longer exists")
    return user

import base64
from cryptography.fernet import Fernet

def _credential_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secret_key.encode()).digest())
    return Fernet(key)

def encrypt_credential(value: str) -> str:
    return _credential_cipher().encrypt(value.encode()).decode()

def decrypt_credential(value: str) -> str:
    return _credential_cipher().decrypt(value.encode()).decode()
