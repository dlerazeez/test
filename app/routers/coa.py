from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services.coa_store import coa_store

router = APIRouter()


@router.get("/expense_accounts")
def expense_accounts():
    return {"accounts": coa_store.expense_accounts()}


@router.get("/paid_through")
def paid_through():
    return {"accounts": coa_store.paid_through_accounts()}


@router.get("/accrued_paid_through")
def accrued_paid_through():
    acc = coa_store.accrued_paid_through_account()
    if not acc:
        raise HTTPException(status_code=400, detail="Accrued Expenses account not found in COA CSV")
    return {"account": acc}
