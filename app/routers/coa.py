from fastapi import APIRouter, HTTPException
from app.services.coa_store import coa_filter, load_coa_csv, coa_error

router = APIRouter(prefix="/coa", tags=["COA"])


@router.get("/expense-accounts")
def coa_expense_accounts():
    err = coa_error()
    if err:
        return {"ok": False, "error": err, "accounts": []}
    accounts = coa_filter({"Expense", "Other Expense"})
    return {"ok": True, "count": len(accounts), "accounts": accounts}


@router.get("/paid-through-accounts")
def coa_paid_through_accounts():
    err = coa_error()
    if err:
        return {"ok": False, "error": err, "accounts": []}
    accounts = coa_filter({"Cash", "Bank"})
    return {"ok": True, "count": len(accounts), "accounts": accounts}


@router.post("/reload")
def coa_reload():
    load_coa_csv()
    err = coa_error()
    if err:
        raise HTTPException(400, err)
    return {"ok": True}
