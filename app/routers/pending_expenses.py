from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from app.services.pending_store import (
    create_pending_expense, list_pending_expenses, get_pending_expense, update_pending_expense,
    add_pending_attachment, list_pending_attachments, get_pending_attachment
)

router = APIRouter(prefix="/pending-expenses", tags=["Pending Expenses (Local)"])


@router.post("/create")
def create_pending(payload: dict):
    required = ["date", "account_id", "amount", "paid_through_account_id"]
    missing = [f for f in required if f not in payload]
    if missing:
        raise HTTPException(400, {"error": "Missing fields", "missing": missing})

    row = create_pending_expense(payload)
    return {"ok": True, "pending": row}


@router.get("/list")
def list_pending(status: str = "PENDING", date_from: str | None = None, date_to: str | None = None):
    rows = list_pending_expenses(status=status, date_from=date_from, date_to=date_to)
    return {"ok": True, "count": len(rows), "pending": rows}


@router.get("/by-id/{expense_id}")
def get_pending_by_id(expense_id: str):
    row = get_pending_expense(expense_id)
    if not row:
        raise HTTPException(404, "Pending expense not found")
    atts = list_pending_attachments(expense_id)
    return {"ok": True, "pending": row, "attachments": atts}


@router.put("/update/{expense_id}")
def update_pending_by_id(expense_id: str, payload: dict):
    try:
        row = update_pending_expense(expense_id, payload)
    except KeyError:
        raise HTTPException(404, "Pending expense not found")
    return {"ok": True, "pending": row}


@router.post("/{expense_id}/attachments")
def upload_pending_attachment(expense_id: str, file: UploadFile = File(...)):
    try:
        data = add_pending_attachment(
            expense_id=expense_id,
            filename=file.filename or "attachment.bin",
            content_type=file.content_type,
            data=file.file.read(),
        )
    except KeyError:
        raise HTTPException(404, "Pending expense not found")

    return {"ok": True, "attachment": data}


@router.get("/{expense_id}/attachments")
def list_pending_files(expense_id: str):
    return {"ok": True, "attachments": list_pending_attachments(expense_id)}


@router.get("/{expense_id}/attachments/{attachment_id}")
def open_pending_file(expense_id: str, attachment_id: str):
    meta = get_pending_attachment(expense_id, attachment_id)
    if not meta:
        raise HTTPException(404, "Attachment not found")

    path = meta["stored_path"]
    content = open(path, "rb").read()
    return Response(content=content, media_type=meta.get("content_type") or "application/octet-stream")
