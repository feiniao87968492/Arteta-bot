from typing import Any, Dict, Optional
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    ok: bool
    data: Optional[Any] = None
    error: Optional[ErrorBody] = None


def ok(data: Any = None) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def fail(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}
