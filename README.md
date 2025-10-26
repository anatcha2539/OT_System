# ระบบจัดการและแจ้งเตือน OT (OT Management System) 📅

ระบบจัดการ OT (Overtime) อัตโนมัติ สร้างด้วย Flask และเชื่อมต่อกับ LINE Bot เพื่อส่งแบบสำรวจ (Survey) ยืนยันสิทธิ์ OT ให้พนักงาน และสรุปผลให้ Admin ผ่านหน้า Dashboard

โปรเจกต์นี้ถูกออกแบบมาเพื่อลดขั้นตอนการทำงาน Manual ของ Admin ในการโทรหรือส่งข้อความถามพนักงานทีละคน และช่วยให้พนักงานสามารถยืนยัน/สละสิทธิ์ OT หรือมอบสิทธิ์ต่อให้คนอื่นได้สะดวกผ่านลิงก์ส่วนตัว

!
---

## 🚀 คุณสมบัติหลัก (Features)

### สำหรับ Admin (ผู้ดูแลระบบ)
* **🔑 ระบบ Login:** หน้า Login ที่ปลอดภัย (ใช้ Flask-Login) สำหรับ Admin
* **📊 Dashboard สรุปผล:** หน้าสรุปผลที่สวยงาม (สร้างด้วย Bootstrap) แสดงสถานะการตอบรับ (ยืนยัน, สละสิทธิ์, ยังไม่ตอบ) ของพนักงานในแต่ละวัน
* **👥 จัดการพนักงาน:** เพิ่ม, ลบ, แก้ไขข้อมูลพนักงาน และที่สำคัญคือการผูก `LINE User ID`
* **🗓️ สร้างตาราง OT:** เลือกวันที่และพนักงานผู้มีสิทธิ์ในวันนั้น ระบบจะสร้างลิงก์ Survey และส่ง LINE แจ้งเตือนอัตโนมัติ
* **🔔 แจ้งเตือน Admin:** สามารถส่งข้อความเตือน (Push Message) ไปยังพนักงานที่ยังไม่ตอบแบบรายคนได้
* **👀 ติดตามผล Real-time:** ดูได้ทันทีว่าใครสละสิทธิ์, ใครมอบสิทธิ์ให้คนอื่น, หรือใครให้ Admin ช่วยเลือกแทน

### สำหรับพนักงาน (User)
* **📱 รับแจ้งเตือนผ่าน LINE:** เมื่อ Admin สร้างตาราง OT, พนักงานที่มี `LINE User ID` ในระบบจะได้รับข้อความแจ้งเตือนพร้อมลิงก์ Survey ส่วนตัวทันที
* **📝 หน้า Survey ที่ใช้งานง่าย:**
    * **ยืนยัน:** กดยืนยันสิทธิ์ OT
    * **สละสิทธิ์ (ให้ Admin เลือกแทน):** สละสิทธิ์และให้ Admin เป็นคนหาคนใหม่
    * **สละสิทธิ์ (มอบให้เพื่อน):** เลือกพนักงานคนอื่นที่ว่างในวันนั้นมารับสิทธิ์แทน (ระบบจะกรองคนที่มี OT วันเดียวกันหรือถูกเลือกไปแล้วออก)
* **🤖 คำสั่ง LINE Bot:** พิมพ์ "ดูตาราง OT ที่ยังไม่ตอบ" เพื่อให้ Bot สรุปรายการ OT ที่ค้างอยู่ (เฉพาะ OT ที่ยังไม่ถึงกำหนด)

---

## 🛠️ เทคโนโลยีที่ใช้ (Tech Stack)

* **Backend:** Python 3, Flask
* **Database:** SQLAlchemy (สามารถใช้ได้ทั้ง SQLite, PostgreSQL)
* **Authentication:** Flask-Login
* **Web Server (Production):** Gunicorn
* **LINE API:**
    * `line-bot-sdk (v3)`: สำหรับ Webhook (รับข้อความ/คำสั่งจาก User)
    * `line-bot-sdk (v1/v2)`: สำหรับ Push Message (ส่งข้อความหา User/กลุ่ม)
* **Frontend:** Bootstrap 5, Jinja2
* **Deployment:** (แนะนำ) Render.com

---

## 🏁 การติดตั้งและใช้งาน (Setup & Deployment)

ทำตามขั้นตอนเหล่านี้เพื่อ Deploy โปรเจกต์ของคุณบน Render (ซึ่งรองรับ Free Tier)

### 1. เตรียมโปรเจกต์และ GitHub
1.  สร้างไฟล์ `requirements.txt` ในโปรเจกต์ของคุณ:
    ```bash
    pip install gunicorn
    pip freeze > requirements.txt
    ```
2.  Push โค้ดทั้งหมด (รวมถึง `app.py`, `requirements.txt`, โฟลเดอร์ `templates`) ขึ้น GitHub Repository

