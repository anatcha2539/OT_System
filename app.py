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
    schedule = db.relationship('OTSchedule', backref=db.backref('responses', lazy=True))
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
            # return render_template('login.html', error="Username หรือ Password ไม่ถูกต้อง (หรือคุณไม่ใช่ Admin)") # ไม่ต้องใช้ error แล้ว เพราะใช้ flash
            return render_template('login.html') # ส่งแค่ template ไป flash จะแสดงผลเอง

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
                delegated_id = data.get('delegated_to_id')
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

                response.response_status = 'delegated'
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

        if line_user_id and line_user_id.strip() != "":
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
        has_responses = OTResponse.query.filter(
            (OTResponse.primary_user_id == user_id) |
            (OTResponse.delegated_to_user_id == user_id)
        ).first()

        if has_responses:
            flash("ไม่สามารถลบผู้ใช้นี้ได้: ผู้ใช้มีข้อมูลผูกพันอยู่ในตาราง OT ที่สร้างไปแล้ว", "danger")
            return redirect(url_for('admin_users_page'))

        user = User.query.get_or_404(user_id)

        if user.is_admin:
            flash("ไม่สามารถลบผู้ดูแลระบบได้", "danger")
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
        db.session.commit() # Commit schedule first to get its ID

        created_responses = []
        selected_users = User.query.filter(User.id.in_(primary_user_ids)).all()
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
        flash(f"สร้างตาราง OT วันที่ {ot_date_str} และส่งข้อความ LINE สำเร็จ!", "success")

        return jsonify({
            "message": "สร้างตาราง OT สำเร็จ!",
            "links": links_for_admin_fallback,
            "schedule_id": new_schedule.id
        }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating schedule: {e}")
        return jsonify({"error": f"เกิดข้อผิดพลาดในการสร้างตาราง: {str(e)}"}), 500

# ฟังก์ชันสำหรับเตือน LINE
@app.route('/api/send-line-reminder', methods=['POST'])
@login_required
def send_line_reminder():
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# ฟังก์ชันยืนยันตัวแทน
@app.route('/admin/substitute/confirm/<int:response_id>', methods=['POST'])
@login_required
def confirm_substitute(response_id):
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# ฟังก์ชันปฏิเสธตัวแทน
@app.route('/admin/substitute/reject/<int:response_id>', methods=['POST'])
@login_required
def reject_substitute(response_id):
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# ฟังก์ชัน Admin เลือกตัวแทน
@app.route('/admin/assign-substitute/<int:response_id>', methods=['POST'])
@login_required
def assign_substitute(response_id):
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# หน้ารายงาน
@app.route('/admin/reports')
@login_required
def admin_reports():
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# หน้า Dashboard หลัก
@app.route('/admin')
@login_required
def admin_dashboard():
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# หน้า Setup Demo (ควรคอมเมนต์ออก)
# @app.route('/setup-demo')
# @login_required
# def setup_demo():
    # ... (โค้ดเหมือนเดิม) ...
#    pass # Placeholder - keep the original code

# Handler สำหรับรับข้อความ LINE
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # ... (โค้ดเหมือนเดิม) ...
    pass # Placeholder - keep the original code

# --- 4. ส่วนสำหรับรัน Server ---
if __name__ == '__main__':
    # Important: Set debug=False for production
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))