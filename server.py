import os
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, List
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "issues.db")

# ถ้ามี DATABASE_URL (เช่นจาก Supabase) → ใช้ Postgres (เก็บถาวรบน cloud)
# ถ้าไม่มี → ใช้ SQLite ไฟล์ในเครื่อง (สำหรับรัน/เทสในเครื่อง)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith("postgres")

MAX_FILE_MB = 10  # จำกัดขนาดไฟล์แนบต่อไฟล์

if IS_PG:
    import psycopg2
    import psycopg2.extras


def get_conn():
    if IS_PG:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _cursor(conn):
    if IS_PG:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def _q(sql):
    """แปลง placeholder ? → %s สำหรับ Postgres"""
    return sql.replace("?", "%s") if IS_PG else sql


def _blob(data: bytes):
    """ห่อ bytes ให้เหมาะกับ backend"""
    return psycopg2.Binary(data) if IS_PG else data


def _ensure_column(cur, table, col, coldef):
    """เพิ่มคอลัมน์ถ้ายังไม่มี (migration รองรับ DB ที่สร้างไว้แล้ว)"""
    if IS_PG:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {coldef}")
    else:
        cur.execute(f"PRAGMA table_info({table})")
        existing = [r["name"] for r in cur.fetchall()]
        if col not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")


def init_db():
    conn = get_conn()
    cur = _cursor(conn)
    if IS_PG:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                department TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                reporter TEXT DEFAULT '',
                position DOUBLE PRECISION NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id TEXT PRIMARY KEY,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                content_type TEXT,
                size INTEGER,
                data BYTEA NOT NULL
            );
            """
        )
    else:
        cur.executescript(
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
                data BLOB NOT NULL
            );
            """
        )
    # migration: ฟิลด์ที่เพิ่มทีหลัง
    _ensure_column(cur, "cards", "assignee", "TEXT DEFAULT ''")
    _ensure_column(cur, "cards", "jira_url", "TEXT DEFAULT ''")
    _ensure_column(cur, "cards", "priority", "TEXT DEFAULT ''")
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
    assignee: Optional[str] = None
    jira_url: Optional[str] = None
    priority: Optional[str] = None


class ReorderItem(BaseModel):
    id: int
    status: str
    position: float


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def attachments_for(cur, card_id):
    cur.execute(
        _q("SELECT id, filename, content_type, size FROM attachments WHERE card_id = ?"),
        (card_id,),
    )
    rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "name": r["filename"],
            "type": r["content_type"],
            "size": r["size"],
            "url": f"/files/{r['id']}",
        }
        for r in rows
    ]


def card_to_dict(cur, row):
    d = dict(row)
    d["attachments"] = attachments_for(cur, row["id"])
    return d


# ---------------- Cards ----------------

@app.get("/api/cards")
def list_cards():
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute("SELECT * FROM cards ORDER BY position ASC")
    rows = cur.fetchall()
    result = [card_to_dict(cur, r) for r in rows]
    conn.close()
    return result


@app.post("/api/cards")
def create_card(card: CardCreate):
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute(
        _q("SELECT MAX(position) as m FROM cards WHERE department = ? AND status = ?"),
        (card.department, card.status),
    )
    max_pos = cur.fetchone()["m"]
    position = (max_pos or 0) + 1024
    now = now_iso()

    if IS_PG:
        cur.execute(
            _q(
                """INSERT INTO cards (department, status, title, description, reporter, position, created_at, updated_at)
                   VALUES (?, ?, ?, '', '', ?, ?, ?) RETURNING id"""
            ),
            (card.department, card.status, card.title.strip(), position, now, now),
        )
        new_id = cur.fetchone()["id"]
    else:
        cur.execute(
            _q(
                """INSERT INTO cards (department, status, title, description, reporter, position, created_at, updated_at)
                   VALUES (?, ?, ?, '', '', ?, ?, ?)"""
            ),
            (card.department, card.status, card.title.strip(), position, now, now),
        )
        new_id = cur.lastrowid

    conn.commit()
    cur.execute(_q("SELECT * FROM cards WHERE id = ?"), (new_id,))
    result = card_to_dict(cur, cur.fetchone())
    conn.close()
    return result


