from datetime import datetime, timedelta, timezone
import os
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from investbrief.web.config import get_web_config, get_recipient_by_email

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def _get_jwt_secret() -> str:
    secret = get_web_config().get("secret_key") or os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT secret_key is required. Set web.secret_key in config.json or JWT_SECRET env var.")
    return secret


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(user_id: int, email: str) -> str:
    secret = _get_jwt_secret()
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": email, "uid": user_id, "exp": expire}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(credentials.credentials, secret, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user = get_recipient_by_email(email)
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
