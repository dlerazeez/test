from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
import os

from app.core.utils import guess_extension
from app.core.zoho import (
    zoho_create_expense,
    zoho_add_expense_receipt,
    zoho_add_expense_attachment,
)

router = APIRouter()


def _normalize_pending_payload(body: dict) -> dict:
    """Accepts both frontend keys and DB keys and returns DB-ready payload."""
    # Frontend (older) keys:
    # - expense_account_id -> account_id
    # - paid_through_account_id stays
    # - description -> notes
    # - reference_number -> reference
    payload = dict(body or {})

    if "account_id" not in payload and "expense_account_id" in payload:
        payload["account_id"] = payload.get("expense_account_id") or ""
    if "notes" not in payload and "description" in payload:
        payload["notes"] = payload.get("description") or ""
    if "reference" not in payload and "reference_number" in payload:
        payload["reference"] = payload.get("reference_number") or ""

    # Ensure required DB keys exist
    payload.setdefault("account_id", "")
    payload.setdefault("paid_through_account_id", "")
    payload.setdefault("vendor_id", payload.get("vendor_id") or "")
    payload.setdefault("vendor_name", payload.get("vendor_name") or "")
    payload.setdefault("notes", payload.get("notes") or "")
    payload.setdefault("reference", payload.get("reference") or "")

    return payload


@router.post("/pending-expenses/create")
async def create_pending_expense(request: Request):
    """Creates a pending expense row in local store."""
    body = await request.json()
    required = ["date", "amount"]
    missing = [k for k in required if k not in body or body[k] in [None, ""]]
    if missing:
        raise HTTPException(400, {"error": "Missing fields", "missing": missing})

    payload = _normalize_pending_payload(body)

    store = request.app.state.pending_store
    pending_id = store.create_pending(payload)
    row = store.get_pending(pending_id)
    row["vendor_name"] = row.get("vendor_name") or ""
    row["currency"] = body.get("currency") or "IQD"
    row["reference_number"] = row.get("reference") or ""
    return {"ok": True, "pending": row}


@router.get("/pending-expenses/list")
def list_pending_expenses(request: Request, date_from: str | None = None, date_to: str | None = None):
    store = request.app.state.pending_store
    rows = store.list_pending(date_from=date_from, date_to=date_to)
    for r in rows:
        r["vendor_name"] = r.get("vendor_name") or ""
        r["currency"] = r.get("currency") or "IQD"
        r["reference_number"] = r.get("reference") or ""
    return {"ok": True, "count": len(rows), "pending": rows}


@router.get("/pending-expenses/{pending_id}")
def get_pending_expense(request: Request, pending_id: int):
    store = request.app.state.pending_store
    try:
        row = store.get_pending(int(pending_id))
    except KeyError:
        raise HTTPException(404, {"error": "Not found"})
    row["vendor_name"] = row.get("vendor_name") or ""
    row["currency"] = row.get("currency") or "IQD"
    row["reference_number"] = row.get("reference") or ""
    return {"ok": True, "pending": row}


@router.put("/pending-expenses/{pending_id}")
async def update_pending_expense(request: Request, pending_id: int):
    store = request.app.state.pending_store
    try:
        _ = store.get_pending(int(pending_id))
    except KeyError:
        raise HTTPException(404, {"error": "Not found"})

    body = await request.json()
    payload = _normalize_pending_payload(body)
    store.update_pending(int(pending_id), payload)

    row2 = store.get_pending(int(pending_id))
    row2["vendor_name"] = row2.get("vendor_name") or ""
    row2["currency"] = body.get("currency") or row2.get("currency") or "IQD"
    row2["reference_number"] = row2.get("reference") or ""
    return {"ok": True, "pending": row2}


@router.delete("/pending-expenses/{pending_id}")
def delete_pending_expense(request: Request, pending_id: int):
    store = request.app.state.pending_store
    # remove local files first
    try:
        atts = store.list_attachments(int(pending_id))
    except Exception:
        atts = []
    for a in atts:
        p = a.get("stored_path")
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    try:
        store.delete_pending(int(pending_id))
    except KeyError:
        raise HTTPException(404, {"error": "Not found"})
    return {"ok": True}


@router.post("/pending-expenses/{pending_id}/attachments")
async def upload_pending_attachment(request: Request, pending_id: int, file: UploadFile = File(...)):
    store = request.app.state.pending_store
    try:
        _ = store.get_pending(int(pending_id))
    except KeyError:
        raise HTTPException(404, {"error": "Not found"})

    # Save locally
    ext = guess_extension(file.filename) or ""
    att = store.add_attachment(int(pending_id), original_name=file.filename, fileobj=file.file, ext=ext)
    return {"ok": True, "attachment": att}


@router.get("/pending-expenses/{pending_id}/attachments")
def list_pending_attachments(request: Request, pending_id: int):
    store = request.app.state.pending_store
    try:
        _ = store.get_pending(int(pending_id))
    except KeyError:
        raise HTTPException(404, {"error": "Not found"})
    return {"ok": True, "attachments": store.list_attachments(int(pending_id))}


@router.get("/pending-expenses/attachments/open/{attachment_id}")
def open_pending_attachment(request: Request, attachment_id: int):
    store = request.app.state.pending_store
    try:
        path, filename = store.get_attachment_path(int(attachment_id))
    except KeyError:
        raise HTTPException(404, {"error": "Attachment not found"})
    if not path or not os.path.exists(path):
        raise HTTPException(404, {"error": "Attachment not found"})
    return FileResponse(path, filename=filename)


@router.post("/pending-expenses/{pending_id}/approve")
async def approve_pending_expense(request: Request, pending_id: int):
    """
    Approve = create expense in Zoho + attach local files + mark posted locally.
    """
    store = request.app.state.pending_store
    try:
        row = store.get_pending(int(pending_id))
    except KeyError:
        raise HTTPException(404, {"error": "Not found"})

    settings = request.app.state.settings

    payload = {
        "date": row.get("date") or "",
        "amount": float(row.get("amount") or 0),
        "account_id": row.get("account_id") or "",
        "paid_through_account_id": row.get("paid_through_account_id") or "",
        "reference_number": row.get("reference") or "",
        "description": row.get("notes") or "",
    }
    if row.get("vendor_id"):
        payload["vendor_id"] = row.get("vendor_id")

    created = zoho_create_expense(settings, payload)
    if created.get("code") != 0:
        raise HTTPException(400, created)

    exp = created.get("expense") or {}
    expense_id = exp.get("expense_id")
    if not expense_id:
        raise HTTPException(400, {"error": "Zoho did not return expense_id", "zoho": created})

    # Attach files (first as receipt; rest as attachment)
    attach_errors = []
    atts = store.list_attachments(int(pending_id))
    for idx, a in enumerate(atts):
        p = a.get("stored_path")
        if not p or not os.path.exists(p):
            continue
        try:
            with open(p, "rb") as f:
                if idx == 0:
                    out = zoho_add_expense_receipt(settings, expense_id, a.get("original_name") or a.get("stored_name") or "receipt", f)
                else:
                    out = zoho_add_expense_attachment(settings, expense_id, a.get("original_name") or a.get("stored_name") or "attachment", f)
            if out.get("code") not in (0, None):
                attach_errors.append({"attachment_id": a.get("id"), "zoho": out})
        except Exception as e:
            attach_errors.append({"attachment_id": a.get("id"), "error": str(e)})

    store.mark_posted(int(pending_id), expense_id)
    return {"ok": True, "zoho_expense_id": expense_id, "attachment_errors": attach_errors}
