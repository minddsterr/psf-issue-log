FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ที่เก็บข้อมูล (map เป็น persistent disk ตอน deploy ถ้ามี)
ENV DATA_DIR=/data
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
