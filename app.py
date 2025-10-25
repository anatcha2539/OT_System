# app.py (เวอร์ชันแก้ไขสมบูรณ์ 25/10/2025)
import os
import uuid
# FIX 2.1: เพิ่ม redirect ไว้ที่ import หลัก
from flask import Flask, request, jsonify, render_template, url_for, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

# --- 1. Import Library ของ LINE Bot SDK ---
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# --- 1. ตั้งค่าพื้นฐาน ---
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

# FIX 3.1: ใช้ Environment Variable สำหรับ DATABASE_URL
# (โค้ดของคุณจะ "สะอาด" ไม่มีรหัสผ่าน)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# FIX 1: ย้าย db.create_all() มาไว้ตรงนี้
# (เพื่อให้ Gunicorn เรียกใช้งานตอนเริ่มเซิร์ฟเวอร์)
with app.app_context():
    db.create_all()

# FIX 3.2: ใช้ Environment Variables สำหรับ LINE Tokens
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
YOUR_TARGET_GROUP_ID = os.environ.get('LINE_TARGET_GROUP_ID')
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
    # (ปรับปรุงเล็กน้อย) เช็กว่ามี ID กลุ่มหรือไม่
    if not YOUR_TARGET_GROUP_ID:
        print("ไม่สามารถส่ง LINE ได้: กรุณาตั้งค่า LINE_TARGET_GROUP_ID")
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
# (ส่วนนี้ถูกต้องสมบูรณ์ ไม่มีการแก้ไข)
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

# FIX 2.2: วาง Route / (Homepage) ไว้ที่นี่
@app.route('/')
def index():
    # เมื่อคนเข้าหน้าหลัก ให้ส่งไปหน้า /admin อัตโนมัติ
    return redirect(url_for('admin_dashboard'))

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


# FIX 2.3: ลบส่วนที่ซ้ำซ้อน (import redirect, route /survey) ที่เคยอยู่ตรงนี้ออกไป

# <<< (ชั่วคราว) Route ลับสำหรับสร้างตาราง DB >>>
@app.route('/admin/force-create-tables')
def force_create_tables():
    try:
        db.create_all()
        return "Tables created successfully! You can remove this route now."
    except Exception as e:
        return f"An error occurred: {str(e)}"


# --- (ส่วนของ Admin) ---

# (ใหม่) หน้าสำหรับจัดการ User (แสดง, เพิ่ม, ลบ, แก้ไข)
@app.route('/admin/users')
def admin_users_page():
    try:
        all_users = User.query.order_by(User.full_name).all()
        return render_template('admin_users.html', users=all_users)
    except Exception as e:
        # นี่คือจุดที่เราจะเจอ Error "relation 'user' does not exist"
        # ถ้าตารางยังไม่ถูกสร้าง
        return f"เกิดข้อผิดพลาดในการโหลดข้อมูลผู้ใช้: {str(e)}"

# (ใหม่) API สำหรับเพิ่ม User
@app.route('/admin/add-user', methods=['POST'])
def add_user():
    try:
        username = request.form['username']
        full_name = request.form['full_name']
        
        # ตรวจสอบว่า username ซ้ำหรือไม่
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "เกิดข้อผิดพลาด: Username นี้มีผู้ใช้งานแล้ว"
            
        new_user = User(username=username, full_name=full_name)
        db.session.add(new_user)
        db.session.commit()
        
        return redirect(url_for('admin_users_page'))
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาด: {str(e)}"

# (ใหม่) API สำหรับลบ User
@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    try:
        # (สำคัญ) ตรวจสอบว่า User นี้ติดพันในตาราง OT หรือไม่
        has_responses = OTResponse.query.filter(
            (OTResponse.primary_user_id == user_id) | 
            (OTResponse.delegated_to_user_id == user_id)
        ).first()
        
        if has_responses:
            return "ไม่สามารถลบผู้ใช้นี้ได้: ผู้ใช้มีข้อมูลผูกพันอยู่ในตาราง OT ที่สร้างไปแล้ว"

        # ถ้าไม่ติดพัน ก็ลบได้
        user = User.query.get_or_404(user_id)
        db.session.delete(user)
        db.session.commit()
        
        return redirect(url_for('admin_users_page'))
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาด: {str(e)}"

# (ใหม่) API สำหรับแก้ไขชื่อ User (รับ JSON จาก JavaScript)
@app.route('/admin/edit-user/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    try:
        data = request.json
        new_full_name = data.get('full_name')

        if not new_full_name:
            return jsonify({"error": "ไม่พบชื่อใหม่"}), 400

        user = User.query.get_or_404(user_id)
        user.full_name = new_full_name
        db.session.commit()
        
        return jsonify({"message": "success"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500



# <<< (ใหม่) หน้าสำหรับสร้างตาราง OT >>>
# --- (ส่วนของ Admin) ---
# (ส่วนนี้ถูกต้องสมบูรณ์ ไม่มีการแก้ไข)

@app.route('/admin/create')
def admin_create_page():
    all_users = User.query.order_by(User.full_name).all()
    return render_template('create_schedule.html', users=all_users)

@app.route('/api/create-schedule', methods=['POST'])
def create_schedule():
    data = request.json
    ot_date_str = data.get('date')
    primary_user_ids = data.get('user_ids', [])

    if not ot_date_str or not primary_user_ids:
        return jsonify({"error": "กรุณาเลือกวันที่และพนักงานอย่างน้อย 1 คน"}), 400

    try:
        ot_date = datetime.strptime(ot_date_str, '%Y-%m-%d').date()

        existing_schedule = OTSchedule.query.filter_by(ot_date=ot_date).first()
        if existing_schedule:
            return jsonify({"error": f"มีตาราง OT สำหรับวันที่ {ot_date_str} อยู่แล้ว"}), 400

        new_schedule = OTSchedule(ot_date=ot_date)
        db.session.add(new_schedule)
        db.session.commit() 

        created_responses = []
        user_map = {u.id: u.full_name for u in User.query.filter(User.id.in_(primary_user_ids)).all()}
        
        for user_id in primary_user_ids:
            response = OTResponse(schedule_id=new_schedule.id, primary_user_id=user_id)
            db.session.add(response)
            created_responses.append(response)
        
        db.session.commit() 

        links_for_admin = []
        for resp in created_responses:
            user_name = user_map.get(resp.primary_user_id, "(ไม่พบชื่อ)")
            links_for_admin.append({
                "name": user_name,
                "link": url_for('show_survey', token=resp.token) 
            })

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

@app.route('/admin')
def admin_dashboard():
    all_schedules = OTSchedule.query.order_by(OTSchedule.ot_date.desc()).all()
    schedule_id_to_show = request.args.get('schedule_id', type=int)
    selected_schedule = None
    
    if schedule_id_to_show:
        selected_schedule = OTSchedule.query.get(schedule_id_to_show)
    elif all_schedules:
        selected_schedule = all_schedules[0] 
    
    responses = []
    if selected_schedule:
        responses = selected_schedule.responses

    return render_template('admin.html', 
                           all_schedules=all_schedules,      
                           selected_schedule=selected_schedule, 
                           responses=responses              
                          )

@app.route('/setup-demo')
def setup_demo():
    try:
        # ลบข้อมูลเก่าทั้งหมด (เรียงลำดับถูกต้อง)
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
    # FIX 1.2: ลบ db.create_all() ออกจากตรงนี้
    app.run(debug=True, port=5000)