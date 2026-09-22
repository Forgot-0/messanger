from typing import Annotated

from fastapi import Form
from pydantic import BaseModel, EmailStr, Field

from app.auth.schemas.base import PasswordMixinSchema


class OAuth2PasswordRequestFormWithDevice:
    def __init__(
        self,
        *,
        grant_type: Annotated[
            str | None,
            Form(pattern="^password$"),
        ] = None,
        username: Annotated[
            str,
            Form(),
        ],
        password: Annotated[
            str,
            Form(json_schema_extra={"format": "password"}),
        ],
        scope: Annotated[
            str,
            Form(),
        ] = "",
        device_id: Annotated[
            str | None,
            Form(),
        ] = None,
        client_id: Annotated[
            str | None,
            Form(),
        ] = None,
        client_secret: Annotated[
            str | None,
            Form(json_schema_extra={"format": "password"}),
        ] = None,
    ) -> None:
        self.grant_type = grant_type
        self.username = username
        self.password = password
        self.scopes = scope.split()
        self.client_id = client_id
        self.client_secret = client_secret
        self.device_id = device_id



class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token for user")


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token for logout")


class SendVerifyCodeRequest(BaseModel):
    email: EmailStr = Field(..., description="Email for verification")


class SendResetPasswordCodeRequest(BaseModel):
    email: EmailStr = Field(..., description="Email for reset password")


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., description="Токен verification email")


class ResetPasswordRequest(PasswordMixinSchema):
    token: str = Field(..., description="Token for reset password")


class CallbackRequest(BaseModel):
    code: str
    state: str


class OAuthCallbackQuery(BaseModel):
    code: str | None = None
    state: str
