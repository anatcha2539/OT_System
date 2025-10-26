import os
import uuid
# FIX 2.1: เพิ่ม redirect, abort ไว้ที่ import หลัก
# นี่คือโค้ดที่ถูกต้อง

import calendar
from flask import Flask, request, jsonify, render_template, url_for, redirect, abort, flash
from sqlalchemy import func, extract, and_
from datetime import datetime, date

# --- (ใหม่) 1. Import Library ของ Flask-Login และการเข้ารหัส ---
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, flash
# --- 1. Import Library ของ LINE Bot SDK ---
# (ใช้ v3 สำหรับ Webhook)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage as V3TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
# (ใช้ v1/v2 สำหรับ Push Message - โค้ดเดิมของคุณ)
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError


# --- 1. ตั้งค่าพื้นฐาน ---
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

# FIX 3.1: ใช้ Environment Variable สำหรับ DATABASE_URL
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- (ใหม่) 2. ตั้งค่า Flask-Login ---
# (สำคัญมาก) เราจะใช้ Environment Variable ตัวใหม่สำหรับ Secret Key
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') 

login_manager = LoginManager()
login_manager.init_app(app)
# ถ้า user พยายามเข้าหน้า /admin แต่ยังไม่ login ให้เด้งไปที่ route (function) ชื่อ 'login'
login_manager.login_view = 'login' 
login_manager.login_message = "กรุณาเข้าสู่ระบบเพื่อใช้งานหน้านี้"
login_manager.login_message_category = "warning" # (ใช้กับ Bootstrap)

@login_manager.user_loader
def load_user(user_id):
    # Flask-Login จะใช้ฟังก์ชันนี้ดึงข้อมูล user จาก ID ที่เก็บใน session
    return User.query.get(int(user_id))
# --- (สิ้นสุดส่วนที่เพิ่มใหม่) ---


# FIX 1: ย้าย db.create_all() มาไว้ตรงนี้
with app.app_context():
    db.create_all()

# FIX 3.2: ใช้ Environment Variables สำหรับ LINE Tokens
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
YOUR_TARGET_GROUP_ID = os.environ.get('LINE_TARGET_GROUP_ID')
# (ใหม่) เพิ่ม Channel Secret และ Handler สำหรับ Webhook
YOUR_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
handler = WebhookHandler(YOUR_CHANNEL_SECRET)
# ===================================================

# --- 1.2 สร้าง Instance ของ LineBotApi (v1/v2) ---
try:
    line_bot_api = LineBotApi(YOUR_CHANNEL_ACCESS_TOKEN)
except Exception as e:
    print(f"!!! Error initializing LineBotApi (v1): {e}")
    line_bot_api = None

# --- 1.5 ฟังก์ชันสำหรับส่ง LINE (Messaging API - v1/v2) ---
def send_line_push_message(message_text):
    if not line_bot_api:
        print("ไม่สามารถส่ง LINE ได้: LineBotApi (v1) ไม่ได้ถูกตั้งค่า")
        return False
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
        print(f"เกิดข้อผิดพลาดในการส่ง LINE (v1): {e}")
        return False

# --- (ใหม่) 1.6 Webhook สำหรับ "รับ" ข้อความจาก LINE (v3) ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    return 'OK'

# --- 2. สร้างโมเดลฐานข้อมูล ---

# (ใหม่) อัปเกรด User Model ให้รองรับการ Login
class User(db.Model, UserMixin): # (1. เพิ่ม UserMixin)
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    line_user_id = db.Column(db.String(100), nullable=True, unique=True, index=True)
    
    # --- (ส่วนที่เพิ่มใหม่) ---
    password_hash = db.Column(db.String(256), nullable=True) # (2. เพิ่ม hash รหัสผ่าน)
    is_admin = db.Column(db.Boolean, default=False)        # (3. เพิ่มสถานะ Admin)

    # (4. ฟังก์ชันสำหรับตั้งรหัสผ่าน)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # (5. ฟังก์ชันสำหรับเช็กรหัสผ่าน)
    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    # --- (สิ้นสุดส่วนที่เพิ่มใหม่) ---

    def __repr__(self):
        return f'<User {self.full_name}>'
User_sub = db.aliased(User, name='user_sub')

# (Class OTSchedule และ OTResponse เหมือนเดิม ไม่ต้องแก้)
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
    # (อัปเกรด) ถ้า login แล้ว ให้ไป dashboard, ถ้ายัง ให้ไป login
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login'))

