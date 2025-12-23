from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user, require_admin, CurrentUser
from ..core.config import settings
from ..core.zoho import zoho
from ..core.utils import ensure_ok_zoho
from ..services.coa_store import coa_store
from ..services.pending_store import pending_store

router = APIRouter()


class ExpenseCreate(BaseModel):
    expense_type: str = "ordinary"  # ordinary | accrued

    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None

    date: Optional[str] = None  # YYYY-MM-DD
    reference_number: Optional[str] = None

    expense_account_id: str
    amount: float
    paid_through_account_id: str

    description: Optional[str] = ""
    tax_id: Optional[str] = None


def _today_str() -> str:
    return date.today().isoformat()


@router.get("/vendors")
async def list_vendors():
    # This endpoint calls Zoho vendor list, but also supports UI dropdown.
    if not settings.use_zoho:
        return {"contacts": []}
    resp = await zoho.request("GET", "/contacts", params={"contact_type": "vendor"})
    resp = ensure_ok_zoho(resp)
    return resp


@router.post("/create")
async def create_expense(payload: ExpenseCreate, user: CurrentUser = Depends(get_current_user)):
    """
    Creates an expense locally as PENDING (scaffolding).
    Later we will push to Zoho after approval.
    """
    exp_type = (payload.expense_type or "ordinary").strip().lower()
    if exp_type not in ("ordinary", "accrued"):
        exp_type = "ordinary"

    # enforce accrued paid-through
    paid_through_id = payload.paid_through_account_id
    paid_through_name = ""

    if exp_type == "accrued":
        acc = coa_store.accrued_paid_through_account()
        if not acc:
            raise HTTPException(status_code=400, detail="Accrued Expenses account not found in COA")
        paid_through_id = (acc.get("Account ID") or acc.get("Account Id") or acc.get("account_id") or "").strip()
        paid_through_name = (acc.get("Account Name") or acc.get("account_name") or "Accrued Expenses")

    if not payload.expense_account_id:
        raise HTTPException(status_code=400, detail="Expense account is required")
    if not paid_through_id:
        raise HTTPException(status_code=400, detail="Paid through is required")
    if not payload.amount or payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    if not payload.vendor_id and not payload.vendor_name:
        raise HTTPException(status_code=400, detail="Select a vendor or enter vendor name")

    record: Dict[str, Any] = {
        "status": "pending",
        "expense_type": exp_type,
        "date": payload.date or _today_str(),
        "vendor_id": payload.vendor_id,
        "vendor_name": payload.vendor_name or "",
        "reference_number": payload.reference_number or "",
        "expense_account_id": payload.expense_account_id,
        "paid_through_account_id": paid_through_id,
        "paid_through_account_name": paid_through_name,
        "amount": float(payload.amount),
        "description": payload.description or "",
        "tax_id": payload.tax_id,
        "created_by": user.user_id,
        "payload": payload.dict(),
    }

    created = pending_store.add_pending(record)
    return {"ok": True, "expense": created}


@router.get("/approved")
def list_approved(
    start_date: str | None = None,
    end_date: str | None = None,
):
    # default behavior: current month unless date filters provided
    return {
        "approved": pending_store.list_approved(
            start_date=start_date,
            end_date=end_date,
            default_current_month=True,
        )
    }


@router.get("/{expense_id}")
def get_expense(expense_id: str):
    exp = pending_store.get(expense_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"expense": exp}


@router.patch("/{expense_id}")
def update_expense(expense_id: str, patch: Dict[str, Any], _: CurrentUser = Depends(require_admin)):
    updated = pending_store.update(expense_id, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"ok": True, "expense": updated}


@router.delete("/{expense_id}")
def delete_expense(expense_id: str, _: CurrentUser = Depends(require_admin)):
    ok = pending_store.delete(expense_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"ok": True}
