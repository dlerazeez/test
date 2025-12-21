import os
import sqlite3
import time
from dataclasses import asdict


class PendingStore:
    def __init__(self, db_path: str, storage_dir: str):
        self.db_path = db_path
        self.storage_dir = storage_dir
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS pending_expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    account_id TEXT NOT NULL,
                    paid_through_account_id TEXT NOT NULL,
                    notes TEXT,
                    vendor_id TEXT,
                    vendor_name TEXT,
                    reference TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    zoho_expense_id TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS pending_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pending_id INTEGER NOT NULL,
                    original_name TEXT,
                    stored_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (pending_id) REFERENCES pending_expenses(id)
                )
            """)

    def create_pending(self, payload: dict) -> dict:
        now = int(time.time())
        with self._connect() as con:
            cur = con.execute("""
                INSERT INTO pending_expenses
                (date, amount, account_id, paid_through_account_id, notes, vendor_id, vendor_name, reference, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """, (
                payload["date"],
                float(payload["amount"]),
                str(payload["account_id"]),
                str(payload["paid_through_account_id"]),
                payload.get("notes"),
                payload.get("vendor_id"),
                payload.get("vendor_name"),
                payload.get("reference"),
                now,
                now
            ))
            pid = cur.lastrowid
        return self.get_pending(pid)

    def list_pending(self, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        where = ["status = 'PENDING'"]
        args = []
        if date_from:
            where.append("date >= ?")
            args.append(date_from)
        if date_to:
            where.append("date <= ?")
            args.append(date_to)

        q = "SELECT * FROM pending_expenses WHERE " + " AND ".join(where) + " ORDER BY date DESC, id DESC"
        with self._connect() as con:
            rows = con.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def get_pending(self, pending_id: int) -> dict:
        with self._connect() as con:
            row = con.execute("SELECT * FROM pending_expenses WHERE id = ?", (pending_id,)).fetchone()
        if not row:
            raise KeyError("pending_not_found")
        return dict(row)

    def update_pending(self, pending_id: int, payload: dict) -> dict:
        now = int(time.time())
        fields = []
        args = []
        for k in ["date", "amount", "account_id", "paid_through_account_id", "notes", "vendor_id", "vendor_name", "reference"]:
            if k in payload:
                fields.append(f"{k} = ?")
                args.append(payload[k])
        fields.append("updated_at = ?")
        args.append(now)
        args.append(pending_id)

        with self._connect() as con:
            con.execute(f"UPDATE pending_expenses SET {', '.join(fields)} WHERE id = ?", args)
        return self.get_pending(pending_id)

    def add_attachment(self, pending_id: int, original_name: str | None, stored_name: str, stored_path: str) -> dict:
        now = int(time.time())
        with self._connect() as con:
            cur = con.execute("""
                INSERT INTO pending_attachments (pending_id, original_name, stored_name, stored_path, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (pending_id, original_name, stored_name, stored_path, now))
            att_id = cur.lastrowid
            row = con.execute("SELECT * FROM pending_attachments WHERE id = ?", (att_id,)).fetchone()
        return dict(row)

    def list_attachments(self, pending_id: int) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM pending_attachments WHERE pending_id = ? ORDER BY id DESC",
                (pending_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_attachment(self, attachment_id: int) -> dict:
        with self._connect() as con:
            row = con.execute("SELECT * FROM pending_attachments WHERE id = ?", (attachment_id,)).fetchone()
        if not row:
            raise KeyError("attachment_not_found")
        return dict(row)

    def mark_posted(self, pending_id: int, zoho_expense_id: str) -> dict:
        now = int(time.time())
        with self._connect() as con:
            con.execute("""
                UPDATE pending_expenses
                SET status = 'POSTED', zoho_expense_id = ?, updated_at = ?
                WHERE id = ?
            """, (zoho_expense_id, now, pending_id))
        return self.get_pending(pending_id)