# --- (ใหม่) 3.1 สร้าง Route สำหรับ Login / Logout ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.is_admin and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('login.html', error="Username หรือ Password ไม่ถูกต้อง (หรือคุณไม่ใช่ Admin)")

    return render_template('login.html')

@app.route('/logout')
@login_required 
def logout():
    logout_user()
    return redirect(url_for('login'))

# #(สำคัญ!) Route ลับสำหรับ "สร้าง Admin คนแรก"
# @app.route('/admin/create-first-admin')
# def create_first_admin():
#     try:
# #@app.route('/admin/create-first-admin')
# #def create_first_admin():
# #    try:
#         admin_user = User.query.filter_by(username='admin').first()
#         if not admin_user:
#             admin_user = User(
#                 username='admin', 
#                 full_name='ผู้ดูแลระบบ', 
#                 is_admin=True
#             )
#             admin_user.set_password('password123') 
#             db.session.add(admin_user)
#             db.session.commit()
#             return "<h1>สร้าง Admin User (username: admin, pass: password123) สำเร็จ!</h1>"
#         else:
#             admin_user.set_password('password123')
#             admin_user.is_admin = True
#             db.session.commit()
#             return "<h1>มี User 'admin' อยู่แล้ว -> อัปเดตสิทธิ์และรีเซ็ตรหัสผ่านเป็น 'password123' สำเร็จ!</h1>"
#     except Exception as e:
#         db.session.rollback()
#         return f"เกิดข้อผิดพลาด: {e}"
# # --- (สิ้นสุดส่วน Login) ---


