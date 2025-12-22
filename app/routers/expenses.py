from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from datetime import date, datetime
import os
import time

from app.core.utils import guess_extension
from app.core.zoho import (
    zoho_request, zoho_json,
    zoho_get_expense, zoho_update_expense,
    extract_cf_expense_report,
    zoho_add_expense_attachment,
)

router = APIRouter()


def _month_range_today():
    today = date.today()
    start = today.replace(day=1)
    # compute last day of month
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = next_month.replace(day=1) - datetime.resolution  # safe placeholder, we won’t rely on time
    return start.isoformat(), (next_month - datetime.resolution).date().isoformat()  # not used


def _current_month_start_end():
    today = date.today()
    start = today.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = next_month - (next_month - next_month)  # dummy, replaced below
    # real last day:
    last_day = (next_month - datetime.resolution).date()
    return start.isoformat(), last_day.isoformat()


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _storage_dir(request: Request, expense_id: str) -> str:
    settings = request.app.state.settings
    d = os.path.join(settings.storage_dir, "expenses", expense_id)
    os.makedirs(d, exist_ok=True)
    return d


@router.get("/expenses/list")
def list_expenses(
    request: Request,
    page: int = 1,
    per_page: int = 200,
    filter_by: str = "Status.All",
    search_text: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """
    Default: current month (if date_from/date_to not provided).
    Filter is optional: if user provides date_from/date_to, apply them.
    """
    settings = request.app.state.settings

    if not date_from and not date_to:
        date_from, date_to = _current_month_start_end()

    params = {"page": page, "per_page": per_page, "filter_by": filter_by}
    if search_text:
        params["search_text"] = search_text

    resp = zoho_request(settings, "GET", "/expenses", params=params, timeout=30)
    data = zoho_json(resp)
    if data.get("code") != 0:
        raise HTTPException(400, data)

    expenses = data.get("expenses", []) or []

    # Local date filtering (safe even if Zoho doesn’t support date params here)
    df = _parse_date(date_from) if date_from else None
    dt = _parse_date(date_to) if date_to else None

    if df or dt:
        filtered = []
        for x in expenses:
            xd = _parse_date(x.get("date", "") or "")
            if not xd:
                continue
            if df and xd < df:
                continue
            if dt and xd > dt:
                continue
            filtered.append(x)
        expenses = filtered

    # Normalize vendor name + reference
    for x in expenses:
        x["vendor_name"] = x.get("vendor_name") or x.get("contact_name") or x.get("vendor") or ""
        x["reference"] = x.get("reference_number") or ""

    return {"ok": True, "count": len(expenses), "expenses": expenses, "raw": data}


@router.get("/expenses/by-id/{expense_id}")
def get_expense_by_id(request: Request, expense_id: str):
    settings = request.app.state.settings
    return zoho_get_expense(settings, expense_id)


@router.put("/expenses/update/{expense_id}")
def update_expense(request: Request, expense_id: str, payload: dict):
    """
    Allow editing fields (Notes->Zoho description, Reference->Zoho reference_number, vendor, account, paid_through, amount, date).
    """
    settings = request.app.state.settings

    zoho_payload = {}
    if "date" in payload:
        zoho_payload["date"] = payload["date"]
    if "amount" in payload:
        zoho_payload["amount"] = float(payload["amount"])
    if "account_id" in payload:
        zoho_payload["account_id"] = str(payload["account_id"]).strip()
    if "paid_through_account_id" in payload:
        zoho_payload["paid_through_account_id"] = str(payload["paid_through_account_id"]).strip()
    if "notes" in payload:
        zoho_payload["description"] = payload["notes"]
    if "vendor_id" in payload:
        zoho_payload["vendor_id"] = payload["vendor_id"] or None
    if "reference" in payload:
        zoho_payload["reference_number"] = payload["reference"] or ""

    resp = zoho_update_expense(settings, expense_id, zoho_payload)
    if resp.get("code") != 0:
        raise HTTPException(400, resp)
    return {"ok": True, "zoho": resp}


@router.post("/expenses/{expense_id}/attachments")
def add_expense_attachment(
    request: Request,
    expense_id: str,
    file: UploadFile = File(...),
):
    """
    Non-overwriting attachment:
    - Renames file using cf_expense_report (if available) + timestamp
    - Saves locally for "Open"
    - Uploads to Zoho as an expense attachment (does NOT replace receipt)
    """
    settings = request.app.state.settings

    # get expense_report_no
    exp = zoho_get_expense(settings, expense_id)
    report_no = None
    if exp.get("code") == 0:
        report_no = extract_cf_expense_report(settings, (exp.get("expense") or {}))

    report_no = (report_no or f"EXP{expense_id}").strip()

    ext = guess_extension(file.filename, file.content_type)
    ts = int(time.time())
    new_filename = f"{report_no}_{ts}{ext}"

    # Save locally
    d = _storage_dir(request, expense_id)
    local_path = os.path.join(d, new_filename)
    with open(local_path, "wb") as out:
        out.write(file.file.read())

    # Upload to Zoho as attachment (non-overwriting)
    with open(local_path, "rb") as f:
        z = zoho_add_expense_attachment(settings, expense_id, new_filename, f, file.content_type)

    return {"ok": True, "expense_id": expense_id, "report_no": report_no, "filename": new_filename, "zoho": z}


@router.get("/expenses/{expense_id}/attachments/list")
def list_local_attachments(request: Request, expense_id: str):
    d = _storage_dir(request, expense_id)
    items = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                items.append({"filename": name, "size": os.path.getsize(p)})
    return {"ok": True, "count": len(items), "attachments": items}


@router.get("/expenses/{expense_id}/attachments/open-latest")
def open_latest_local_attachment(request: Request, expense_id: str):
    d = _storage_dir(request, expense_id)
    if not os.path.isdir(d):
        raise HTTPException(404, "No attachments")
    files = [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]
    if not files:
        raise HTTPException(404, "No attachments")
    files.sort()
    latest = files[-1]
    path = os.path.join(d, latest)
    return FileResponse(path, filename=latest)
