from __future__ import annotations

from datetime import date
import inspect
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user, require_admin, CurrentUser
from ..services.coa_store import coa_store
from ..services.pending_store import pending_store

router = APIRouter()


class ClearingPayload(BaseModel):
    paid_through_account_id: str
    amount: float
    date: str | None = None  # YYYY-MM-DD
    reference_number: str | None = None
    description: str | None = None


def _load_accrued_expense(expense_id: str) -> dict | None:
    """
    Best-effort loader. Prefer a direct getter if your PendingStore exposes one;
    otherwise fallback to scanning list_accrued(include_cleared=True).
    """
    for getter_name in ("get_accrued", "get_accrued_expense", "find_accrued"):
        getter = getattr(pending_store, getter_name, None)
        if callable(getter):
            try:
                return getter(expense_id)
            except TypeError:
                # In case a getter expects different args, ignore and fallback.
                pass

    # Fallback: scan list
    try:
        items = pending_store.list_accrued(include_cleared=True)
    except TypeError:
        items = pending_store.list_accrued(True)

    for e in items or []:
        if str(e.get("id") or e.get("expense_id") or "") == str(expense_id):
            return e
    return None


def _compute_balance(expense: dict) -> float | None:
    """
    Extract remaining balance from common keys; fallback to computing from amount - cleared.
    If balance cannot be determined reliably, return None.
    """
    for key in ("balance", "remaining_balance", "remaining", "open_balance"):
        if key in expense and expense[key] is not None:
            try:
                return float(expense[key])
            except (TypeError, ValueError):
                return None

    amount = expense.get("amount")
    if amount is None:
        return None
    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        return None

    # Common patterns for cleared totals
    for cleared_key in ("cleared_total", "cleared_amount", "paid_total", "paid_amount"):
        if cleared_key in expense and expense[cleared_key] is not None:
            try:
                return amount_f - float(expense[cleared_key])
            except (TypeError, ValueError):
                return None

    # If there is a list of clearings/payments
    for list_key in ("clearings", "payments", "clearing_payments"):
        if isinstance(expense.get(list_key), list):
            try:
                cleared_sum = sum(float(x.get("amount", 0) or 0) for x in expense[list_key])
                return amount_f - cleared_sum
            except (TypeError, ValueError):
                return None

    return None


@router.get("/expenses")
def list_accrued(
    include_cleared: bool = False,
    user: CurrentUser = Depends(get_current_user),
):
    items = pending_store.list_accrued(include_cleared=include_cleared)

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

    return {"accrued": items}


@router.post("/{expense_id}/clear")
def clear_accrued(
    expense_id: str,
    payload: ClearingPayload,
    user: CurrentUser = Depends(require_admin),
):
    src = pending_store.get(expense_id)
    if not src:
        raise HTTPException(status_code=404, detail="Accrued expense not found")

    if src.get("status") != "approved" or (src.get("expense_type") or "").lower() != "accrued":
        raise HTTPException(status_code=400, detail="Source must be an approved accrued expense")

    amt = float(payload.amount or 0)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    paid_id = str(payload.paid_through_account_id or "").strip()
    if not paid_id:
        raise HTTPException(status_code=400, detail="Paid through is required")

    # derive account name from COA
    paid_name = ""
    for r in coa_store.paid_through_accounts():
        rid = (r.get("Account ID") or r.get("Account Id") or r.get("account_id") or "").strip()
        if rid == paid_id:
            paid_name = (r.get("Account Name") or r.get("account_name") or "").strip()
            break

    created = pending_store.add_pending({
        "pending_kind": "accrued_payment",
        "expense_type": "accrued_payment",
        "date": payload.date or date.today().isoformat(),
        "vendor_id": src.get("vendor_id"),
        "vendor_name": src.get("vendor_name"),
        "amount": amt,
        "reference_number": payload.reference_number or "",
        "paid_through_account_id": paid_id,
        "paid_through_account_name": paid_name,
        "description": payload.description or f"Clearing payment for accrued expense {expense_id}",
        "created_by": user.user_id,
        "source_accrued_expense_id": expense_id,
        "payload": {
            "date": payload.date or date.today().isoformat(),
            "vendor_id": src.get("vendor_id"),
            "vendor_name": src.get("vendor_name"),
            "amount": amt,
            "reference_number": payload.reference_number or "",
            "paid_through_account_id": paid_id,
            "description": payload.description or f"Clearing payment for accrued expense {expense_id}",
        },
    })

    return {"ok": True, "payment": created}


@router.get("/payments")
def list_payments_made(user: CurrentUser = Depends(get_current_user)):
    items = pending_store.list_payments_made(status="approved")

    if not user.is_admin:
        allowed = set(user.allowed_cash_accounts or [])
        items = [
            p for p in items
            if (
                p.get("created_by") == user.user_id
                or p.get("paid_through_account_id") in allowed
            )
        ]
    return {"payments": items}


class ClearingEditPayload(BaseModel):
    amount: float | None = None
    paid_through_account_id: str | None = None
    paid_through_account_name: str | None = None
    date: str | None = None
    reference_number: str | None = None


@router.get("/{expense_id}/clearing/{clearing_id}")
def get_clearing(
    expense_id: str,
    clearing_id: str,
    _: CurrentUser = Depends(require_admin),
):
    c = pending_store.get_clearing(expense_id, clearing_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clearing entry not found")
    return {"ok": True, "clearing": c}


@router.patch("/{expense_id}/clearing/{clearing_id}")
def update_clearing(
    expense_id: str,
    clearing_id: str,
    payload: ClearingEditPayload,
    _: CurrentUser = Depends(require_admin),
):
    updates = payload.model_dump(exclude_none=True)
    c = pending_store.update_clearing(expense_id, clearing_id, updates)
    if not c:
        raise HTTPException(status_code=404, detail="Clearing entry not found")
    return {"ok": True, "clearing": c}


@router.delete("/{expense_id}/clearing/{clearing_id}")
def delete_clearing(
    expense_id: str,
    clearing_id: str,
    _: CurrentUser = Depends(require_admin),
):
    ok = pending_store.delete_clearing(expense_id, clearing_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Clearing entry not found")
    return {"ok": True}
