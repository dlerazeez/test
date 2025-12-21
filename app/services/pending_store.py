import sqlite3
import uuid
from pathlib import Path
from datetime import datetime

from app.core.config import PENDING_DB_PATH, PENDING_UPLOADS_DIR


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def init_db():
    PENDING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS pending_expenses (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            account_id TEXT NOT NULL,
            paid_through_account_id TEXT NOT NULL,
            amount REAL NOT NULL,
            vendor_id TEXT,
            notes TEXT,
            reference_number TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS pending_attachments (
            id TEXT PRIMARY KEY,
            expense_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT,
            stored_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(expense_id) REFERENCES pending_expenses(id)
        )
        """)
        con.commit()


init_db()


def create_pending_expense(payload: dict) -> dict:
    exp_id = str(uuid.uuid4())
    now = _utc_now()

    row = {
        "id": exp_id,
        "date": payload["date"],
        "account_id": str(payload["account_id"]).strip(),
        "paid_through_account_id": str(payload["paid_through_account_id"]).strip(),
        "amount": float(payload["amount"]),
        "vendor_id": (str(payload["vendor_id"]).strip() if payload.get("vendor_id") else None),
        "notes": (payload.get("notes") or "").strip() or None,
        "reference_number": (payload.get("reference_number") or "").strip() or None,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
    }

    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.execute(
            """INSERT INTO pending_expenses
               (id,date,account_id,paid_through_account_id,amount,vendor_id,notes,reference_number,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["id"], row["date"], row["account_id"], row["paid_through_account_id"], row["amount"],
                row["vendor_id"], row["notes"], row["reference_number"], row["status"], row["created_at"], row["updated_at"]
            )
        )
        con.commit()

    return row


def list_pending_expenses(status: str = "PENDING", date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    q = "SELECT id,date,amount,vendor_id,reference_number,notes,account_id,paid_through_account_id,status,created_at,updated_at FROM pending_expenses WHERE status=?"
    params = [status]

    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)

    q += " ORDER BY date DESC, created_at DESC"

    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(q, params).fetchall()

    return [dict(r) for r in rows]


def get_pending_expense(expense_id: str) -> dict | None:
    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT * FROM pending_expenses WHERE id=?",
            (expense_id,)
        ).fetchone()
    return dict(r) if r else None


def update_pending_expense(expense_id: str, payload: dict) -> dict:
    existing = get_pending_expense(expense_id)
    if not existing:
        raise KeyError("Pending expense not found")

    allowed = {"date", "amount", "account_id", "paid_through_account_id", "vendor_id", "notes", "reference_number"}
    updates = {}
    for k in allowed:
        if k in payload:
            updates[k] = payload[k]

    if "amount" in updates:
        updates["amount"] = float(updates["amount"])
    if "account_id" in updates:
        updates["account_id"] = str(updates["account_id"]).strip()
    if "paid_through_account_id" in updates:
        updates["paid_through_account_id"] = str(updates["paid_through_account_id"]).strip()
    if "vendor_id" in updates:
        updates["vendor_id"] = (str(updates["vendor_id"]).strip() if updates["vendor_id"] else None)
    if "notes" in updates:
        updates["notes"] = (updates["notes"] or "").strip() or None
    if "reference_number" in updates:
        updates["reference_number"] = (updates["reference_number"] or "").strip() or None

    updates["updated_at"] = _utc_now()

    sets = ", ".join([f"{k}=?" for k in updates.keys()])
    params = list(updates.values()) + [expense_id]

    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.execute(f"UPDATE pending_expenses SET {sets} WHERE id=?", params)
        con.commit()

    return get_pending_expense(expense_id)


def add_pending_attachment(expense_id: str, filename: str, content_type: str | None, data: bytes) -> dict:
    if not get_pending_expense(expense_id):
        raise KeyError("Pending expense not found")

    att_id = str(uuid.uuid4())
    exp_dir = (PENDING_UPLOADS_DIR / expense_id)
    exp_dir.mkdir(parents=True, exist_ok=True)

    stored_path = exp_dir / f"{att_id}__{filename}"
    stored_path.write_bytes(data)

    row = {
        "id": att_id,
        "expense_id": expense_id,
        "filename": filename,
        "content_type": content_type,
        "stored_path": str(stored_path),
        "uploaded_at": _utc_now(),
    }

    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.execute(
            "INSERT INTO pending_attachments (id,expense_id,filename,content_type,stored_path,uploaded_at) VALUES (?,?,?,?,?,?)",
            (row["id"], row["expense_id"], row["filename"], row["content_type"], row["stored_path"], row["uploaded_at"])
        )
        con.commit()

    return row


def list_pending_attachments(expense_id: str) -> list[dict]:
    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id,expense_id,filename,content_type,stored_path,uploaded_at FROM pending_attachments WHERE expense_id=? ORDER BY uploaded_at DESC",
            (expense_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_attachment(expense_id: str, attachment_id: str) -> dict | None:
    with sqlite3.connect(PENDING_DB_PATH) as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT id,expense_id,filename,content_type,stored_path,uploaded_at FROM pending_attachments WHERE expense_id=? AND id=?",
            (expense_id, attachment_id)
        ).fetchone()
    return dict(r) if r else None
