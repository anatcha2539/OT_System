import os
import uuid
import calendar # <-- (V4) เพิ่ม
from flask import Flask, request, jsonify, render_template, url_for, redirect, abort, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract, and_ # <-- (V4) เพิ่ม
from datetime import datetime, date

# --- (ใหม่) 1. Import Library ของ Flask-Login และการเข้ารหัส ---
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

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
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "กรุณาเข้าสู่ระบบเพื่อใช้งานหน้านี้"
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
# --- (สิ้นสุดส่วนที่เพิ่มใหม่) ---


# FIX 1: ย้าย db.create_all() มาไว้ตรงนี้
with app.app_context():
    db.create_all()

# FIX 3.2: ใช้ Environment Variables สำหรับ LINE Tokens
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
YOUR_TARGET_GROUP_ID = os.environ.get('LINE_TARGET_GROUP_ID')
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

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    line_user_id = db.Column(db.String(100), nullable=True, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.full_name}>'

# <--- (V4) Alias สำหรับ User
User_sub = db.aliased(User, name='user_sub')

class OTSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ot_date = db.Column(db.Date, nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class OTResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    schedule_id = db.Column(db.Integer, db.ForeignKey('ot_schedule.id'), nullable=False)
    primary_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    response_status = db.Column(db.String(50), default='pending') # pending, confirmed, declined_admin, delegated, sub_confirmed, sub_declined
    delegated_to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    let_admin_decide = db.Column(db.Boolean, default=False)
    schedule = db.relationship('OTSchedule', backref=db.backref('responses', lazy=True, cascade="all, delete-orphan")) # Add cascade
    primary_user = db.relationship('User', foreign_keys=[primary_user_id])
    delegated_user = db.relationship('User', foreign_keys=[delegated_to_user_id])


# --- 3. สร้าง API Endpoints ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login'))

# --- 3.1 สร้าง Route สำหรับ Login / Logout ---

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
            flash("Username หรือ Password ไม่ถูกต้อง (หรือคุณไม่ใช่ Admin)", "danger")
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("ออกจากระบบสำเร็จ", "success")
    return redirect(url_for('login'))

#(สำคัญ!) Route ลับสำหรับ "สร้าง Admin คนแรก" - ควรคอมเมนต์ออกหลังใช้งาน
# @app.route('/admin/create-first-admin')
# def create_first_admin():
#     try:
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
#             # ถ้ามี user 'admin' อยู่แล้ว แค่อัปเดต password และ is_admin (ถ้าจำเป็น)
#             admin_user.set_password('password123')
#             admin_user.is_admin = True
#             db.session.commit()
#             return "<h1>มี User 'admin' อยู่แล้ว -> อัปเดตสิทธิ์และรีเซ็ตรหัสผ่านเป็น 'password123' สำเร็จ!</h1>"
#     except Exception as e:
#         db.session.rollback()
#         return f"เกิดข้อผิดพลาด: {e}"


# --- 3.2 ส่วนของ Survey (User ทั่วไป ไม่ต้อง Login) ---
@app.route('/survey/<string:token>')
def show_survey(token):
    response = OTResponse.query.filter_by(token=token).first_or_404()
    # ป้องกันการเข้าถึง survey ที่ตอบไปแล้วโดยตรง (อาจจะเพิ่มเงื่อนไขอื่นๆ เช่น วันที่ผ่านไปแล้ว)
    if response.response_status != 'pending':
         return render_template('survey_closed.html', status=response.response_status) # สร้าง template ใหม่
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
        OTResponse.delegated_to_user_id.isnot(None),
        OTResponse.response_status.in_(['delegated', 'sub_confirmed'])
    ).all()
    already_delegated_user_ids = [r.delegated_to_user_id for r in already_delegated_responses]

    excluded_user_ids = list(set(all_primary_user_ids + already_delegated_user_ids))

    # (แก้ไข V5) กรอง Admin ออก
    substitute_users = User.query.filter(
        User.id.notin_(excluded_user_ids),
        User.is_admin == False
    ).order_by(User.full_name).all()

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

        elif status == 'declined':
            message_to_group = ""

            if data.get('let_admin_decide'):
                response.response_status = 'declined_admin'
                response.let_admin_decide = True
                response.delegated_to_user_id = None
                message_to_group = (
                    f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
                    f"พนักงาน: คุณ {primary_user_name}\n"
                    f"สถานะ: ❌ สละสิทธิ์ (ให้ Admin เลือกแทน)"
                )

            elif data.get('delegated_to_id'):
                try:
                    delegated_id = int(data.get('delegated_to_id')) # Ensure it's an integer
                except (ValueError, TypeError):
                    return jsonify({"error": "ID ผู้รับมอบสิทธิ์ไม่ถูกต้อง"}), 400

                current_schedule_id = response.schedule_id

                existing_delegation = OTResponse.query.filter(
                    OTResponse.schedule_id == current_schedule_id,
                    OTResponse.delegated_to_user_id == delegated_id,
                    OTResponse.response_status.in_(['delegated', 'sub_confirmed'])
                ).first()

                if existing_delegation:
                    substitute_user = User.query.get(delegated_id)
                    sub_name = substitute_user.full_name if substitute_user else "คนนี้"
                    return jsonify({"error": f"เลือกตัวแทนซ้ำ! ({sub_name} ถูกเลือกไปแล้วโดยคนอื่น)"}), 400

                # Check if the delegated user exists
                substitute_user = User.query.get(delegated_id)
                if not substitute_user:
                     return jsonify({"error": f"ไม่พบข้อมูลผู้รับมอบสิทธิ์ (ID: {delegated_id})"}), 400

                response.response_status = 'delegated'
                response.delegated_to_user_id = delegated_id
                response.let_admin_decide = False
                substitute_name = substitute_user.full_name

                message_to_group = (
                    f"🚨 แจ้งเตือนสละสิทธิ์ OT ({ot_date_str}) 🚨\n"
                    f"พนักงาน: คุณ {primary_user_name}\n"
                    f"สถานะ: ❌ สละสิทธิ์ (มอบสิทธิ์ให้ ➡️ {substitute_name})\n\n"
                    f"‼️ Admin: กรุณาติดต่อ {substitute_name} เพื่อยืนยันและกดปุ่มใน Dashboard"
                )
            else:
                 return jsonify({"error": "กรุณาเลือกตัวเลือกในการสละสิทธิ์"}), 400

            if message_to_group:
                send_line_push_message(message_to_group)

        db.session.commit()
        return jsonify({"message": "บันทึกผลสำเร็จ!"}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in submit_ot_response: {e}")
        return jsonify({"error": str(e)}), 500


# --- 3.3 ส่วนของ Admin (ต้อง Login) ---

@app.route('/admin/users')
@login_required
def admin_users_page():
    if not current_user.is_admin: abort(403)
    try:
        all_users = User.query.filter(User.is_admin == False).order_by(User.full_name).all()
        return render_template('admin_users.html', users=all_users)
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการโหลดข้อมูลผู้ใช้: {str(e)}", "danger")
        return render_template('admin_users.html', users=[])

@app.route('/admin/add-user', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin: abort(403)
    try:
        username = request.form['username']
        full_name = request.form['full_name']
        line_user_id = request.form.get('line_user_id', None)

        if not username or not full_name:
             flash("กรุณากรอก Username และ ชื่อ-สกุล", "warning")
             return redirect(url_for('admin_users_page'))

        if line_user_id and line_user_id.strip() != "":
            line_user_id = line_user_id.strip() # Remove leading/trailing whitespace
            existing_line_id = User.query.filter_by(line_user_id=line_user_id).first()
            if existing_line_id:
                flash(f"เกิดข้อผิดพลาด: LINE User ID ({line_user_id}) นี้มีผู้ใช้งานแล้ว", "danger")
                return redirect(url_for('admin_users_page'))
        else:
            line_user_id = None

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("เกิดข้อผิดพลาด: Username นี้มีผู้ใช้งานแล้ว", "danger")
            return redirect(url_for('admin_users_page'))

        new_user = User(
            username=username,
            full_name=full_name,
            line_user_id=line_user_id,
            is_admin=False
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f"เพิ่มผู้ใช้ {full_name} สำเร็จ", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"เกิดข้อผิดพลาดในการเพิ่มผู้ใช้: {str(e)}", "danger")
    return redirect(url_for('admin_users_page'))

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin: abort(403)
    try:
        user = User.query.get_or_404(user_id)

        if user.is_admin:
            flash("ไม่สามารถลบผู้ดูแลระบบได้", "danger")
            return redirect(url_for('admin_users_page'))

        # Check dependencies more carefully
        has_primary_responses = OTResponse.query.filter_by(primary_user_id=user_id).first()
        has_delegated_responses = OTResponse.query.filter_by(delegated_to_user_id=user_id).first()

        if has_primary_responses or has_delegated_responses:
            flash("ไม่สามารถลบผู้ใช้นี้ได้: ผู้ใช้มีข้อมูลผูกพันอยู่ในตาราง OT ที่สร้างไปแล้ว (เป็นผู้มีสิทธิ์หลัก หรือ ผู้รับมอบสิทธิ์)", "danger")
            return redirect(url_for('admin_users_page'))

        db.session.delete(user)
        db.session.commit()
        flash(f"ลบผู้ใช้ {user.full_name} สำเร็จ", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"เกิดข้อผิดพลาดในการลบผู้ใช้: {str(e)}", "danger")
    return redirect(url_for('admin_users_page'))

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
            return jsonify({"error": "กรุณากรอก ชื่อ-สกุล"}), 400

        user.full_name = new_full_name.strip() # Ensure no extra whitespace

        if new_line_user_id and new_line_user_id.strip() != "":
            new_line_user_id = new_line_user_id.strip()
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
        return jsonify({"message": "success", "new_name": user.full_name, "new_line_id": user.line_user_id}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error editing user {user_id}: {e}")
        return jsonify({"error": f"เกิดข้อผิดพลาดในการแก้ไข: {str(e)}"}), 500

@app.route('/admin/delete-schedule/<int:schedule_id>', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    if not current_user.is_admin: abort(403)
    try:
        schedule = OTSchedule.query.get_or_404(schedule_id)
        # Cascade should handle deleting responses, but explicitly doing it might be safer
        # OTResponse.query.filter_by(schedule_id=schedule_id).delete()
        db.session.delete(schedule)
        db.session.commit()
        flash(f"ลบตาราง OT วันที่ {schedule.ot_date.strftime('%d/%m/%Y')} สำเร็จ", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"เกิดข้อผิดพลาดในการลบตาราง: {str(e)}", "danger")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/create')
@login_required
def admin_create_page():
    if not current_user.is_admin: abort(403)
    all_users = User.query.filter_by(is_admin=False).order_by(User.full_name).all()
    return render_template('create_schedule.html', users=all_users)

@app.route('/api/create-schedule', methods=['POST'])
@login_required
def create_schedule():
    if not current_user.is_admin: abort(403)
    data = request.json
    ot_date_str = data.get('date')
    primary_user_ids_str = data.get('user_ids', []) # Might receive strings

    if not ot_date_str or not primary_user_ids_str:
        return jsonify({"error": "กรุณาเลือกวันที่และพนักงานอย่างน้อย 1 คน"}), 400

    try:
        # Convert user IDs to integers
        primary_user_ids = [int(uid) for uid in primary_user_ids_str]
    except ValueError:
         return jsonify({"error": "ข้อมูล User ID ไม่ถูกต้อง"}), 400


    try:
        ot_date = datetime.strptime(ot_date_str, '%Y-%m-%d').date()

        # Check if date is in the past
        if ot_date < date.today():
             return jsonify({"error": "ไม่สามารถสร้างตาราง OT สำหรับวันที่ผ่านมาแล้ว"}), 400

        existing_schedule = OTSchedule.query.filter_by(ot_date=ot_date).first()
        if existing_schedule:
            return jsonify({"error": f"มีตาราง OT สำหรับวันที่ {ot_date_str} อยู่แล้ว"}), 400

        new_schedule = OTSchedule(ot_date=ot_date)
        db.session.add(new_schedule)
        db.session.commit() # Commit schedule first to get its ID

        # Verify selected users exist and are not admins
        selected_users = User.query.filter(User.id.in_(primary_user_ids), User.is_admin == False).all()
        if len(selected_users) != len(primary_user_ids):
             db.session.rollback() # Rollback schedule creation if users are invalid
             invalid_ids = set(primary_user_ids) - set(u.id for u in selected_users)
             return jsonify({"error": f"ไม่พบข้อมูลพนักงานบางคน หรือเลือก Admin (IDs: {invalid_ids})"}), 400

        user_map = {u.id: u for u in selected_users}

        for user_id in primary_user_ids:
            response = OTResponse(schedule_id=new_schedule.id, primary_user_id=user_id)
            db.session.add(response)
        db.session.commit() # Commit responses

        # Now fetch the committed responses to get tokens
        created_responses = OTResponse.query.filter_by(schedule_id=new_schedule.id).all()

        links_for_admin_fallback = []
        names_list_for_group = []
        users_sent_count = 0

        # Use app context for url_for outside of request context (important for sending links)
        with app.app_context():
            for resp in created_responses:
                user = user_map.get(resp.primary_user_id)
                if not user:
                    continue

                names_list_for_group.append(f"- {user.full_name}")
                # Ensure _external=True for absolute URLs
                survey_link = url_for('show_survey', token=resp.token, _external=True)

                if user.line_user_id:
                    try:
                        message_text = (
                            f"สวัสดีครับ คุณ {user.full_name},\n\n"
                            f"คุณได้รับสิทธิ์ OT สำหรับวันที่ {ot_date.strftime('%d/%m/%Y')}\n"
                            f"กรุณากดยืนยัน/สละสิทธิ์ ภายในลิงก์นี้:\n\n"
                            f"{survey_link}"
                        )
                        message = TextSendMessage(text=message_text)
                        line_bot_api.push_message(user.line_user_id, messages=message)
                        users_sent_count += 1
                    except LineBotApiError as line_error:
                         print(f"!!! ส่ง LINE หา {user.full_name} ({user.line_user_id}) ไม่สำเร็จ: {line_error.status_code} {line_error.error.message}")
                         links_for_admin_fallback.append({
                            "name": f"{user.full_name} (ส่ง LINE ไม่สำเร็จ: {line_error.error.message})",
                            "link": survey_link
                        })
                    except Exception as e:
                        print(f"!!! เกิดข้อผิดพลาดอื่นในการส่ง LINE หา {user.full_name}: {e}")
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
        # Use flash for success message on redirect, not needed for API response
        # flash(f"สร้างตาราง OT วันที่ {ot_date_str} และส่งข้อความ LINE สำเร็จ!", "success")

        return jsonify({
            "message": f"สร้างตาราง OT วันที่ {ot_date_str} สำเร็จ! ส่ง LINE ให้พนักงาน {users_sent_count} คน",
            "links": links_for_admin_fallback,
            "schedule_id": new_schedule.id
        }), 201

    except ValueError:
         return jsonify({"error": "รูปแบบวันที่ในข้อมูลไม่ถูกต้อง"}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating schedule: {e}")
        return jsonify({"error": f"เกิดข้อผิดพลาดในการสร้างตาราง: {str(e)}"}), 500

# ฟังก์ชันสำหรับเตือน LINE
@app.route('/api/send-line-reminder', methods=['POST'])
@login_required
def send_line_reminder():
    if not current_user.is_admin: abort(403)
    data = request.json
    line_user_id = data.get('line_user_id')
    full_name = data.get('full_name')
    ot_date = data.get('ot_date')
    survey_link = data.get('survey_link')

    if not all([line_user_id, full_name, ot_date, survey_link]):
        return jsonify({"error": "ข้อมูลไม่ครบถ้วนสำหรับการส่ง Line"}), 400

    try:
        message_text = (
            f"สวัสดีครับ คุณ {full_name},\n\n"
            f"Admin แจ้งเตือนเรื่อง OT สำหรับวันที่ {ot_date} ที่คุณยังไม่ได้ตอบกลับครับ\n"
            f"กรุณากดลิงก์นี้เพื่อยืนยัน/สละสิทธิ์:\n\n"
            f"{survey_link}"
        )
        message = TextSendMessage(text=message_text)
        line_bot_api.push_message(line_user_id, messages=message)
        return jsonify({"message": "ส่ง LINE เตือนสำเร็จ!"}), 200
    except LineBotApiError as e:
        print(f"Error sending LINE reminder to {full_name} ({line_user_id}): {e.message}")
        # Provide more specific error if possible
        error_detail = e.error.message if hasattr(e, 'error') and hasattr(e.error, 'message') else str(e)
        return jsonify({"error": f"ส่ง LINE ไม่สำเร็จ: {error_detail}"}), 500
    except Exception as e:
        print(f"Unexpected error sending LINE reminder: {e}")
        app.logger.error(f"Unexpected error sending LINE reminder to {line_user_id}: {e}")
        return jsonify({"error": f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {str(e)}"}), 500


# ฟังก์ชันยืนยันตัวแทน
@app.route('/admin/substitute/confirm/<int:response_id>', methods=['POST'])
@login_required
def confirm_substitute(response_id):
    if not current_user.is_admin: abort(403)
    response = OTResponse.query.get_or_404(response_id)
    schedule_id_redirect = response.schedule_id # Get schedule ID before potential commit error

    if not response.delegated_user or response.response_status not in ['delegated', 'sub_declined']:
        flash("ไม่สามารถยืนยันตัวแทนได้ (สถานะไม่ถูกต้อง หรือ ไม่มีผู้รับมอบสิทธิ์)", "danger")
        return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))

    try:
        response.response_status = 'sub_confirmed'
        db.session.commit()

        ot_date_str = response.schedule.ot_date.strftime('%d/%m/%Y')
        message_to_group = (
            f"✅ ยืนยันตัวแทน OT ({ot_date_str}) ✅\n"
            f"ผู้สละสิทธิ์: คุณ {response.primary_user.full_name}\n"
            f"ตัวแทน: คุณ {response.delegated_user.full_name} (ยืนยันมาแน่นอน)"
        )
        send_line_push_message(message_to_group)
        flash("ยืนยันตัวแทนเรียบร้อยแล้ว", "success")

    except Exception as e:
         db.session.rollback()
         flash(f"เกิดข้อผิดพลาดในการยืนยันตัวแทน: {e}", "danger")
         app.logger.error(f"Error confirming substitute for response {response_id}: {e}")

    return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))


# ฟังก์ชันปฏิเสธตัวแทน
@app.route('/admin/substitute/reject/<int:response_id>', methods=['POST'])
@login_required
def reject_substitute(response_id):
    if not current_user.is_admin: abort(403)
    response = OTResponse.query.get_or_404(response_id)
    schedule_id_redirect = response.schedule_id
    original_delegated_user = response.delegated_user # Get user before potentially changing

    if not original_delegated_user or response.response_status not in ['delegated', 'sub_confirmed']:
        flash("ไม่สามารถปฏิเสธตัวแทนได้ (สถานะไม่ถูกต้อง หรือ ไม่มีผู้รับมอบสิทธิ์)", "danger")
        return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))

    try:
        response.response_status = 'sub_declined'
        response.let_admin_decide = True
        # Keep delegated_to_user_id for record, or set to None if admin should reassign blank
        # response.delegated_to_user_id = None # Optional: Clear assignment
        db.session.commit()

        ot_date_str = response.schedule.ot_date.strftime('%d/%m/%Y')
        message_to_group = (
            f"🚨 ตัวแทน OT ปฏิเสธ ({ot_date_str}) 🚨\n"
            f"ผู้สละสิทธิ์: คุณ {response.primary_user.full_name}\n"
            f"ตัวแทนที่ปฏิเสธ: คุณ {original_delegated_user.full_name} (ไม่สามารถมาได้)\n\n"
            f"‼️ Admin: กรุณาหาคนใหม่แทน"
        )
        send_line_push_message(message_to_group)
        flash("ปฏิเสธตัวแทนแล้ว (ระบบจะคืนสถานะให้ Admin เลือกคนใหม่)", "warning")

    except Exception as e:
         db.session.rollback()
         flash(f"เกิดข้อผิดพลาดในการปฏิเสธตัวแทน: {e}", "danger")
         app.logger.error(f"Error rejecting substitute for response {response_id}: {e}")

    return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))