# --- 3.2 ส่วนของ Survey (User ทั่วไป ไม่ต้อง Login) ---
@app.route('/survey/<string:token>')
def show_survey(token):
    response = OTResponse.query.filter_by(token=token).first_or_404()
    return render_template('survey.html', 
                           response_id=response.id, 
                           user_name=response.primary_user.full_name,
                           ot_date=response.schedule.ot_date, 
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
        
# ... ในฟังก์ชัน submit_ot_response ...
        elif status == 'declined':
# response.response_status = 'declined' # (ลบบรรทัดนี้)
            message_to_group = ""  
            if data.get('let_admin_decide'):
                response.response_status = 'declined_admin' # (อัปเดตสถานะ)
                response.let_admin_decide = True
                response.delegated_to_user_id = None
                message_to_group = (
                    f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
                    f"พนักงาน: คุณ {primary_user_name}\n"
                    f"สถานะ: ❌ สละสิทธิ์ (ให้ Admin เลือกแทน)"
                )

            elif data.get('delegated_to_id'):
                delegated_id = data.get('delegated_to_id')
# ... (โค้ดเช็ก existing_delegation เหมือนเดิม) ...
# ...

                response.response_status = 'delegated' # (อัปเดตสถานะ)
                response.delegated_to_user_id = delegated_id
                response.let_admin_decide = False
                substitute_user = User.query.get(delegated_id)
                substitute_name = substitute_user.full_name if substitute_user else "(ไม่พบชื่อ)"

                message_to_group = (
                    f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
                    f"พนักงาน: คุณ {primary_user_name}\n"
                    f"สถานะ: ❌ สละสิทธิ์ (มอบสิทธิ์ให้ ➡️ {substitute_name})\n\n"
                    f"‼️ Admin: กรุณาติดต่อ {substitute_name} เพื่อยืนยันและกดปุ่มใน Dashboard"
                    )
# ... (โค้ดส่วนที่เหลือเหมือนเดิม) ...
        # elif status == 'declined':
            # response.response_status = 'declined'
            # message_to_group = "" 
            
            # if data.get('let_admin_decide'):
            #     response.let_admin_decide = True
            #     response.delegated_to_user_id = None
            #     message_to_group = (
            #         f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
            #         f"พนักงาน: คุณ {primary_user_name}\n"
            #         f"สถานะ: ❌ สละสิทธิ์ (ให้ Admin เลือกแทน)"
            #     )
                
            # elif data.get('delegated_to_id'):
            #     delegated_id = data.get('delegated_to_id')
            #     current_schedule_id = response.schedule_id
            #     existing_delegation = OTResponse.query.filter(
            #         OTResponse.schedule_id == current_schedule_id,
            #         OTResponse.delegated_to_user_id == delegated_id
            #     ).first() 

            #     if existing_delegation:
            #         substitute_user = User.query.get(delegated_id)
            #         sub_name = substitute_user.full_name if substitute_user else "คนนี้"
            #         return jsonify({"error": f"เลือกตัวแทนซ้ำ! ({sub_name} ถูกเลือกไปแล้วโดยคนอื่น)"}), 400

            #     response.delegated_to_user_id = delegated_id
            #     response.let_admin_decide = False
                
            #     substitute_user = User.query.get(delegated_id)
            #     substitute_name = substitute_user.full_name if substitute_user else "(ไม่พบชื่อ)"
                
            #     message_to_group = (
            #         f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
            #         f"พนักงาน: คุณ {primary_user_name}\n"
            #         f"สถานะ: ❌ สละสิทธิ์ (มอบสิทธิ์ให้ ➡️ {substitute_name})"
            #     )
            
            if message_to_group:
                send_line_push_message(message_to_group)
            
        db.session.commit()
        return jsonify({"message": "บันทึกผลสำเร็จ!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# --- 3.3 ส่วนของ Admin (ต้อง Login) ---

# @app.route('/admin/force-create-tables')
# @login_required
# def force_create_tables():
#     if not current_user.is_admin: abort(403)
#     try:
# #@app.route('/admin/force-create-tables')
# #def force_create_tables():
# #    try:
#         db.drop_all()
#         db.create_all()
#         return "Tables dropped and recreated successfully! (Schema is updated)"
#     except Exception as e:
#         return f"An error occurred: {str(e)}"

@app.route('/admin/users')
@login_required
def admin_users_page():
    if not current_user.is_admin: abort(403)
    try:
        # (อัปเกรด) ดึง user ทั้งหมด แต่ไม่แสดง "ผู้ดูแลระบบ" (admin)
        all_users = User.query.filter(User.is_admin == False).order_by(User.full_name).all()
        return render_template('admin_users.html', users=all_users)
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการโหลดข้อมูลผู้ใช้: {str(e)}"

@app.route('/admin/add-user', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin: abort(403)
    try:
        username = request.form['username']
        full_name = request.form['full_name']
        line_user_id = request.form.get('line_user_id', None) 

        if line_user_id and line_user_id.strip() != "":
            existing_line_id = User.query.filter_by(line_user_id=line_user_id).first()
            if existing_line_id:
                return f"เกิดข้อผิดพลาด: LINE User ID ({line_user_id}) นี้มีผู้ใช้งานแล้ว"
        else:
            line_user_id = None 

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "เกิดข้อผิดพลาด: Username นี้มีผู้ใช้งานแล้ว"

        new_user = User(
            username=username, 
            full_name=full_name, 
            line_user_id=line_user_id,
            is_admin=False # (ใหม่) พนักงานที่เพิ่มใหม่จะเป็น Non-Admin เสมอ
        )
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('admin_users_page'))
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาด: {str(e)}"
    
@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin: abort(403)
    try:
        has_responses = OTResponse.query.filter(
            (OTResponse.primary_user_id == user_id) | 
            (OTResponse.delegated_to_user_id == user_id)
        ).first()
        
        if has_responses:
            return "ไม่สามารถลบผู้ใช้นี้ได้: ผู้ใช้มีข้อมูลผูกพันอยู่ในตาราง OT ที่สร้างไปแล้ว"

        user = User.query.get_or_404(user_id)
        
        # (ใหม่) ป้องกันการลบ Admin Account
        if user.is_admin:
            return "ไม่สามารถลบผู้ดูแลระบบได้"
            
        db.session.delete(user)
        db.session.commit()
        
        return redirect(url_for('admin_users_page'))
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาด: {str(e)}"

@app.route('/admin/edit-user/<int:user_id>', methods=['POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin: abort(403)
    try:
        data = request.json
        new_full_name = data.get('full_name')
        new_line_user_id = data.get('line_user_id') 

        user = User.query.get_or_404(user_id)

        if not new_full_name:
            return jsonify({"error": "ไม่พบชื่อใหม่"}), 400

        user.full_name = new_full_name

        if new_line_user_id and new_line_user_id.strip() != "":
            existing_line_id = User.query.filter(
                User.line_user_id == new_line_user_id,
                User.id != user_id 
            ).first()
            if existing_line_id:
                return jsonify({"error": f"LINE User ID ({new_line_user_id}) นี้ ถูกใช้โดยผู้ใช้อื่นแล้ว"}), 400
            user.line_user_id = new_line_user_id
        else:
            user.line_user_id = None

        db.session.commit()
        return jsonify({"message": "success"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
@app.route('/admin/delete-schedule/<int:schedule_id>', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    if not current_user.is_admin: abort(403)
    try:
        schedule = OTSchedule.query.get_or_404(schedule_id)
        OTResponse.query.filter_by(schedule_id=schedule_id).delete()
        db.session.delete(schedule)
        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาดในการลบตาราง: {str(e)}"


@app.route('/admin/create')
@login_required
def admin_create_page():
    if not current_user.is_admin: abort(403)
    # (อัปเกรด) ดึงเฉพาะ User ที่ไม่ใช่ Admin มาให้เลือก
    all_users = User.query.filter_by(is_admin=False).order_by(User.full_name).all()
    return render_template('create_schedule.html', users=all_users)

@app.route('/api/create-schedule', methods=['POST'])
@login_required
def create_schedule():
    if not current_user.is_admin: abort(403)
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
        selected_users = User.query.filter(User.id.in_(primary_user_ids)).all()
        user_map = {u.id: u for u in selected_users} 

        for user_id in primary_user_ids:
            response = OTResponse(schedule_id=new_schedule.id, primary_user_id=user_id)
            db.session.add(response)
            created_responses.append(response)

        db.session.commit() 

        links_for_admin_fallback = [] 
        names_list_for_group = [] 
        users_sent_count = 0

        for resp in created_responses:
            user = user_map.get(resp.primary_user_id)
            if not user:
                continue 

            names_list_for_group.append(f"- {user.full_name}")
            survey_link = url_for('show_survey', token=resp.token, _external=True)

            if user.line_user_id:
                try:
                    message_text = (
                        f"สวัสดีครับ คุณ {user.full_name},\n\n"
                        f"คุณได้รับสิทธิ์ OT สำหรับวันที่ {ot_date.strftime('%d/%m/%Y')}\n"
                        f"กรุณากดยืนยัน/สละสิทธิ์ ภายในลิงก์นี้:\n\n"
                        f"{survey_link}"
                    )
                    # (ใช้ v1/v2 API สำหรับส่ง Push Message)
                    message = TextSendMessage(text=message_text)
                    line_bot_api.push_message(user.line_user_id, messages=message)
                    users_sent_count += 1
                except Exception as e:
                    print(f"!!! ส่ง LINE หา {user.full_name} ({user.line_user_id}) ไม่สำเร็จ: {e}")
                    links_for_admin_fallback.append({
                        "name": f"{user.full_name} (ส่ง LINE ไม่สำเร็จ)",
                        "link": survey_link
                    })
            else:
                links_for_admin_fallback.append({
                    "name": f"{user.full_name} (ไม่มี LINE ID)",
                    "link": survey_link
                })

        names_list_str = "\n".join(names_list_for_group)
        message_to_group = (
            f"📢 สร้างตาราง OT ใหม่ 📢\n"
            f"วันที่: {ot_date.strftime('%d/%m/%Y')}\n\n"
            f"ผู้มีสิทธิ์หลัก:\n{names_list_str}\n\n"
            f"✅ ระบบได้ส่งลิงก์ Survey ให้พนักงานแล้ว {users_sent_count} คน"
        )
        if links_for_admin_fallback:
            message_to_group += f"\n\n🚨 ({current_user.full_name} โปรดแจกจ่ายลิงก์ที่เหลือเอง)"

        send_line_push_message(message_to_group)

        return jsonify({
            "message": "สร้างตาราง OT สำเร็จ!",
            "links": links_for_admin_fallback,
            "schedule_id": new_schedule.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    

# (ต้อง import flash ไว้ข้างบนด้วย)
# from flask import Flask, ..., flash

@app.route('/admin/substitute/confirm/<int:response_id>', methods=['POST'])
@login_required
def confirm_substitute(response_id):
    if not current_user.is_admin: abort(403)
    response = OTResponse.query.get_or_404(response_id)
    
    # ถ้าไม่มีตัวแทน หรือสถานะไม่ถูกต้อง
    if not response.delegated_user or response.response_status not in ['delegated', 'sub_declined']:
        flash("ไม่สามารถยืนยันตัวแทนได้ (สถานะไม่ถูกต้อง)", "danger")
        return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))
        
    response.response_status = 'sub_confirmed'
    db.session.commit()

    # แจ้งเตือนกลุ่มว่า "ยืนยัน" แล้ว
    ot_date_str = response.schedule.ot_date.strftime('%d/%m/%Y')
    message_to_group = (
        f"✅ ยืนยันตัวแทน OT ({ot_date_str}) ✅\n"
        f"ผู้สละสิทธิ์: คุณ {response.primary_user.full_name}\n"
        f"ตัวแทน: คุณ {response.delegated_user.full_name} (ยืนยันมาแน่นอน)"
    )
    send_line_push_message(message_to_group)
    flash("ยืนยันตัวแทนเรียบร้อยแล้ว", "success")
    
    return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))


@app.route('/admin/substitute/reject/<int:response_id>', methods=['POST'])
@login_required
def reject_substitute(response_id):
    if not current_user.is_admin: abort(403)
    response = OTResponse.query.get_or_404(response_id)

    if not response.delegated_user or response.response_status not in ['delegated', 'sub_confirmed']:
        flash("ไม่สามารถปฏิเสธตัวแทนได้ (สถานะไม่ถูกต้อง)", "danger")
        return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))

    response.response_status = 'sub_declined'
    response.let_admin_decide = True # (สำคัญ) คืนสิทธิ์การตัดสินใจให้ Admin
    db.session.commit()

    # แจ้งเตือนกลุ่มว่า "ตัวแทนไม่มา"
    ot_date_str = response.schedule.ot_date.strftime('%d/%m/%Y')
    message_to_group = (
        f"🚨 ตัวแทน OT ปฏิเสธ ({ot_date_str}) 🚨\n"
        f"ผู้สละสิทธิ์: คุณ {response.primary_user.full_name}\n"
        f"ตัวแทน: คุณ {response.delegated_user.full_name} (ไม่สามารถมาได้)\n\n"
        f"‼️ Admin: กรุณาหาคนใหม่แทน"
    )
    send_line_push_message(message_to_group)
    flash("ปฏิเสธตัวแทนแล้ว (ระบบจะคืนสถานะให้ Admin เลือกคนใหม่)", "warning")
    
    return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))

# (วางโค้ดนี้ไว้ก่อน @app.route('/admin') )

@app.route('/admin/assign-substitute/<int:response_id>', methods=['POST'])
@login_required
def assign_substitute(response_id):
    if not current_user.is_admin: abort(403)
    response = OTResponse.query.get_or_404(response_id)
    
    # ตรวจสอบว่าสถานะถูกต้อง (คือ Admin ต้องเลือก)
    if response.response_status not in ['declined_admin', 'sub_declined']:
        flash("ไม่สามารถมอบหมายได้ (สถานะไม่ถูกต้อง)", "danger")
        return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))
        
    try:
        sub_user_id = int(request.form['user_id'])
        sub_user = User.query.get(sub_user_id)
        
        if not sub_user:
             flash("ไม่พบพนักงานที่เลือก", "danger")
             return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))

        # (สำคัญ) ตรวจสอบอีกครั้งว่า User ที่เลือกมา "ว่าง" จริงๆ
        # (กัน Admin 2 คนเลือกชนกัน)
        existing_assignment = OTResponse.query.filter(
            OTResponse.schedule_id == response.schedule_id,
            (OTResponse.delegated_to_user_id == sub_user_id) & 
            (OTResponse.response_status.in_(['delegated', 'sub_confirmed']))
        ).first()
        
        if existing_assignment:
            flash(f"เลือกตัวแทนซ้ำ! ({sub_user.full_name} ถูกเลือกไปแล้ว)", "danger")
            return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))

        # --- อัปเดตสถานะ ---
        response.delegated_to_user_id = sub_user_id
        response.response_status = 'sub_confirmed' # ยืนยันเลย (เพราะ Admin เป็นคนเลือกเอง)
        response.let_admin_decide = False
        db.session.commit()
        
        # --- แจ้งเตือน LINE ---
        ot_date_str = response.schedule.ot_date.strftime('%d/%m/%Y')
        message_to_group = (
            f"✅ Admin มอบหมาย OT ({ot_date_str}) ✅\n"
            f"จาก: คุณ {response.primary_user.full_name} (สละสิทธิ์)\n"
            f"มอบหมายให้: คุณ {sub_user.full_name} (ยืนยันมาแน่นอน)\n"
            f"(Admin: {current_user.full_name})"
        )
        send_line_push_message(message_to_group)
        flash(f"มอบหมายให้ {sub_user.full_name} เรียบร้อยแล้ว", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "danger")

    return redirect(url_for('admin_dashboard', schedule_id=response.schedule_id))

