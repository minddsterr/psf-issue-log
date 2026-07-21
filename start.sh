#!/bin/bash
# สคริปต์เริ่มระบบแจ้งปัญหาการใช้งาน
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "==> สร้าง virtual environment ครั้งแรก..."
  python3 -m venv venv
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install --quiet -r requirements.txt
fi

echo "==> เริ่มเซิร์ฟเวอร์ที่ http://localhost:8080"
echo "    (เครื่องอื่นในวง LAN เข้าผ่าน http://<IP-เครื่องนี้>:8080)"
exec ./venv/bin/python3 server.py
