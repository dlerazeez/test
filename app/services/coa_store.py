import csv
import os
from app.core.config import COA_CSV_PATH

_COA_ROWS: list[dict] = []
_COA_LOAD_ERROR: str | None = None


def load_coa_csv():
    global _COA_ROWS, _COA_LOAD_ERROR
    _COA_ROWS = []
    _COA_LOAD_ERROR = None

    if not os.path.exists(COA_CSV_PATH):
        _COA_LOAD_ERROR = f"COA CSV not found at '{COA_CSV_PATH}'. Put Chart_of_Accounts.csv at root or set COA_CSV_PATH."
        return

    try:
        with open(COA_CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                row = {
                    "account_id": (r.get("Account ID") or "").strip(),
                    "account_name": (r.get("Account Name") or "").strip(),
                    "account_code": str(r.get("Account Code") or "").strip(),
                    "account_type": (r.get("Account Type") or "").strip(),
                    "currency": (r.get("Currency") or "").strip(),
                    "parent_account": (r.get("Parent Account") or "").strip(),
                    "status": (r.get("Account Status") or "").strip(),
                }
                if row["account_id"] and row["account_name"]:
                    _COA_ROWS.append(row)
    except Exception as e:
        _COA_LOAD_ERROR = f"Failed to load COA CSV: {repr(e)}"


def coa_error() -> str | None:
    return _COA_LOAD_ERROR


def coa_filter(types: set[str]) -> list[dict]:
    out = []
    for r in _COA_ROWS:
        if r.get("status") and r["status"].lower() not in ("active", ""):
            continue
        if r.get("account_type") in types:
            out.append(r)

    def sort_key(x):
        code = x.get("account_code", "")
        try:
            code_num = int(float(code)) if code else 10**9
        except Exception:
            code_num = 10**9
        return (code_num, x.get("account_name", ""))

    out.sort(key=sort_key)
    return out


load_coa_csv()
