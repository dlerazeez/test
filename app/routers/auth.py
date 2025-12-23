from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user, require_admin, CurrentUser
from ..services.auth_store import auth_store

router = APIRouter()


class LoginPayload(BaseModel):
    email: str
    password: str


class InvitePayload(BaseModel):
    email: str
    role: str = Field(default="user")


class AcceptInvitePayload(BaseModel):
    invite_token: str
    password: str


@router.post("/login")
def login(payload: LoginPayload):
    token = auth_store.login(payload.email, payload.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"token": token}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"user_id": user.user_id, "email": user.email, "role": user.role}


@router.post("/invite")
def invite(payload: InvitePayload, user: CurrentUser = Depends(require_admin)):
    try:
        token = auth_store.invite_user(payload.email, payload.role)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"invite_token": token, "email": payload.email, "role": payload.role}


@router.post("/accept")
def accept(payload: AcceptInvitePayload):
    u = auth_store.accept_invite(payload.invite_token, payload.password)
    if not u:
        raise HTTPException(status_code=400, detail="Invalid invite token or password too short (min 8)")
    return {"ok": True, "email": u["email"], "role": u["role"]}


@router.get("/users")
def list_users(user: CurrentUser = Depends(require_admin)):
    return {"users": auth_store.list_users()}


@router.patch("/users/{user_id}/role")
def set_role(user_id: str, payload: InvitePayload, user: CurrentUser = Depends(require_admin)):
    ok = auth_store.update_role(user_id, payload.role)
    if not ok:
        raise HTTPException(status_code=400, detail="Unable to update role")
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, user: CurrentUser = Depends(require_admin)):
    ok = auth_store.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}
