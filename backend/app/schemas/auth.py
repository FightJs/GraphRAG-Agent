from pydantic import BaseModel, field_validator, ConfigDict
import re

class RegisterRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    username: str
    email: str   # 使用 str 避免 email-validator 的域名可送达性检查
    password: str

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        import re as _re
        if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("邮箱格式不正确")
        return v.lower()

    @field_validator("username")
    @classmethod
    def username_ok(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]{3,32}$", v):
            raise ValueError("用户名3-32位，仅限字母数字下划线")
        return v

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码最少8位")
        if not re.search(r"[A-Z]", v):
            raise ValueError("密码须含大写字母")
        if not re.search(r"[a-z]", v):
            raise ValueError("密码须含小写字母")
        if not re.search(r"\d", v):
            raise ValueError("密码须含数字")
        return v

class LoginRequest(BaseModel):
    email: str   # 宽松验证，不检查域名可送达性
    password: str

class TokenData(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 86400
    user: dict
