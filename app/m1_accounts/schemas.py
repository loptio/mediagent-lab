import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

# 只檢查基本格式：一個 @、前後都有內容、網域有點；不另外安裝 Email 驗證套件
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut


class UserDetail(BaseModel):
    """管理員看到的幹部帳號；不含任何密碼資訊。"""

    id: int
    email: str
    name: str
    role: str
    status: str
    locked_until: datetime | None
    is_locked: bool


class UserList(BaseModel):
    items: list[UserDetail]


class UserCreate(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [
                {"email": "bob@club.tw", "name": "Bob", "role": "writer", "initial_password": "abcd1234"}
            ]
        }
    }

    email: str
    name: str
    role: Literal["admin", "publisher", "writer"]
    initial_password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """BR-40：移除前後空白並轉為小寫後再檢查格式。"""
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("Email 格式錯誤")
        return value

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名稱不可空白")
        return value.strip()


class UserStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]
