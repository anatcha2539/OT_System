# app.py (เวอร์ชันอัปเดต - Admin สร้าง Schedule เองได้)
import os
import uuid
from flask import Flask, request, jsonify, render_template, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

# --- 1. Import Library ของ LINE Bot SDK ---
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# --- 1. ตั้งค่าพื้นฐาน ---
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'ot_database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgres://your_user:your_pass@your_host/your_db_name'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === (สำคัญ) ใส่ Token และ ID ที่คุณหามาได้ ===
YOUR_CHANNEL_ACCESS_TOKEN = 'PL/avKB7pIC6D5K7uBhC0QysgPldURTehkZwRf7cj0FiIOEoYR6sNucNCc17heM1ckcN2cToU37xsaBbya94PF3N/ad32wz1Eg3b1+cTUR1EV8f8fzGYI0C+81vgkbM810Lrdl/nX49dPYwY6hehbQdB04t89/1O/w1cDnyilFU=' 
YOUR_TARGET_GROUP_ID = 'C73261ee748ea4c2e8af5033c68a7fd97'
# ===================================================

# --- 1.2 สร้าง Instance ของ LineBotApi ---
try:
    line_bot_api = LineBotApi(YOUR_CHANNEL_ACCESS_TOKEN)
except Exception as e:
    print(f"!!! Error initializing LineBotApi: {e}")
    line_bot_api = None

# --- 1.5 ฟังก์ชันสำหรับส่ง LINE (Messaging API) ---
def send_line_push_message(message_text):
    if not line_bot_api:
        print("ไม่สามารถส่ง LINE ได้: LineBotApi ไม่ได้ถูกตั้งค่า")
        return False
    if YOUR_TARGET_GROUP_ID == 'PASTE_YOUR_GROUP_ID_HERE':
        print("ไม่สามารถส่ง LINE ได้: กรุณาตั้งค่า YOUR_TARGET_GROUP_ID")
        return False
    try:
        message = TextSendMessage(text=message_text)
        line_bot_api.push_message(YOUR_TARGET_GROUP_ID, messages=message)
        print(f"ส่ง LINE Push Message เข้ากลุ่มสำเร็จ!")
        return True
    except LineBotApiError as e:
        print(f"ส่ง LINE Push Message ไม่สำเร็จ: {e.code} {e.message}")
        return False
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการส่ง LINE: {e}")
        return False

# --- 2. สร้างโมเดลฐานข้อมูล ---
# (ส่วน Model User, OTSchedule, OTResponse เหมือนเดิมทุกประการ)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    def __repr__(self):
        return f'<User {self.full_name}>'

class OTSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ot_date = db.Column(db.Date, nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class OTResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    schedule_id = db.Column(db.Integer, db.ForeignKey('ot_schedule.id'), nullable=False)
    primary_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    response_status = db.Column(db.String(50), default='pending')
    delegated_to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    let_admin_decide = db.Column(db.Boolean, default=False)
    schedule = db.relationship('OTSchedule', backref=db.backref('responses', lazy=True))
    primary_user = db.relationship('User', foreign_keys=[primary_user_id])
    delegated_user = db.relationship('User', foreign_keys=[delegated_to_user_id])


# --- 3. สร้าง API Endpoints ---

# (Endpoint /survey/... และ /api/survey-data/... เหมือนเดิม)

@app.route('/survey/<string:token>')
def show_survey(token):
    response = OTResponse.query.filter_by(token=token).first_or_404()
    return render_template('survey.html', 
                           response_id=response.id, 
                           user_name=response.primary_user.full_name,
                           ot_date=response.schedule.ot_date, # ส่งเป็น object date
                           current_status=response.response_status 
                          )

@app.route('/api/survey-data/<int:response_id>')
def get_survey_data(response_id):
    response = OTResponse.query.get_or_404(response_id)
    current_schedule_id = response.schedule_id
    
    all_primary_responses = OTResponse.query.filter_by(schedule_id=current_schedule_id).all()
    all_primary_user_ids = [r.primary_user_id for r in all_primary_responses]
    
    already_delegated_responses = OTResponse.query.filter(
        OTResponse.schedule_id == current_schedule_id,
        OTResponse.delegated_to_user_id.isnot(None) 
    ).all()
    already_delegated_user_ids = [r.delegated_to_user_id for r in already_delegated_responses]
    
    excluded_user_ids = all_primary_user_ids + already_delegated_user_ids
    
    substitute_users = User.query.filter(User.id.notin_(excluded_user_ids)).all()
    
    users_list = [{"id": user.id, "name": user.full_name} for user in substitute_users]
    
    return jsonify({
        "response_id": response.id,
        "primary_user_name": response.primary_user.full_name,
        "ot_date": response.schedule.ot_date.strftime('%Y-%m-%d'),
        "other_users": users_list
    })

# (Endpoint /submit-ot-response เหมือนเดิม)

@app.route('/submit-ot-response', methods=['POST'])
def submit_ot_response():
    data = request.json
    try:
        response = OTResponse.query.get(data['response_id'])
        if not response:
            return jsonify({"error": "ไม่พบการตอบรับนี้"}), 404
        
        if response.response_status != 'pending':
            return jsonify({"error": f"คุณได้ตอบแบบสำรวจนี้ไปแล้ว (สถานะ: {response.response_status})"}), 400

        primary_user_name = response.primary_user.full_name
        ot_date_str = response.schedule.ot_date.strftime('%d/%m/%Y') 
        
        status = data.get('status')
        
        if status == 'confirmed':
            response.response_status = 'confirmed'
            response.delegated_to_user_id = None
            response.let_admin_decide = False
        
        elif status == 'declined':
            response.response_status = 'declined'
            message_to_group = "" 
            
            if data.get('let_admin_decide'):
                response.let_admin_decide = True
                response.delegated_to_user_id = None
                message_to_group = (
                    f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
                    f"พนักงาน: คุณ {primary_user_name}\n"
                    f"สถานะ: ❌ สละสิทธิ์ (ให้ Admin เลือกแทน)"
                )
                
            elif data.get('delegated_to_id'):
                delegated_id = data.get('delegated_to_id')
                current_schedule_id = response.schedule_id
                existing_delegation = OTResponse.query.filter(
                    OTResponse.schedule_id == current_schedule_id,
                    OTResponse.delegated_to_user_id == delegated_id
                ).first() 

                if existing_delegation:
                    substitute_user = User.query.get(delegated_id)
                    sub_name = substitute_user.full_name if substitute_user else "คนนี้"
                    return jsonify({"error": f"เลือกตัวแทนซ้ำ! ({sub_name} ถูกเลือกไปแล้วโดยคนอื่น)"}), 400

                response.delegated_to_user_id = delegated_id
                response.let_admin_decide = False
                
                substitute_user = User.query.get(delegated_id)
                substitute_name = substitute_user.full_name if substitute_user else "(ไม่พบชื่อ)"
                
                message_to_group = (
                    f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
                    f"พนักงาน: คุณ {primary_user_name}\n"
                    f"สถานะ: ❌ สละสิทธิ์ (มอบสิทธิ์ให้ ➡️ {substitute_name})"
                )
            
            if message_to_group:
                send_line_push_message(message_to_group)
            
        db.session.commit()
        return jsonify({"message": "บันทึกผลสำเร็จ!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- (ส่วนของ Admin) ---

# <<< (ใหม่) หน้าสำหรับสร้างตาราง OT >>>
@app.route('/admin/create')
def admin_create_page():
    all_users = User.query.order_by(User.full_name).all()
    return render_template('create_schedule.html', users=all_users)

# <<< (ใหม่) API สำหรับรับข้อมูลการสร้างตาราง OT >>>
@app.route('/api/create-schedule', methods=['POST'])
def create_schedule():
    data = request.json
    ot_date_str = data.get('date')
    primary_user_ids = data.get('user_ids', [])

    if not ot_date_str or not primary_user_ids:
        return jsonify({"error": "กรุณาเลือกวันที่และพนักงานอย่างน้อย 1 คน"}), 400

    try:
        ot_date = datetime.strptime(ot_date_str, '%Y-%m-%d').date()

        # ตรวจสอบว่าวันที่นี้ถูกสร้างไปแล้วหรือยัง
        existing_schedule = OTSchedule.query.filter_by(ot_date=ot_date).first()
        if existing_schedule:
            return jsonify({"error": f"มีตาราง OT สำหรับวันที่ {ot_date_str} อยู่แล้ว"}), 400

        # 1. สร้าง Schedule
        new_schedule = OTSchedule(ot_date=ot_date)
        db.session.add(new_schedule)
        db.session.commit() # Commit เพื่อให้ได้ new_schedule.id

        # 2. สร้าง OTResponse สำหรับแต่ละคนที่ถูกเลือก
        created_responses = []
        user_map = {u.id: u.full_name for u in User.query.filter(User.id.in_(primary_user_ids)).all()}
        
        for user_id in primary_user_ids:
            response = OTResponse(schedule_id=new_schedule.id, primary_user_id=user_id)
            db.session.add(response)
            created_responses.append(response)
        
        db.session.commit() # Commit responses ทั้งหมด

        # 3. เตรียมข้อมูลลิงก์เพื่อส่งกลับให้ Admin
        links_for_admin = []
        for resp in created_responses:
            user_name = user_map.get(resp.primary_user_id, "(ไม่พบชื่อ)")
            links_for_admin.append({
                "name": user_name,
                "link": url_for('show_survey', token=resp.token) # สร้าง URL ให้
            })

        # 4. (Optional) ส่งข้อความแจ้งเตือนเข้ากลุ่ม LINE
        names_list = "\n".join([f"- {name}" for name in user_map.values()])
        message_to_group = (
            f"📢 สร้างตาราง OT ใหม่ 📢\n"
            f"วันที่: {ot_date.strftime('%d/%m/%Y')}\n\n"
            f"ผู้มีสิทธิ์หลัก:\n{names_list}\n\n"
            f"ระบบจะส่งลิงก์สำรวจให้ Admin เพื่อแจกจ่ายต่อไป"
        )
        send_line_push_message(message_to_group)
        
        return jsonify({
            "message": "สร้างตาราง OT สำเร็จ!",
            "links": links_for_admin,
            "schedule_id": new_schedule.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# <<< (แก้ไข) หน้า Dashboard หลักของ Admin >>>
@app.route('/admin')
def admin_dashboard():
    # ดึงตาราง OT ทั้งหมด เรียงจากใหม่ไปเก่า
    all_schedules = OTSchedule.query.order_by(OTSchedule.ot_date.desc()).all()
    
    # ตรวจสอบว่า User ขอ Schedule ID ไหนมา (จาก query string)
    schedule_id_to_show = request.args.get('schedule_id', type=int)
    
    selected_schedule = None
    
    if schedule_id_to_show:
        # ถ้าขอมา ให้ query อันนั้น
        selected_schedule = OTSchedule.query.get(schedule_id_to_show)
    elif all_schedules:
        # ถ้าไม่ได้ขอมา (เข้าหน้า /admin เฉยๆ) ให้แสดงอันล่าสุด
        selected_schedule = all_schedules[0] 
    
    # เตรียมข้อมูล responses ถ้ามี schedule ที่เลือก
    responses = []
    if selected_schedule:
        responses = selected_schedule.responses

    return render_template('admin.html', 
                           all_schedules=all_schedules,       # ส่งตารางทั้งหมดไปให้ Dropdown
                           selected_schedule=selected_schedule, # ส่งตารางที่เลือก
                           responses=responses                  # ส่ง responses ของตารางที่เลือก
                          )

# <<< (แก้ไข) หน้า /setup-demo จะเหลือแค่สร้าง User เท่านั้น >>>
@app.route('/setup-demo')
def setup_demo():
    try:
        # ลบข้อมูลเก่าทั้งหมด
        db.session.query(OTResponse).delete()
        db.session.query(OTSchedule).delete()
        db.session.query(User).delete()
        db.session.commit()
        
        # สร้าง User 5 คน
        user_a = User(username='a', full_name='นายประทวน มงคลศิลป์')
        user_b = User(username='b', full_name='นายสุธี แซ่อึ้ง')
        user_c = User(username='c', full_name='นายพลวัต รัตนภักดี')
        user_d = User(username='d', full_name='นายนิติธร สุขหิรัญ')
        user_e = User(username='e', full_name='นายอนุพงษ์ อิงสันเทียะ')
        db.session.add_all([user_a, user_b, user_c, user_d, user_e]) 
        db.session.commit()
        
        return f"""
        <h1>สร้างข้อมูลพนักงาน 5 คนสำเร็จ!</h1>
        <p>ลบข้อมูลตาราง OT เก่าทั้งหมด และสร้างรายชื่อพนักงาน 5 คนเรียบร้อยแล้ว</p>
        <hr>
        <p><b>ขั้นตอนต่อไป:</b> <a href='/admin/create'>ไปที่หน้าสร้างตาราง OT</a></p>
        <p><b>หรือไปที่หน้า Dashboard หลัก:</b> <a href='/admin'>/admin</a></p>
        """
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาด: {e}"


# --- 4. ส่วนสำหรับรัน Server ---
if __name__ == '__main__':
    with app.app_context(): 
        db.create_all()
    app.run(debug=True, port=5000)