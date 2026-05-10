from pydantic import BaseModel, Field
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


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    market: str = Field(..., pattern=r"^(us|cn)$")


class SectionAnalysisRequest(BaseModel):
    section: str = Field(..., min_length=1, max_length=100)
    market: str = Field(..., pattern=r"^(us|cn)$")
    data: dict


class RefreshResponse(BaseModel):
    status: str
    updated_at: str


class StatusResponse(BaseModel):
    us: Optional[dict] = None
    cn: Optional[dict] = None


class HoldingItem(BaseModel):
    symbol: str
    name: str


class AddHoldingRequest(BaseModel):
    market: str = Field(..., pattern=r"^(us|cn)$")
    symbol: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)


class MarketPreferences(BaseModel):
    holdings: list[HoldingItem] = []
    industries: list[str] = []


class DeliveryEntry(BaseModel):
    email: str
    language: str = "zh-CN"
    schedule: dict[str, list[str]] = {}


class PreferencesUpdate(BaseModel):
    markets: dict[str, MarketPreferences] = {}
    delivery: list[DeliveryEntry] = []


class PreferencesResponse(BaseModel):
    markets: dict = {}
    delivery: list = []
    language: str = "zh-CN"


class EmailSendRequest(BaseModel):
    market: Optional[str] = None


class EmailSendResponse(BaseModel):
    status: str
    message: str = ""
