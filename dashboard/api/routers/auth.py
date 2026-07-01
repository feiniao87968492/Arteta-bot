from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.api.schemas import ok
from dashboard.api.security import create_access_token, require_auth, verify_admin_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(request: LoginRequest):
    return ok({"token": ""})


@router.get("/me")
def me(payload=Depends(require_auth)):
    return ok({"subject": payload["sub"]})
