"""Core: env, db, security helpers (password, JWT, sessions), merchant signature."""
import os
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt
import bcrypt
import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

JWT_ALGORITHM = "HS256"
EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "access"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookie(response, token: str):
    response.set_cookie(key="access_token", value=token, httponly=True,
                        secure=True, samesite="none", max_age=604800, path="/")


def set_session_cookie(response, token: str):
    response.set_cookie(key="session_token", value=token, httponly=True,
                        secure=True, samesite="none", max_age=604800, path="/")


def clear_auth_cookies(response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("session_token", path="/")


# ---------- current user (supports JWT + Google session) ----------
async def get_current_user(request: Request) -> dict:
    # 1) JWT access token (email/password)
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token:
        try:
            payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
            if payload.get("type") == "access":
                user = await db.users.find_one({"user_id": payload["sub"]}, {"_id": 0})
                if user:
                    user.pop("password_hash", None)
                    return user
        except jwt.PyJWTError:
            pass

    # 2) Emergent Google session token
    stoken = request.cookies.get("session_token")
    if not stoken:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            stoken = auth[7:]
    if stoken:
        sess = await db.user_sessions.find_one({"session_token": stoken}, {"_id": 0})
        if sess:
            exp = sess["expires_at"]
            if isinstance(exp, str):
                exp = datetime.fromisoformat(exp)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > datetime.now(timezone.utc):
                user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
                if user:
                    user.pop("password_hash", None)
                    return user
    raise HTTPException(status_code=401, detail="Not authenticated")


async def exchange_emergent_session(session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": session_id})
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session")
        return r.json()


# ---------- merchant API signature (X-Auth-Sign, sha256) ----------
def _js_scalar(o) -> str:
    """Serialize a scalar exactly like the BoxExchanger engine's JS `extractValues`
    (Array.prototype.join / String()) so signatures match the merchant side:
      - bool  -> "true"/"false"   (NOT "1"/"0")
      - None  -> ""               (join renders null/undefined as empty)
      - float -> JS Number.toString(): integral floats drop ".0" (3.0 -> "3")
      - int/str -> str(o)
    """
    if isinstance(o, bool):
        return "true" if o else "false"
    if o is None:
        return ""
    if isinstance(o, float):
        if o == int(o) and abs(o) < 1e16:
            return str(int(o))
        return repr(o)
    return str(o)


def _concat_values(obj) -> str:
    """Sort keys alphabetically (recursive), concatenate all scalar values in order.
    Value formatting mirrors the JS receiver so X-Auth-Sign verifies on both sides."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k in sorted(o.keys()):
                walk(o[k])
        elif isinstance(o, (list, tuple)):
            for item in o:
                walk(item)
        else:
            out.append(_js_scalar(o))

    walk(obj)
    return "".join(out)


def make_signature(body: dict, secret: str) -> str:
    return hashlib.sha256((_concat_values(body) + secret).encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_hex(32)


def new_secret() -> str:
    return secrets.token_hex(32)