# ฟังก์ชัน Admin เลือกตัวแทน
@app.route('/admin/assign-substitute/<int:response_id>', methods=['POST'])
@login_required
def assign_substitute(response_id):
    if not current_user.is_admin: abort(403)
    response = OTResponse.query.get_or_404(response_id)
    schedule_id_redirect = response.schedule_id

    if response.response_status not in ['declined_admin', 'sub_declined']:
        flash("ไม่สามารถมอบหมายได้ (สถานะไม่ถูกต้อง)", "danger")
        return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))

    try:
        # Check if user_id exists in the form data and is not empty
        if 'user_id' not in request.form or not request.form['user_id']:
             flash("กรุณาเลือกพนักงานที่จะมอบหมาย", "warning")
             return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))

        sub_user_id = int(request.form['user_id'])
        sub_user = User.query.get(sub_user_id)

        if not sub_user:
             flash("ไม่พบพนักงานที่เลือก", "danger")
             return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))

        # Check if the selected user is already assigned or a primary user in this schedule
        existing_primary = OTResponse.query.filter(
            OTResponse.schedule_id == response.schedule_id,
            OTResponse.primary_user_id == sub_user_id
        ).first()

        existing_assignment = OTResponse.query.filter(
            OTResponse.schedule_id == response.schedule_id,
            OTResponse.delegated_to_user_id == sub_user_id,
            OTResponse.response_status.in_(['delegated', 'sub_confirmed']),
            OTResponse.id != response_id # Exclude the current response itself if it was sub_declined
        ).first()

        if existing_primary or existing_assignment:
            flash(f"เลือกตัวแทนซ้ำ! ({sub_user.full_name} มีส่วนร่วมใน OT นี้แล้ว)", "danger")
            return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))

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

    except ValueError:
         flash("ข้อมูลที่ส่งมาไม่ถูกต้อง (User ID)", "danger")
         return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))
    except Exception as e:
        db.session.rollback()
        flash(f"เกิดข้อผิดพลาดในการมอบหมาย: {str(e)}", "danger")
        app.logger.error(f"Error assigning substitute for response {response_id}: {e}")

    return redirect(url_for('admin_dashboard', schedule_id=schedule_id_redirect))


