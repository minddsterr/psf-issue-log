import os
import sqlite3
import uuid
import shutil
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# รองรับการตั้งที่เก็บข้อมูลผ่าน env (ใช้ตอน deploy ที่มี persistent disk)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "issues.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            reporter TEXT DEFAULT '',
            position REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            content_type TEXT,
            size INTEGER,
            stored_name TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


init_db()

app = FastAPI(title="PSF Issue Log")


class CardCreate(BaseModel):
    department: str
    status: str
    title: str


class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    reporter: Optional[str] = None
    department: Optional[str] = None
    status: Optional[str] = None
    position: Optional[float] = None


class ReorderItem(BaseModel):
    id: int
    status: str
    position: float


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def attachments_for(conn, card_id):
    rows = conn.execute(
        "SELECT * FROM attachments WHERE card_id = ?", (card_id,)
    ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["filename"],
            "type": r["content_type"],
            "size": r["size"],
            "url": f"/uploads/{r['stored_name']}",
        }
        for r in rows
    ]


def card_to_dict(conn, row):
    d = dict(row)
    d["attachments"] = attachments_for(conn, row["id"])
    return d


# ---------------- Uploads ----------------

@app.get("/uploads/{name}")
def get_upload(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "ชื่อไฟล์ไม่ถูกต้อง")
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(404, "ไม่พบไฟล์")
    return FileResponse(path)


# ---------------- Cards ----------------

@app.get("/api/cards")
def list_cards():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cards ORDER BY position ASC").fetchall()
    result = [card_to_dict(conn, r) for r in rows]
    conn.close()
    return result


@app.post("/api/cards")
def create_card(card: CardCreate):
    conn = get_conn()
    max_pos = conn.execute(
        "SELECT MAX(position) as m FROM cards WHERE department = ? AND status = ?",
        (card.department, card.status),
    ).fetchone()["m"]
    position = (max_pos or 0) + 1024
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO cards (department, status, title, description, reporter, position, created_at, updated_at)
           VALUES (?, ?, ?, '', '', ?, ?, ?)""",
        (card.department, card.status, card.title.strip(), position, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (cur.lastrowid,)).fetchone()
    result = card_to_dict(conn, row)
    conn.close()
    return result


@app.patch("/api/cards/{card_id}")
def update_card(card_id: int, patch: CardUpdate):
    conn = get_conn()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "not found")

    fields = patch.dict(exclude_unset=True)
    if "title" in fields:
        fields["title"] = fields["title"].strip() or row["title"]
    merged = dict(row)
    merged.update(fields)
    merged["updated_at"] = now_iso()

    conn.execute(
        """UPDATE cards SET title=?, description=?, reporter=?, department=?,
           status=?, position=?, updated_at=? WHERE id=?""",
        (
            merged["title"],
            merged["description"],
            merged["reporter"],
            merged["department"],
            merged["status"],
            merged["position"],
            merged["updated_at"],
            card_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    result = card_to_dict(conn, row)
    conn.close()
    return result


@app.post("/api/cards/reorder")
def reorder_cards(items: List[ReorderItem]):
    conn = get_conn()
    now = now_iso()
    for item in items:
        conn.execute(
            "UPDATE cards SET status = ?, position = ?, updated_at = ? WHERE id = ?",
            (item.status, item.position, now, item.id),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: int):
    conn = get_conn()
    atts = conn.execute(
        "SELECT stored_name FROM attachments WHERE card_id = ?", (card_id,)
    ).fetchall()
    for a in atts:
        path = os.path.join(UPLOAD_DIR, a["stored_name"])
        if os.path.exists(path):
            os.remove(path)
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()
    return JSONResponse(status_code=204, content=None)


# ---------------- Attachments ----------------

@app.post("/api/cards/{card_id}/attachments")
def upload_attachments(card_id: int, files: List[UploadFile] = File(...)):
    conn = get_conn()
    row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "card not found")

    created = []
    for f in files:
        ext = os.path.splitext(f.filename)[1]
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(UPLOAD_DIR, stored_name)
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        size = os.path.getsize(dest)
        att_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO attachments (id, card_id, filename, content_type, size, stored_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (att_id, card_id, f.filename, f.content_type, size, stored_name),
        )
        created.append(
            {
                "id": att_id,
                "name": f.filename,
                "type": f.content_type,
                "size": size,
                "url": f"/uploads/{stored_name}",
            }
        )
    conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (now_iso(), card_id))
    conn.commit()
    conn.close()
    return created


@app.delete("/api/attachments/{att_id}")
def delete_attachment(att_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "not found")
    path = os.path.join(UPLOAD_DIR, row["stored_name"])
    if os.path.exists(path):
        os.remove(path)
    conn.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
    conn.commit()
    conn.close()
    return JSONResponse(status_code=204, content=None)


# ---------------- Frontend ----------------

@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
