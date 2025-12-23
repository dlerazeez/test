from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import require_admin, CurrentUser
from ..services.coa_store import coa_store
from ..services.pending_store import pending_store

router = APIRouter()


class ClearingPayload(BaseModel):
    paid_through_account_id: str
    paid_through_account_name: str
    amount: float
    date: str | None = None  # YYYY-MM-DD


@router.get("/expenses")
def list_accrued(include_cleared: bool = False):
    return {"accrued": pending_store.list_accrued(include_cleared=include_cleared)}


@router.post("/{expense_id}/clear")
def clear_accrued(expense_id: str, payload: ClearingPayload, _: CurrentUser = Depends(require_admin)):
    updated = pending_store.add_clearing(
        expense_id,
        amount=payload.amount,
        paid_through_account_id=payload.paid_through_account_id,
        paid_through_account_name=payload.paid_through_account_name,
        clearing_date=payload.date,
    )
    if not updated:
        raise HTTPException(status_code=400, detail="Unable to clear accrued expense (check id/type/status/amount)")
    return {"ok": True, "expense": updated}