# หน้ารายงาน
@app.route('/admin/reports')
@login_required
def admin_reports():
    if not current_user.is_admin: abort(403)

    # --- 1. ตั้งค่าตัวกรอง (Filters) ---
    today = date.today()
    current_year = today.year
    current_month = today.month
    current_week = today.isocalendar()[1]

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
    monthly_summary = {}
    sorted_monthly_summary = []
    try:
        monthly_responses = db.session.query(
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
            extract('month', OTSchedule.ot_date) == selected_month,
            OTResponse.response_status.in_(['confirmed', 'sub_confirmed'])
        ).order_by(OTSchedule.ot_date.asc()).all()

        for resp, schedule, primary_name, sub_name in monthly_responses:
            user_name = None # Use None initially

            if resp.response_status == 'confirmed':
                user_name = primary_name
            elif resp.response_status == 'sub_confirmed':
                user_name = sub_name if sub_name else f"User ID: {resp.delegated_to_user_id or 'Unknown'}" # Handle missing sub_name

            if user_name:
                if user_name not in monthly_summary:
                    monthly_summary[user_name] = {'name': user_name, 'dates': []}
                monthly_summary[user_name]['dates'].append(schedule.ot_date)

        sorted_monthly_summary = sorted(monthly_summary.values(), key=lambda item: len(item['dates']), reverse=True)
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลรายเดือน: {e}", "danger")
        print(f"Error fetching monthly report: {e}") # Log the error


    # --- 3. Logic สรุปผลรายสัปดาห์ ---
    weekly_summary = {}
    sorted_weekly_summary = []
    week_range_str = f"(สัปดาห์ที่ {selected_week})" # Default week string
    try:
        # PostgreSQL uses 'week', SQLite might need adjustments or different approach
        week_filter_column = extract('week', OTSchedule.ot_date)
        # For ISO week standard used by isocalendar(), PostgreSQL also supports 'isoyear'
        year_filter_column = extract('isoyear', OTSchedule.ot_date)

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
            year_filter_column == selected_year, # Use ISO year
            week_filter_column == selected_week,
            OTResponse.response_status.in_(['confirmed', 'sub_confirmed'])
        ).order_by(OTSchedule.ot_date.asc()).all()

        for resp, schedule, primary_name, sub_name in weekly_responses:
            user_name = None
            if resp.response_status == 'confirmed':
                user_name = primary_name
            elif resp.response_status == 'sub_confirmed':
                 user_name = sub_name if sub_name else f"User ID: {resp.delegated_to_user_id or 'Unknown'}"

            if user_name:
                if user_name not in weekly_summary:
                    weekly_summary[user_name] = {'name': user_name, 'dates': []}
                weekly_summary[user_name]['dates'].append(schedule.ot_date)

        sorted_weekly_summary = sorted(weekly_summary.values(), key=lambda item: len(item['dates']), reverse=True)

        # Calculate week range string (moved inside try) - using ISO standard week definition
        # Monday is 1, Sunday is 7
        week_start = datetime.strptime(f'{selected_year}-W{selected_week}-1', "%G-W%V-%u").date()
        week_end = datetime.strptime(f'{selected_year}-W{selected_week}-7', "%G-W%V-%u").date()
        week_range_str = f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m/%Y')}"

    except ValueError:
         flash(f"ไม่สามารถคำนวณช่วงวันที่สำหรับสัปดาห์ที่ {selected_week} ปี {selected_year}", "warning")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลรายสัปดาห์: {e}", "danger")
        print(f"Error fetching weekly report: {e}") # Log the error

    # --- 4. ส่งข้อมูลไปที่ Template ---
    first_schedule = OTSchedule.query.order_by(OTSchedule.ot_date.asc()).first()
    start_year = first_schedule.ot_date.year if first_schedule else current_year
    available_years = list(range(start_year, current_year + 2))

    month_names = [(i, calendar.month_name[i]) for i in range(1, 13)]

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


