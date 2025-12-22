from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from datetime import datetime
import os
import time
import shutil

from app.core.zoho import (
    zoho_request,
    zoho_json,
    zoho_get_expense,
    zoho_update_expense,
    zoho_delete_expense,
    zoho_add_expense_attachment,
    zoho_list_expenses,
    zoho_list_expense_attachments,
    zoho_open_latest_expense_attachment,
)

router = APIRouter()


def _safe_str(v):
    return "" if v is None else str(v)


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
    try:
        out = zoho_list_expenses(
            request,
            page=page,
            per_page=per_page,
            filter_by=filter_by,
            search_text=search_text,
            date_from=date_from,
            date_to=date_to,
        )
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/by-id/{expense_id}")
def get_expense_by_id(request: Request, expense_id: str):
    try:
        exp = zoho_get_expense(request, expense_id)
        return {"ok": True, "expense": exp}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/expenses/update/{expense_id}")
async def update_expense(request: Request, expense_id: str):
    """
    Expects JSON body like:
    {
      "date": "YYYY-MM-DD",
      "amount": 1000,
      "vendor_id": "...",
      "reference_number": "...",
      "description": "...",
      "expense_account_id": "...",
      "paid_through_account_id": "..."
    }
    Only provided keys will be updated.
    """
    try:
        body = await request.json()
        updated = zoho_update_expense(request, expense_id, body)
        return {"ok": True, "expense": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/expenses/delete/{expense_id}")
def delete_expense(request: Request, expense_id: str):
    try:
        zoho_delete_expense(request, expense_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/expenses/{expense_id}/attachments")
async def upload_expense_attachment(request: Request, expense_id: str, file: UploadFile = File(...)):
    """
    Upload an attachment to a Zoho expense (non-overwriting).
    """
    try:
        temp_dir = os.path.join(os.getcwd(), "tmp_uploads")
        os.makedirs(temp_dir, exist_ok=True)

        filename = file.filename or f"upload_{int(time.time())}"
        temp_path = os.path.join(temp_dir, filename)

        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        out = zoho_add_expense_attachment(request, expense_id, temp_path, filename)
        try:
            os.remove(temp_path)
        except Exception:
            pass

        return {"ok": True, "data": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/{expense_id}/attachments/list")
def list_expense_attachments(request: Request, expense_id: str):
    try:
        out = zoho_list_expense_attachments(request, expense_id)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/{expense_id}/attachments/open-latest")
def open_latest_attachment(request: Request, expense_id: str):
    """
    Opens the latest attachment of a Zoho expense in a new tab.
    """
    try:
        return zoho_open_latest_expense_attachment(request, expense_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
