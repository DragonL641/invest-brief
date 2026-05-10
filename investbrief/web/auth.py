from datetime import datetime, timedelta, timezone
import os

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from investbrief.web.config import get_web_config, get_recipient_by_email

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer()


def _get_jwt_secret() -> str:
    secret = get_web_config().get("secret_key") or os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT secret_key is required. Set web.secret_key in config.json or JWT_SECRET env var.")
    return secret


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode("utf-8")
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(user_id: int, email: str) -> str:
    secret = _get_jwt_secret()
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": email, "uid": user_id, "exp": expire}
    return pyjwt.encode(payload, secret, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    secret = _get_jwt_secret()
    try:
        payload = pyjwt.decode(credentials.credentials, secret, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user = get_recipient_by_email(email)
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
