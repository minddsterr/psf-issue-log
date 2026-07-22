# PSF Issue Log

เว็บแอปแจ้งปัญหาการใช้งานสไตล์ Trello — มีเมนูหลัก 10 ระบบ, บอร์ด 3 คอลัมน์สถานะ
(แจ้งปัญหาใหม่ / กำลังดำเนินการ / แก้ไขแล้ว), เปิดการ์ดใส่รายละเอียด/แนบรูปภาพ/ไฟล์,
ลากการ์ดข้ามคอลัมน์ได้ และมีฐานข้อมูลกลางให้ทีมใช้ร่วมกัน

## สถาปัตยกรรม

- **Backend:** Python + FastAPI (`server.py`)
- **ฐานข้อมูล:** สลับอัตโนมัติตาม env
  - ถ้ามี `DATABASE_URL` → **PostgreSQL** (เก็บถาวรบน cloud เช่น Supabase)
  - ถ้าไม่มี → **SQLite** ไฟล์ `data/issues.db` (สำหรับรัน/เทสในเครื่อง)
- **ไฟล์แนบ:** เก็บเป็น BLOB **ในฐานข้อมูลเดียวกัน** (ไม่ใช้ดิสก์แยก) → ย้าย/deploy ที่ไหนข้อมูลก็ตามไปครบ
- **Frontend:** `index.html` ไฟล์เดียว เรียก REST API และ poll ข้อมูลใหม่ทุก 5 วินาที
- **ไม่มีระบบล็อกอิน** — ใครมีลิงก์ก็เข้าใช้งานได้ (เหมาะกับแชร์เฉพาะเจ้าหน้าที่)

## รันในเครื่อง (local)

```bash
./start.sh
```

ครั้งแรกจะสร้าง virtual environment + ติดตั้ง dependency ให้เอง แล้วเปิดที่ `http://localhost:8080`
เพื่อนในวง LAN เดียวกันเข้าที่ `http://<IP-เครื่องที่รัน>:8080`

## นำขึ้น server ฟรี + เก็บข้อมูลถาวร (Render + Supabase)

Render ฟรีไม่มี disk ถาวร (ข้อมูลหายเมื่อ service หลับ/deploy ใหม่) เราจึงเก็บข้อมูลไว้ที่
**Supabase (PostgreSQL ฟรี)** แทน — ข้อมูล + ไฟล์แนบอยู่ถาวร ไม่หาย

### 1. สร้างฐานข้อมูลที่ Supabase (ฟรี)
1. เข้า [supabase.com](https://supabase.com) → สมัคร/ล็อกอิน → **New project**
2. ตั้งชื่อ + ตั้ง **Database Password** (จำไว้) → เลือก region ใกล้ๆ (Singapore) → Create
3. รอสร้างเสร็จ ~2 นาที → เมนู **Project Settings → Database → Connection string → URI**
4. คัดลอก connection string (หน้าตา `postgresql://postgres:[PASSWORD]@db.xxxx.supabase.co:5432/postgres`)
   แล้วแทน `[PASSWORD]` ด้วยรหัสที่ตั้งไว้ข้อ 2

### 2. ตั้ง env บน Render
ที่หน้า service บน Render → **Environment** → **Add Environment Variable**
- Key: `DATABASE_URL`
- Value: connection string จากข้อ 1
- Save → Render จะ deploy ใหม่เอง แล้วสลับไปใช้ Postgres อัตโนมัติ (ตารางสร้างให้เอง)

### 3. Deploy โค้ด
push ขึ้น GitHub (repo เดิม) แล้ว Render จะ build + deploy อัตโนมัติ
เสร็จแล้วเปิด `https://psf-issue-log.onrender.com` ได้จากทุกที่ ข้อมูลอยู่ถาวร

> **ข้อควรรู้:**
> - Render ฟรียัง "หลับ" เมื่อไม่มีคนใช้ ~15 นาที เข้าครั้งแรกหลังหลับช้า ~30 วิ (แต่ข้อมูลไม่หายแล้ว)
> - Supabase ฟรี: DB 500 MB — ไฟล์แนบเก็บใน DB ด้วย จึงจำกัดขนาดไฟล์ละ 10 MB (แก้ได้ที่ `MAX_FILE_MB` ใน `server.py`)
> - Supabase ฟรีจะ pause project ถ้าไม่มีใช้งาน 7 วัน (ข้อมูลไม่หาย กด resume ได้)

การตั้งค่าที่เกี่ยวข้อง (env):
- `DATABASE_URL` — connection string ของ Postgres (ถ้าไม่ตั้ง = ใช้ SQLite ในเครื่อง)
- `PORT` — พอร์ตที่เซิร์ฟเวอร์ฟัง (Render ตั้งให้อัตโนมัติ)
- `DATA_DIR` — โฟลเดอร์เก็บไฟล์ SQLite ตอนรัน local (ค่าเริ่มต้น `./data`)

## API endpoints

| Method | Path | หน้าที่ |
|--------|------|---------|
| GET    | `/api/cards` | ดึงการ์ดทั้งหมด |
| POST   | `/api/cards` | สร้างการ์ด |
| PATCH  | `/api/cards/{id}` | แก้ไขการ์ด |
| POST   | `/api/cards/reorder` | ย้าย/จัดลำดับการ์ด |
| DELETE | `/api/cards/{id}` | ลบการ์ด (ลบไฟล์แนบด้วย) |
| POST   | `/api/cards/{id}/attachments` | อัปโหลดไฟล์แนบ (เก็บใน DB) |
| DELETE | `/api/attachments/{id}` | ลบไฟล์แนบ |
| GET    | `/files/{id}` | โหลดไฟล์แนบจาก DB |
