from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
import os
import time
import shutil

from app.core.utils import guess_extension

router = APIRouter()


@router.post("/pending-expenses/create")
async def create_pending_expense(request: Request):
    """
    Creates a pending expense row in local store.
    Body JSON (example):
    {
      "date": "YYYY-MM-DD",
      "amount": 1000,
      "currency": "IQD",
      "vendor_name": "Vendor",
      "reference_number": "",
      "description": "",
      "expense_account_id": "",
      "expense_account_name": "",
      "paid_through_account_id": "",
      "paid_through_account_name": ""
    }
    """
    body = await request.json()
    required = ["date", "amount", "currency"]
    missing = [k for k in required if k not in body or body[k] in [None, ""]]
    if missing:
        raise HTTPException(400, {"error": "Missing fields", "missing": missing})

    store = request.app.state.pending_store
    pending_id = store.create_pending(body)
    row = store.get_pending(pending_id)
    row["vendor_name"] = row.get("vendor_name") or ""
    return {"ok": True, "pending": row}


@router.get("/pending-expenses/list")
def list_pending_expenses(request: Request, date_from: str | None = None, date_to: str | None = None):
    store = request.app.state.pending_store
    rows = store.list_pending(date_from=date_from, date_to=date_to)
    # Ensure vendor_name is always present
    for r in rows:
        r["vendor_name"] = r.get("vendor_name") or ""
    return {"ok": True, "count": len(rows), "pending": rows}


@router.get("/pending-expenses/{pending_id}")
def get_pending_expense(request: Request, pending_id: str):
    store = request.app.state.pending_store
    row = store.get_pending(pending_id)
    if not row:
        raise HTTPException(404, {"error": "Not found"})
    row["vendor_name"] = row.get("vendor_name") or ""
    return {"ok": True, "pending": row}


@router.put("/pending-expenses/{pending_id}")
async def update_pending_expense(request: Request, pending_id: str):
    store = request.app.state.pending_store
    row = store.get_pending(pending_id)
    if not row:
        raise HTTPException(404, {"error": "Not found"})

    body = await request.json()
    store.update_pending(pending_id, body)
    row2 = store.get_pending(pending_id)
    row2["vendor_name"] = row2.get("vendor_name") or ""
    return {"ok": True, "pending": row2}


@router.post("/pending-expenses/{pending_id}/attachments")
async def upload_pending_attachment(request: Request, pending_id: str, file: UploadFile = File(...)):
    store = request.app.state.pending_store
    row = store.get_pending(pending_id)
    if not row:
        raise HTTPException(404, {"error": "Not found"})

    temp_dir = os.path.join(os.getcwd(), "tmp_uploads")
    os.makedirs(temp_dir, exist_ok=True)

    orig_name = file.filename or f"upload_{int(time.time())}"
    temp_path = os.path.join(temp_dir, orig_name)

    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    ext = guess_extension(orig_name)
    att = store.add_attachment(pending_id, temp_path, orig_name, ext)

    try:
        os.remove(temp_path)
    except Exception:
        pass

    return {"ok": True, "attachment": att}


@router.get("/pending-expenses/{pending_id}/attachments/list")
def list_pending_attachments(request: Request, pending_id: str):
    store = request.app.state.pending_store
    row = store.get_pending(pending_id)
    if not row:
        raise HTTPException(404, {"error": "Not found"})
    return {"ok": True, "attachments": store.list_attachments(pending_id)}


@router.get("/pending-expenses/attachments/open/{attachment_id}")
def open_pending_attachment(request: Request, attachment_id: str):
    store = request.app.state.pending_store
    path, filename = store.get_attachment_path(attachment_id)
    if not path or not os.path.exists(path):
        raise HTTPException(404, {"error": "Attachment not found"})
    return FileResponse(path, filename=filename)


@router.post("/pending-expenses/{pending_id}/approve")
async def approve_pending_expense(request: Request, pending_id: str):
    """
    Approve means: create in Zoho (Expense endpoint) + attach local files + mark approved/closed locally.
    The frontend calls backend Zoho expense creation separately; this endpoint can remain as a placeholder.
    """
    store = request.app.state.pending_store
    row = store.get_pending(pending_id)
    if not row:
        raise HTTPException(404, {"error": "Not found"})

    # You can implement full approve logic later if desired.
    store.mark_approved(pending_id)
    return {"ok": True}