# หน้า Dashboard หลัก
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin: abort(403)

    all_schedules = OTSchedule.query.order_by(OTSchedule.ot_date.desc()).all()
    schedule_id_to_show = request.args.get('schedule_id', type=int)
    search_date_str = request.args.get('search_date')

    selected_schedule = None
    # error_message = None # Replaced by flash messages
    responses = []
    available_substitutes = [] # (V3)

    try:
        if schedule_id_to_show:
            selected_schedule = OTSchedule.query.get(schedule_id_to_show)
            # If ID is provided, clear search date string
            search_date_str = None

        elif search_date_str:
            search_date = datetime.strptime(search_date_str, '%Y-%m-%d').date()
            selected_schedule = OTSchedule.query.filter_by(ot_date=search_date).first()
            if not selected_schedule:
                flash(f"ไม่พบตาราง OT สำหรับวันที่ {search_date.strftime('%d/%m/%Y')}", "info") # Use info, not error
                # If search yields nothing, maybe default to latest? Or show empty.
                # selected_schedule = all_schedules[0] if all_schedules else None

        elif all_schedules:
            selected_schedule = all_schedules[0]

        # (V3) เพิ่ม Logic ค้นหาคนว่าง
        if selected_schedule:
            responses = selected_schedule.responses

            all_primary_user_ids = [r.primary_user_id for r in responses]

            all_delegated_user_ids = [
                r.delegated_to_user_id for r in responses
                if r.delegated_to_user_id is not None and
                   r.response_status in ['delegated', 'sub_confirmed']
            ]

            excluded_user_ids = list(set(all_primary_user_ids + all_delegated_user_ids))

            available_substitutes = User.query.filter(
                User.id.notin_(excluded_user_ids),
                User.is_admin == False
            ).order_by(User.full_name).all()

    except ValueError:
        flash("รูปแบบวันที่ไม่ถูกต้อง (ต้องเป็น YYYY-MM-DD)", "danger")
        search_date_str = None
        selected_schedule = None
        responses = []
        available_substitutes = []
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "danger")
        app.logger.error(f"Error in admin_dashboard: {e}")
        selected_schedule = None
        responses = []
        available_substitutes = []

    # (V3) อัปเกรดการส่งค่า
    return render_template('admin.html',
                           all_schedules=all_schedules,
                           selected_schedule=selected_schedule,
                           responses=responses,
                           available_substitutes=available_substitutes,
                           search_date_str=search_date_str
                           )


