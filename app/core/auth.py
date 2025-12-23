from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..services.auth_store import auth_store

security = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: str
    email: str
    role: str  # "admin" | "user"


def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> CurrentUser:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = creds.credentials
    u = auth_store.get_user_by_session(token)
    if not u:
        raise HTTPException(status_code=401, detail="Invalid session")

    return CurrentUser(user_id=u["user_id"], email=u["email"], role=u["role"])


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user