@app.patch("/api/cards/{card_id}")
def update_card(card_id: int, patch: CardUpdate):
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute(_q("SELECT * FROM cards WHERE id = ?"), (card_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "not found")

    fields = patch.dict(exclude_unset=True)
    if "title" in fields:
        fields["title"] = (fields["title"] or "").strip() or row["title"]
    merged = dict(row)
    merged.update(fields)
    merged["updated_at"] = now_iso()

    cur.execute(
        _q(
            """UPDATE cards SET title=?, description=?, reporter=?, department=?,
               status=?, position=?, assignee=?, jira_url=?, priority=?, updated_at=? WHERE id=?"""
        ),
        (
            merged["title"],
            merged["description"],
            merged["reporter"],
            merged["department"],
            merged["status"],
            merged["position"],
            merged.get("assignee", ""),
            merged.get("jira_url", ""),
            merged.get("priority", ""),
            merged["updated_at"],
            card_id,
        ),
    )
    conn.commit()
    cur.execute(_q("SELECT * FROM cards WHERE id = ?"), (card_id,))
    result = card_to_dict(cur, cur.fetchone())
    conn.close()
    return result


@app.post("/api/cards/reorder")
def reorder_cards(items: List[ReorderItem]):
    conn = get_conn()
    cur = _cursor(conn)
    now = now_iso()
    for item in items:
        cur.execute(
            _q("UPDATE cards SET status = ?, position = ?, updated_at = ? WHERE id = ?"),
            (item.status, item.position, now, item.id),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: int):
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute(_q("DELETE FROM cards WHERE id = ?"), (card_id,))
    conn.commit()
    conn.close()
    return JSONResponse(status_code=204, content=None)


# ---------------- Attachments (เก็บไฟล์ในฐานข้อมูล) ----------------

@app.post("/api/cards/{card_id}/attachments")
async def upload_attachments(card_id: int, files: List[UploadFile] = File(...)):
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute(_q("SELECT id FROM cards WHERE id = ?"), (card_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(404, "card not found")

    created = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            conn.close()
            raise HTTPException(413, f"ไฟล์ {f.filename} ใหญ่เกิน {MAX_FILE_MB} MB")
        att_id = uuid.uuid4().hex
        cur.execute(
            _q(
                """INSERT INTO attachments (id, card_id, filename, content_type, size, data)
                   VALUES (?, ?, ?, ?, ?, ?)"""
            ),
            (att_id, card_id, f.filename, f.content_type, len(data), _blob(data)),
        )
        created.append(
            {
                "id": att_id,
                "name": f.filename,
                "type": f.content_type,
                "size": len(data),
                "url": f"/files/{att_id}",
            }
        )
    cur.execute(_q("UPDATE cards SET updated_at = ? WHERE id = ?"), (now_iso(), card_id))
    conn.commit()
    conn.close()
    return created


@app.delete("/api/attachments/{att_id}")
def delete_attachment(att_id: str):
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute(_q("DELETE FROM attachments WHERE id = ?"), (att_id,))
    conn.commit()
    conn.close()
    return JSONResponse(status_code=204, content=None)


@app.get("/files/{att_id}")
def get_file(att_id: str):
    conn = get_conn()
    cur = _cursor(conn)
    cur.execute(
        _q("SELECT filename, content_type, data FROM attachments WHERE id = ?"),
        (att_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "ไม่พบไฟล์")
    data = bytes(row["data"])
    fname = row["filename"] or "file"
    # HTTP header เป็น latin-1 เท่านั้น → ชื่อไฟล์ภาษาไทยต้อง encode แบบ RFC 5987
    ascii_fallback = fname.encode("ascii", "ignore").decode().strip() or "file"
    ascii_fallback = ascii_fallback.replace('"', "")
    disposition = f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(fname)}"
    return Response(
        content=data,
        media_type=row["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


# ---------------- Health check ----------------

@app.get("/api/health")
def health():
    backend = "postgres" if IS_PG else "sqlite"
    try:
        conn = get_conn()
        cur = _cursor(conn)
        cur.execute("SELECT COUNT(*) as n FROM cards")
        n = cur.fetchone()["n"]
        conn.close()
        return {"backend": backend, "cards": n, "ok": True}
    except Exception as e:
        return {"backend": backend, "ok": False, "error": str(e)}


# ---------------- Frontend ----------------

@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