# หน้า Setup Demo (ควรคอมเมนต์ออก)
# @app.route('/setup-demo')
# @login_required
# def setup_demo():
#     if not current_user.is_admin: abort(403)
#     try:
#         db.session.query(OTResponse).delete()
#         db.session.query(OTSchedule).delete()
#         User.query.filter(User.is_admin == False).delete()
#         db.session.commit()
#
#         user_a = User(username='a', full_name='นายประทวน มงคลศิลป์')
#         user_b = User(username='b', full_name='นายสุธี แซ่อึ้ง')
#         user_c = User(username='c', full_name='นายพลวัต รัตนภักดี')
#         user_d = User(username='d', full_name='นายนิติธร สุขหิรัญ')
#         user_e = User(username='e', full_name='นายอนุพงษ์ อิงสันเทียะ')
#         db.session.add_all([user_a, user_b, user_c, user_d, user_e])
#         db.session.commit()
#
#         flash("สร้างข้อมูล Demo สำเร็จ (ลบข้อมูลเก่าและสร้างพนักงาน 5 คน)", "success")
#         return redirect(url_for('admin_users_page')) # Redirect to user page after setup
#         # return f"""
#         # <h1>สร้างข้อมูลพนักงาน 5 คนสำเร็จ!</h1>
#         # <p>ลบข้อมูลตาราง OT และพนักงานเก่าทั้งหมด (ยกเว้น Admin) และสร้างรายชื่อพนักงาน 5 คนเรียบร้อยแล้ว</p>
#         # <hr>
#         # <p><b>ขั้นตอนต่อไป:</b> <a href='/admin/create'>ไปที่หน้าสร้างตาราง OT</a></p>
#         # <p><b>หรือไปที่หน้า Dashboard หลัก:</b> <a href='/admin'>/admin</a></p>
#         # """
#     except Exception as e:
#         db.session.rollback()
#         flash(f"เกิดข้อผิดพลาดในการ Setup Demo: {e}", "danger")
#         return redirect(url_for('admin_dashboard'))


