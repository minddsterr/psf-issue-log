# PSF Issue Log

เว็บแอปแจ้งปัญหาการใช้งานสไตล์ Trello — มีเมนูหลัก 10 ระบบ, บอร์ด 3 คอลัมน์สถานะ
(แจ้งปัญหาใหม่ / กำลังดำเนินการ / แก้ไขแล้ว), เปิดการ์ดใส่รายละเอียด/แนบรูปภาพ/ไฟล์,
ลากการ์ดข้ามคอลัมน์ได้ และมีฐานข้อมูลกลางให้ทีมใช้ร่วมกัน

## สถาปัตยกรรม

- **Backend:** Python + FastAPI (`server.py`)
- **ฐานข้อมูล:** SQLite — เก็บที่ `data/issues.db` (สร้างอัตโนมัติ)
- **ไฟล์แนบ:** เก็บบนดิสก์ที่ `data/uploads/`
- **Frontend:** `index.html` ไฟล์เดียว เรียก REST API และ poll ข้อมูลใหม่ทุก 5 วินาที
- **ไม่มีระบบล็อกอิน** — ใครมีลิงก์ก็เข้าใช้งานได้ (เหมาะกับแชร์เฉพาะเจ้าหน้าที่)

## รันในเครื่อง (local)

```bash
./start.sh
```

ครั้งแรกจะสร้าง virtual environment + ติดตั้ง dependency ให้เอง แล้วเปิดที่ `http://localhost:8080`
เพื่อนในวง LAN เดียวกันเข้าที่ `http://<IP-เครื่องที่รัน>:8080`

## นำขึ้น server ฟรี (deploy)

ในโปรเจกต์เตรียมไฟล์ไว้ให้พร้อมแล้ว: `Dockerfile`, `render.yaml`

### วิธีที่แนะนำ: Render.com (ฟรี)

1. push โค้ดชุดนี้ขึ้น GitHub repo (สาธารณะหรือส่วนตัวก็ได้)
2. เข้า [render.com](https://render.com) → สมัคร/ล็อกอิน (เชื่อมกับ GitHub ได้)
3. **New + → Blueprint** → เลือก repo นี้ → Render อ่าน `render.yaml` เอง → กด **Apply**
4. รอ build เสร็จ จะได้ URL แบบ `https://psf-issue-log.onrender.com` เปิดจากที่ไหนก็ได้

> **ข้อควรรู้ (สำคัญ):**
> - Render free tier จะ "หลับ" เมื่อไม่มีคนใช้ ~15 นาที เข้าครั้งแรกหลังหลับจะช้า ~30 วิ
> - Render free tier **ไม่มี disk ถาวร** → ข้อมูลจะรีเซ็ตเมื่อ deploy ใหม่ (เหมาะกับทดลอง/เดโม)
>   ถ้าต้องเก็บข้อมูลถาวรจริงจัง: upgrade เป็น plan ที่มี disk แล้วตั้ง env `DATA_DIR=/data` + mount disk ที่ `/data`
>   หรือย้าย DB ไป cloud (Turso/Supabase) + ไฟล์ไป object storage (Cloudflare R2)

การตั้งค่าที่เกี่ยวข้อง (env):
- `PORT` — พอร์ตที่เซิร์ฟเวอร์ฟัง (Render ตั้งให้อัตโนมัติ)
- `DATA_DIR` — โฟลเดอร์เก็บ DB + ไฟล์แนบ (ค่าเริ่มต้น `./data`)

## API endpoints

| Method | Path | หน้าที่ |
|--------|------|---------|
| GET    | `/api/cards` | ดึงการ์ดทั้งหมด |
| POST   | `/api/cards` | สร้างการ์ด |
| PATCH  | `/api/cards/{id}` | แก้ไขการ์ด |
| POST   | `/api/cards/reorder` | ย้าย/จัดลำดับการ์ด |
| DELETE | `/api/cards/{id}` | ลบการ์ด (ลบไฟล์แนบด้วย) |
| POST   | `/api/cards/{id}/attachments` | อัปโหลดไฟล์แนบ |
| DELETE | `/api/attachments/{id}` | ลบไฟล์แนบ |
| GET    | `/uploads/{name}` | โหลดไฟล์แนบ |
