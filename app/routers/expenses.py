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


def _current_month_start_end() -> tuple[str, str]:
    today = date.today()
    start = date(today.year, today.month, 1)
    # next month start:
    if today.month == 12:
        next_start = date(today.year + 1, 1, 1)
    else:
        next_start = date(today.year, today.month + 1, 1)
    end = next_start - datetime.resolution  # safe; will format to date anyway
    return start.strftime("%Y-%m-%d"), (next_start - datetime.resolution).date().strftime("%Y-%m-%d")


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
    # Zoho API supports filtering by expense date using date_start/date_end
    if date_from:
        params["date_start"] = date_from
    if date_to:
        params["date_end"] = date_to
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
    data = zoho_get_expense(settings, expense_id)
    if data.get('code') != 0:
        raise HTTPException(400, data)
    return {'ok': True, 'expense': (data.get('expense') or {}), 'raw': data}

@router.post("/expenses/update/{expense_id}")
async def update_expense(request: Request, expense_id: str):
    settings = request.app.state.settings
    payload = await request.json()
    out = zoho_update_expense(settings, expense_id, payload)
    if out.get("code") != 0:
        raise HTTPException(400, out)
    return {"ok": True, "zoho": out}


@router.post("/expenses/attachment/{expense_id}")
async def upload_expense_attachment(
    request: Request,
    expense_id: str,
    file: UploadFile = File(...),
):
    """
    Uploads attachment for expense:
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

    d = _storage_dir(request, expense_id)
    local_path = os.path.join(d, new_filename)

    # Save local copy
    with open(local_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Upload to Zoho
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


@router.delete("/expenses/delete/{expense_id}")
def delete_expense(request: Request, expense_id: str):
    settings = request.app.state.settings
    resp = zoho_request(settings, "DELETE", f"/expenses/{expense_id}")
    out = zoho_json(resp)
    if out.get("code") != 0:
        raise HTTPException(400, out)
    return {"ok": True, "zoho": out}