# Handler สำหรับรับข้อความ LINE
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text
    reply_text = ""

    # --- 1. ตรวจสอบ Logic ---
    if text == "ดูตาราง OT ที่ยังไม่ตอบ":
        user = User.query.filter_by(line_user_id=user_id).first()

        if not user:
            reply_text = "ไม่พบข้อมูลของคุณในระบบ กรุณาติดต่อ Admin เพื่อลงทะเบียน LINE User ID ครับ"
        else:
            pending_responses = db.session.query(OTResponse).join(OTSchedule).filter(
                OTResponse.primary_user_id == user.id,
                OTResponse.response_status == 'pending',
                OTSchedule.ot_date >= date.today() # Only future/today's OT
            ).order_by(OTSchedule.ot_date.asc()).all()

            if not pending_responses:
                reply_text = f"สวัสดีครับ คุณ {user.full_name}\n\nคุณไม่มียอด OT ค้างตอบครับ 👍"
            else:
                reply_text = f"สวัสดีครับ คุณ {user.full_name}\n\nคุณมี OT ที่ยังไม่ตอบ {len(pending_responses)} รายการ:\n\n"

                with app.app_context():
                    for resp in pending_responses:
                        survey_link = url_for('show_survey', token=resp.token, _external=True)
                        reply_text += (
                            f"📅 วันที่: {resp.schedule.ot_date.strftime('%d/%m/%Y')}\n"
                            f"🔗 ลิงก์: {survey_link}\n\n"
                        )
                reply_text = reply_text.strip() # Remove last newline

    else:
        # --- Logic เดิม: (ถ้าไม่ใช่คำสั่ง Rich Menu) ---
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! USER ID ที่คุณตามหาคือ: {user_id}")
        print(f"!!! เขาพิมพ์ว่า: {text}")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        reply_text = f'นี่คือ User ID ของคุณ:\n{user_id}\n\nกรุณาคัดลอก ID นี้ไปให้ Admin ครับ'

    # --- 2. ส่งการตอบกลับ ---
    try:
        # Use V3 API for replying
        configuration = Configuration(access_token=YOUR_CHANNEL_ACCESS_TOKEN)
        with ApiClient(configuration) as api_client:
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
    # Important: Set debug=False for production deployment on Render
    # The PORT environment variable is automatically set by Render.
    port = int(os.environ.get('PORT', 5000))
    # Use host='0.0.0.0' to be accessible externally
    app.run(debug=False, host='0.0.0.0', port=port)