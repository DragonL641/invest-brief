from fastapi import APIRouter, Depends, HTTPException, status
from investbrief.web.auth import verify_password, create_access_token, get_current_user
from investbrief.web.models.schemas import LoginRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    from investbrief.web.config import get_recipient_by_email
    user = get_recipient_by_email(req.email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    stored_pw = user.get("password", "")
    if not stored_pw or not verify_password(req.password, stored_pw):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not user.get("active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token)


@router.post("/logout")
def logout():
    return {"message": "ok"}


@router.get("/me", response_model=UserInfo)
def me(user: dict = Depends(get_current_user)):
    return UserInfo(
        id=user["id"],
        email=user["email"],
        name=user.get("name", ""),
        language=user.get("language", "zh-CN"),
        markets=user.get("markets", {}),
    )
