from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    email: str
    name: str
    language: str
    markets: dict


class WatchlistItem(BaseModel):
    symbol: str
    name: str
    market: str


class WatchlistResponse(BaseModel):
    id: str
    symbol: str
    name: str
    market: str


class ChatRequest(BaseModel):
    message: str
    market: str


class SectionAnalysisRequest(BaseModel):
    section: str
    market: str
    data: dict


class RefreshResponse(BaseModel):
    status: str
    updated_at: str


class StatusResponse(BaseModel):
    us: Optional[dict] = None
    cn: Optional[dict] = None
