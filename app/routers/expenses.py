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


# =========================================================
# MODELS
# =========================================================

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


# =========================================================
# HELPERS
# =========================================================

def _today_str() -> str:
    return date.today().isoformat()


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _recompute_accrued_balance(rec: Dict[str, Any]) -> None:
    amt = _safe_float(rec.get("amount"))
    clearing = rec.get("clearing") or []
    cleared_total = sum(_safe_float(c.get("amount")) for c in clearing)
    bal = max(0.0, amt - cleared_total)
    rec["balance"] = round(bal, 2)
    if rec["balance"] <= 0:
        rec["cleared_at"] = rec.get("cleared_at") or int(__import__("time").time())
    else:
        rec["cleared_at"] = None


# =========================================================
# VENDORS
# =========================================================

@router.get("/vendors")
async def list_vendors():
    if not settings.use_zoho:
        return {"contacts": []}

    resp = await zoho.request(
        "GET",
        "/contacts",
        params={"contact_type": "vendor"},
    )
    resp = ensure_ok_zoho(resp)
    return resp


# =========================================================
# CREATE EXPENSE
# =========================================================

@router.post("/create")
async def create_expense(
    payload: ExpenseCreate,
    user: CurrentUser = Depends(get_current_user),
):
    exp_type = (payload.expense_type or "ordinary").strip().lower()
    if exp_type not in ("ordinary", "accrued"):
        exp_type = "ordinary"

    paid_through_id = payload.paid_through_account_id
    paid_through_name = ""

    # Enforce accrued paid-through
    if exp_type == "accrued":
        acc = coa_store.accrued_paid_through_account()
        if not acc:
            raise HTTPException(
                status_code=400,
                detail="Accrued Expenses account not found in COA",
            )

        paid_through_id = (
            acc.get("Account ID")
            or acc.get("Account Id")
            or acc.get("account_id")
            or ""
        ).strip()

        paid_through_name = (
            acc.get("Account Name")
            or acc.get("account_name")
            or "Accrued Expenses"
        )

    # 🔐 ENFORCE CASH ACCESS (ORDINARY ONLY)
    if not user.is_admin and exp_type != "accrued":
        allowed = user.allowed_cash_accounts or []
        if paid_through_id not in allowed:
            raise HTTPException(
                status_code=403,
                detail="You are not allowed to use this paid-through account",
            )

    if not payload.expense_account_id:
        raise HTTPException(status_code=400, detail="Expense account is required")
    if not paid_through_id:
        raise HTTPException(status_code=400, detail="Paid through is required")
    if not payload.amount or payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    if not payload.vendor_id and not payload.vendor_name:
        raise HTTPException(
            status_code=400,
            detail="Select a vendor or enter vendor name",
        )

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


# =========================================================
# APPROVED EXPENSES
# =========================================================

@router.get("/approved")
def list_approved(
    start_date: str | None = None,
    end_date: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    items = pending_store.list_approved(
        start_date=start_date,
        end_date=end_date,
        default_current_month=True,
    )

    # 🔐 Restrict non-admin users
    if not user.is_admin:
        allowed = set(user.allowed_cash_accounts or [])
        items = [
            e for e in items
            if (
                e.get("created_by") == user.user_id
                or e.get("paid_through_account_id") in allowed
            )
        ]

    return {"approved": items}


# =========================================================
# GET SINGLE EXPENSE
# =========================================================

@router.get("/{expense_id}")
def get_expense(
    expense_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    exp = pending_store.get(expense_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")

    # 🔐 Restrict non-admin users
    if not user.is_admin:
        if exp.get("paid_through_account_id") not in (
            user.allowed_cash_accounts or []
        ):
            raise HTTPException(status_code=403, detail="Not allowed")

    return {"expense": exp}


# =========================================================
# UPDATE EXPENSE (FIXED)
# =========================================================

@router.patch("/{expense_id}")
def update_expense(
    expense_id: str,
    patch: Dict[str, Any],
    user: CurrentUser = Depends(get_current_user),
):
    exp = pending_store.get(expense_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")

    # permissions:
    # - admin can edit anything
    # - user can only edit their own pending items
    if not user.is_admin:
        if exp.get("status") != "pending":
            raise HTTPException(status_code=403, detail="Only pending expenses can be edited")
        if exp.get("created_by") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your expense")

    updates = dict(patch or {})

    # Sync edits into raw payload so approve won't post stale values
    payload = (exp.get("payload") if isinstance(exp.get("payload"), dict) else {}) or {}

    if "amount" in updates:
        payload["amount"] = updates["amount"]
    if "reference_number" in updates:
        payload["reference_number"] = updates["reference_number"]
    if "paid_through_account_id" in updates:
        payload["paid_through_account_id"] = updates["paid_through_account_id"]
    if "expense_account_id" in updates:
        payload["expense_account_id"] = updates["expense_account_id"]
    if "date" in updates:
        payload["date"] = updates["date"]
    if "description" in updates:
        payload["description"] = updates["description"]
    if "vendor_id" in updates:
        payload["vendor_id"] = updates["vendor_id"]
    if "vendor_name" in updates:
        payload["vendor_name"] = updates["vendor_name"]

    updates["payload"] = payload

    # If accrued expense amount changed, recompute balance
    exp_type = (exp.get("expense_type") or "").lower()
    if exp_type == "accrued" and "amount" in updates:
        tmp = dict(exp)
        tmp.update(updates)
        _recompute_accrued_balance(tmp)
        updates["balance"] = tmp.get("balance")
        updates["cleared_at"] = tmp.get("cleared_at")

    updated = (
        pending_store.update_fields(expense_id, updates)
        if user.is_admin
        else pending_store.update(expense_id, updates)
    )
    if not updated:
        raise HTTPException(status_code=400, detail="Update failed")

    return {"ok": True, "expense": updated}


# =========================================================
# DELETE EXPENSE
# =========================================================

@router.delete("/{expense_id}")
def delete_expense(
    expense_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    exp = pending_store.get(expense_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")

    if not user.is_admin:
        if exp.get("status") != "pending":
            raise HTTPException(status_code=403, detail="Only pending expenses can be deleted")
        if exp.get("created_by") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your expense")

    pending_store.delete(expense_id)
    return {"ok": True}