@app.route('/admin/reports')
@login_required
def admin_reports():
    if not current_user.is_admin: abort(403)

    # --- 1. ตั้งค่าตัวกรอง (Filters) ---
    today = date.today()
    current_year = today.year
    current_month = today.month
    current_week = today.isocalendar()[1] # [1] คือ week number

    try:
        selected_year = int(request.args.get('year', current_year))
        selected_month = int(request.args.get('month', current_month))
        selected_week = int(request.args.get('week', current_week))
    except ValueError:
        flash("ค่าตัวกรองไม่ถูกต้อง", "danger")
        selected_year = current_year
        selected_month = current_month
        selected_week = current_week

    # --- 2. Logic สรุปผลรายเดือน ---
    # เราจะค้นหา OT ทั้งหมดที่ "ยืนยัน" (confirmed) หรือ "ตัวแทนยืนยัน" (sub_confirmed)
    monthly_responses = db.session.query(
        OTResponse, OTSchedule, 
        User.full_name.label('primary_name'),
        User_sub.full_name.label('sub_name')
    ).join(
        OTSchedule, OTResponse.schedule_id == OTSchedule.id
    ).join(
        User, OTResponse.primary_user_id == User.id
    ).outerjoin( # ใช้ outerjoin เพราะตัวแทนอาจจะยังไม่มี (เป็น None)
        User_sub, OTResponse.delegated_to_user_id == User_sub.id
    ).filter(
        extract('year', OTSchedule.ot_date) == selected_year,
        extract('month', OTSchedule.ot_date) == selected_month,
        OTResponse.response_status.in_(['confirmed', 'sub_confirmed'])
    ).order_by(OTSchedule.ot_date.asc()).all()

    # จัดกลุ่มข้อมูลใหม่ ให้ "User" เป็นศูนย์กลาง
    monthly_summary = {}
    for resp, schedule, primary_name, sub_name in monthly_responses:
        user_name = ""
        
        if resp.response_status == 'confirmed':
            user_name = primary_name
        elif resp.response_status == 'sub_confirmed':
            user_name = sub_name # (ถ้า sub_name เป็น None แสดงว่ามีบางอย่างผิดพลาด)
        
        if user_name:
            if user_name not in monthly_summary:
                monthly_summary[user_name] = {'name': user_name, 'dates': []}
            monthly_summary[user_name]['dates'].append(schedule.ot_date)
    
    # เรียงลำดับ (Sort) จากคนที่มา OT เยอะสุด
    sorted_monthly_summary = sorted(monthly_summary.values(), key=lambda item: len(item['dates']), reverse=True)


    # --- 3. Logic สรุปผลรายสัปดาห์ ---
    weekly_responses = db.session.query(
        OTResponse, OTSchedule, 
        User.full_name.label('primary_name'),
        User_sub.full_name.label('sub_name')
    ).join(
        OTSchedule, OTResponse.schedule_id == OTSchedule.id
    ).join(
        User, OTResponse.primary_user_id == User.id
    ).outerjoin(
        User_sub, OTResponse.delegated_to_user_id == User_sub.id
    ).filter(
        extract('year', OTSchedule.ot_date) == selected_year,
        extract('week', OTSchedule.ot_date) == selected_week, # (ISO Week number)
        OTResponse.response_status.in_(['confirmed', 'sub_confirmed'])
    ).order_by(OTSchedule.ot_date.asc()).all()
    
    # จัดกลุ่มข้อมูลรายสัปดาห์
    weekly_summary = {}
    for resp, schedule, primary_name, sub_name in weekly_responses:
        user_name = ""
        if resp.response_status == 'confirmed':
            user_name = primary_name
        elif resp.response_status == 'sub_confirmed':
            user_name = sub_name
        
        if user_name:
            if user_name not in weekly_summary:
                weekly_summary[user_name] = {'name': user_name, 'dates': []}
            weekly_summary[user_name]['dates'].append(schedule.ot_date)
    
    sorted_weekly_summary = sorted(weekly_summary.values(), key=lambda item: len(item['dates']), reverse=True)


    # --- 4. ส่งข้อมูลไปที่ Template ---
    
    # สร้าง List ปี (ย้อนหลัง) สำหรับ Dropdown
    first_schedule = OTSchedule.query.order_by(OTSchedule.ot_date.asc()).first()
    start_year = first_schedule.ot_date.year if first_schedule else current_year
    available_years = list(range(start_year, current_year + 2)) # (เผื่ออนาคต 1 ปี)
    
    # สร้าง List เดือน สำหรับ Dropdown
    month_names = [(i, calendar.month_name[i]) for i in range(1, 13)]
    
    # สร้าง String สัปดาห์ (เช่น "20/10 - 26/10/2025")
    try:
        # ใช้วันจันทร์ (1) เป็นวันเริ่มสัปดาห์
        week_start = datetime.strptime(f'{selected_year}-W{selected_week}-1', "%Y-W%W-%w").date()
        # ใช้วันอาทิตย์ (0) เป็นวันจบสัปดาห์
        week_end = datetime.strptime(f'{selected_year}-W{selected_week}-0', "%Y-W%W-%w").date()
        week_range_str = f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m/%Y')}"
    except ValueError:
        week_range_str = f"(สัปดาห์ที่ {selected_week})"


    return render_template('reports.html',
                           selected_year=selected_year,
                           selected_month=selected_month,
                           selected_week=selected_week,
                           available_years=available_years,
                           month_names=month_names,
                           current_month_name=calendar.month_name[selected_month],
                           week_range_str=week_range_str,
                           sorted_monthly_summary=sorted_monthly_summary,
                           sorted_weekly_summary=sorted_weekly_summary
                          )

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin: abort(403)
    
    all_schedules = OTSchedule.query.order_by(OTSchedule.ot_date.desc()).all()
    schedule_id_to_show = request.args.get('schedule_id', type=int)
    search_date_str = request.args.get('search_date') 
    
    selected_schedule = None
    error_message = None 
    responses = []
    available_substitutes = [] # (ใหม่) สร้างตัวแปรว่างไว้ก่อน

    try:
        if schedule_id_to_show:
            selected_schedule = OTSchedule.query.get(schedule_id_to_show)
        
        elif search_date_str:
            search_date = datetime.strptime(search_date_str, '%Y-%m-%d').date()
            selected_schedule = OTSchedule.query.filter_by(ot_date=search_date).first()
            if not selected_schedule:
                error_message = f"ไม่พบตาราง OT สำหรับวันที่ {search_date.strftime('%d/%m/%Y')}"
                
        elif all_schedules:
            selected_schedule = all_schedules[0] 
            
        
        # (ใหม่) เพิ่ม Logic นี้เข้าไปใน try...except
        if selected_schedule:
            responses = selected_schedule.responses
            
            # --- เริ่มส่วนที่เพิ่มใหม่ ---
            
            # 1. ค้นหา User ID ที่ "ไม่ว่าง" ทั้งหมดในตารางนี้
            
            # (กลุ่ม 1) คนที่มีสิทธิ์หลักในตารางนี้ (ทุกคน)
            all_primary_user_ids = [r.primary_user_id for r in responses]
            
            # (กลุ่ม 2) คนที่ถูกมอบสิทธิ์ และ "ยืนยันแล้ว" หรือ "กำลังรอ"
            all_delegated_user_ids = [
                r.delegated_to_user_id for r in responses 
                if r.delegated_to_user_id is not None and 
                   r.response_status in ['delegated', 'sub_confirmed']
            ]
            
            # รวม 2 กลุ่มนี้ คือคนที่ "ไม่ว่าง"
            excluded_user_ids = all_primary_user_ids + all_delegated_user_ids
            
            # 2. ค้นหา User ที่ "ว่าง"
            available_substitutes = User.query.filter(
                User.id.notin_(excluded_user_ids),
                User.is_admin == False # ไม่เอา Admin
            ).order_by(User.full_name).all()
            
            # --- จบส่วนที่เพิ่มใหม่ ---
            
    except ValueError:
        error_message = "รูปแบบวันที่ไม่ถูกต้อง (ต้องเป็น YYYY-MM-DD)"
    except Exception as e:
        error_message = f"เกิดข้อผิดพลาด: {str(e)}"

    # (อัปเกรด) ส่ง available_substitutes เพิ่มเข้าไป
    return render_template('admin.html', 
                           all_schedules=all_schedules,
                           selected_schedule=selected_schedule,
                           responses=responses,
                           available_substitutes=available_substitutes, # (ใหม่)
                           error_message=error_message,
                           search_date_str=search_date_str # (ใหม่) ส่งค่า search_date กลับไปด้วย
                           )