### 2. ตั้งค่า LINE Developer Console
1.  ไปที่ [LINE Developer Console](https://developers.line.biz/console/)
2.  สร้าง Provider และ Channel ประเภท **Messaging API**
3.  จดบันทึกค่า 3 อย่างนี้:
    * `Channel Secret` (จากแท็บ Basic settings)
    * `Channel access token (long-lived)` (จากแท็บ Messaging API)
    * `LINE User ID` (U...) ของคุณเอง (สำหรับทดสอบ)

### 3. Deploy บน Render.com
1.  **สร้างฐานข้อมูล:**
    * ที่ Dashboard ของ Render -> **New +** -> **PostgreSQL**
    * เลือกแพ็กเกจ **Free**
    * รอจนสร้างเสร็จ แล้วคัดลอก **Internal Database URL** เก็บไว้

2.  **สร้าง Web Service:**
    * ที่ Dashboard ของ Render -> **New +** -> **Web Service**
    * เชื่อมต่อกับ GitHub Repository ของคุณ
    * **Region:** เลือก `Singapore` (ใกล้ไทยที่สุด)
    * **Build Command:** `pip install -r requirements.txt`
    * **Start Command:** `gunicorn app:app`
    * เลือกแพ็กเกจ **Free**

3.  **ตั้งค่า Environment Variables (สำคัญมาก):**
    * ไปที่แท็บ **Environment** ของ Web Service ที่เพิ่งสร้าง
    * เพิ่มค่าเหล่านี้ทีละตัว:
    * `DATABASE_URL`: (วางค่า Internal Database URL ที่คัดลอกมาจากข้อ 1)
    * `FLASK_SECRET_KEY`: (สุ่มข้อความยาวๆ อะไรก็ได้ เช่น `my-flask-app-secret-key-12345`)
    * `LINE_CHANNEL_ACCESS_TOKEN`: (จาก LINE Dev Console)
    * `LINE_CHANNEL_SECRET`: (จาก LINE Dev Console)
    * `LINE_TARGET_GROUP_ID`: (รหัสกลุ่ม LINE `C...` ที่คุณต้องการให้ Bot ส่งแจ้งเตือนเวลามีคนสละสิทธิ์)

4.  รอจน Render Deploy เสร็จ (สถานะขึ้นว่า "Live") คุณจะได้ URL ของแอป เช่น `https://your-app-name.onrender.com`

### 4. เชื่อมต่อระบบ (ขั้นตอนสุดท้าย)
1.  **สร้าง Admin คนแรก:**
    * เปิดเบราว์เซอร์และไปที่: `https://your-app-name.onrender.com/admin/create-first-admin`
    * ระบบจะสร้าง User `admin` รหัสผ่าน `password123` ให้
    * **(เพื่อความปลอดภัย)** กลับไปที่โค้ด `app.py` ของคุณ **คอมเมนต์ (`#`)** Route `/admin/create-first-admin` ทิ้ง แล้ว Push ขึ้น GitHub (Render จะ Deploy ใหม่)

2.  **ตั้งค่า Webhook:**
    * กลับไปที่ LINE Developer Console -> แท็บ `Messaging API`
    * ในช่อง **Webhook URL** ใส่: `https://your-app-name.onrender.com/callback`
    * กด "Verify" (ต้องขึ้น Success)
    * เปิด **"Use webhook"** (ใช้เว็บฮุค)

3.  **Login และเพิ่มพนักงาน:**
    * ไปที่ `https://your-app-name.onrender.com/login`
    * Login ด้วย `admin` / `password123`
    * ไปที่หน้า **"จัดการพนักงาน"**
    * **วิธีหา LINE User ID:** ให้พนักงานทัก LINE Bot ของคุณ (พิมพ์อะไรก็ได้) Bot จะตอบกลับ User ID ของเขามา (ตามโค้ดใน `handle_message`)
    * นำ User ID (`U...`) นั้นมาใส่ในช่องของพนักงานแต่ละคน

4.  **เริ่มต้นใช้งาน!**
    * ไปที่หน้า **"สร้างตาราง OT ใหม่"**
    * เลือกวันที่และพนักงาน
    * ระบบจะเริ่มส่ง LINE แจ้งเตือน และคุณสามารถดูผลสรุปได้ที่ Dashboard

---
## 🖼️ ภาพหน้าจอ (Screenshots)

(แนะนำ: แคปภาพหน้าจอแอปของคุณ แล้วลากมาวางใน GitHub เพื่ออัปโหลดและแสดงผลที่นี่)

| หน้า Admin Dashboard | หน้า Survey บนมือถือ |
| :---: | :---: |
|  |  |

| ตัวอย่างการแจ้งเตือน LINE | การตอบกลับ User ID |
| :---: | :---: |
|  |  |

---

## 📄 License

This project is licensed under the MIT License.