@app.route('/setup-demo')
@login_required
def setup_demo():
    if not current_user.is_admin: abort(403)
    try:
        db.session.query(OTResponse).delete()
        db.session.query(OTSchedule).delete()
        # (อัปเกรด) ลบเฉพาะ User ที่ไม่ใช่ Admin
        User.query.filter(User.is_admin == False).delete()
        db.session.commit()
        
        user_a = User(username='a', full_name='นายประทวน มงคลศิลป์')
        user_b = User(username='b', full_name='นายสุธี แซ่อึ้ง')
        user_c = User(username='c', full_name='นายพลวัต รัตนภักดี')
        user_d = User(username='d', full_name='นายนิติธร สุขหิรัญ')
        user_e = User(username='e', full_name='นายอนุพงษ์ อิงสันเทียะ')
        db.session.add_all([user_a, user_b, user_c, user_d, user_e]) 
        db.session.commit()
        
        return f"""
        <h1>สร้างข้อมูลพนักงาน 5 คนสำเร็จ!</h1>
        <p>ลบข้อมูลตาราง OT และพนักงานเก่าทั้งหมด (ยกเว้น Admin) และสร้างรายชื่อพนักงาน 5 คนเรียบร้อยแล้ว</p>
        <hr>
        <p><b>ขั้นตอนต่อไป:</b> <a href='/admin/create'>ไปที่หน้าสร้างตาราง OT</a></p>
        <p><b>หรือไปที่หน้า Dashboard หลัก:</b> <a href='/admin'>/admin</a></p>
        """
    except Exception as e:
        db.session.rollback()
        return f"เกิดข้อผิดพลาด: {e}"
    
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text
    reply_text = "" # ตัวแปรสำหรับเก็บข้อความตอบกลับ

    # --- 1. ตรวจสอบ Logic ---
    if text == "ดูตาราง OT ที่ยังไม่ตอบ":
        user = User.query.filter_by(line_user_id=user_id).first()

        if not user:
            reply_text = "ไม่พบข้อมูลของคุณในระบบ กรุณาติดต่อ Admin เพื่อลงทะเบียน LINE User ID ครับ"
        else:
            # (อัปเกรด) ค้นหา OT ที่ยังไม่ตอบ และ "ยังไม่ผ่านมา"
            pending_responses = db.session.query(OTResponse).join(OTSchedule).filter(
                OTResponse.primary_user_id == user.id,
                OTResponse.response_status == 'pending',
                OTSchedule.ot_date >= date.today() # เอาเฉพาะ OT ที่ยังไม่ผ่านมา
            ).order_by(OTSchedule.ot_date.asc()).all()

            if not pending_responses:
                reply_text = f"สวัสดีครับ คุณ {user.full_name}\n\nคุณไม่มียอด OT ค้างตอบครับ 👍"
            else:
                reply_text = f"สวัสดีครับ คุณ {user.full_name}\n\nคุณมี OT ที่ยังไม่ตอบ {len(pending_responses)} รายการ:\n\n"
                
                # (สำคัญ) ต้องใช้ app.app_context() 
                # เพื่อให้ url_for() ทำงานนอก Request ปกติของ Flask ได้
                with app.app_context():
                    for resp in pending_responses:
                        survey_link = url_for('show_survey', token=resp.token, _external=True)
                        reply_text += (
                            f"📅 วันที่: {resp.schedule.ot_date.strftime('%d/%m/%Y')}\n"
                            f"🔗 ลิงก์: {survey_link}\n\n"
                        )
                reply_text = reply_text.strip() # ลบ \n ตัวสุดท้าย

    else:
        # --- Logic เดิม: (ถ้าไม่ใช่คำสั่ง Rich Menu) ---
        # พิมพ์ Log สำหรับ Admin (เหมือนเดิม)
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! USER ID ที่คุณตามหาคือ: {user_id}")
        print(f"!!! เขาพิมพ์ว่า: {text}")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        # ตอบกลับ User ID (เหมือนเดิม)
        reply_text = f'นี่คือ User ID ของคุณ:\n{user_id}\n\nกรุณาคัดลอก ID นี้ไปให้ Admin ครับ'

    # --- 2. ส่งการตอบกลับ (ใช้โครงสร้าง v3 เดิมของคุณ) ---
    try:
        with ApiClient(Configuration(access_token=YOUR_CHANNEL_ACCESS_TOKEN)) as api_client:
            line_bot_api_v3 = MessagingApi(api_client)
            line_bot_api_v3.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[V3TextMessage(text=reply_text)]
                )
            )
    except Exception as e:
        print(f"!!! ไม่สามารถ 'ตอบกลับ' หา {user_id} ได้ (v3): {e}")



# --- 4. ส่วนสำหรับรัน Server ---
if __name__ == '__main__':
    app.run(debug=True, port=5000)