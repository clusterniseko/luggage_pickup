import os
import sys
import logging
import hmac
import hashlib
import time
import base64
from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS


# ── AUTH HELPERS ──────────────────────────────────────

def load_admin_users():
    """Reads ADMIN_USERS env var. Format: 'Admin:pass1,Manager:pass2'"""
    raw = os.environ.get("ADMIN_USERS", "")
    users = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            username, password = pair.split(":", 1)
            users[username.strip()] = password.strip()
    return users


def make_session_token(username: str) -> str:
    """Creates a signed HMAC-SHA256 token: base64(username:timestamp:signature)"""
    secret = os.environ.get("SECRET_KEY", "change-this-secret-in-railway")
    ts = str(int(time.time()))
    msg = f"{username}:{ts}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.b64encode(f"{msg}:{sig}".encode()).decode()


def verify_session_token(token: str):
    """Returns username if token is valid and not expired (12h), else None."""
    secret = os.environ.get("SECRET_KEY", "change-this-secret-in-railway")
    try:
        decoded = base64.b64decode(token.encode()).decode()
        username, ts, sig = decoded.rsplit(":", 2)
        msg = f"{username}:{ts}"
        expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(time.time()) - int(ts) > 43200:  # 12 hours
            return None
        return username
    except Exception:
        return None


def require_admin(f):
    """Decorator to protect routes — checks Authorization: Bearer <token>"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        if not token or not verify_session_token(token):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated



# ── LOGGING ───────────────────────────────────────────
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── DATABASE ──────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    log.warning("DATABASE_URL not set — falling back to local SQLite")
    DATABASE_URL = "sqlite:///luggage.db"
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

log.info(f"Using database: {DATABASE_URL[:40]}...")

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "connect_args": {} if DATABASE_URL.startswith("sqlite") else {
        "connect_timeout": 10
    }
}

db = SQLAlchemy(app)


# ── MODEL ─────────────────────────────────────────────
class LuggageRequest(db.Model):
    __tablename__ = "luggage_requests"

    id           = db.Column(db.Integer, primary_key=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    hotel        = db.Column(db.String(100), nullable=False)
    name         = db.Column(db.String(200), nullable=False)
    room         = db.Column(db.String(50),  nullable=False)
    date         = db.Column(db.String(20),  nullable=False)
    time         = db.Column(db.String(20),  nullable=False)
    items        = db.Column(db.String(20),  nullable=False)
    special      = db.Column(db.Text,        default="")
    trashed      = db.Column(db.Boolean,     default=False, nullable=False)
    deleted_at   = db.Column(db.DateTime,    nullable=True)

    def to_dict(self, include_deleted=False):
        d = {
            "id":          self.id,
            "submittedAt": self.submitted_at.isoformat() if self.submitted_at else "",
            "hotel":       self.hotel,
            "name":        self.name,
            "room":        self.room,
            "date":        self.date,
            "time":        self.time,
            "items":       self.items,
            "special":     self.special or "",
        }
        if include_deleted:
            d["deletedAt"] = self.deleted_at.isoformat() if self.deleted_at else ""
        return d


# ── INIT DB ───────────────────────────────────────────
def init_db():
    try:
        with app.app_context():
            db.create_all()
            count = db.session.execute(
                db.text("SELECT COUNT(*) FROM luggage_requests")
            ).scalar()
            log.info(f"✅ Table 'luggage_requests' ready. Current rows: {count}")
    except Exception as e:
        log.error(f"❌ Failed to init database: {e}")
        raise


# ── HEALTH CHECK ──────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    try:
        count = db.session.execute(
            db.text("SELECT COUNT(*) FROM luggage_requests")
        ).scalar()
        return jsonify({
            "status": "ok",
            "service": "Niseko Luggage API",
            "db": "connected",
            "records": count
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "db": "failed",
            "detail": str(e)
        }), 500


# ── GET — active records ──────────────────────────────
@app.route("/api/luggage", methods=["GET"])
def get_luggage():
    records = (
        LuggageRequest.query
        .filter_by(trashed=False)
        .order_by(LuggageRequest.id.desc())
        .all()
    )
    return jsonify([r.to_dict() for r in records])


# ── POST — new guest request ──────────────────────────
@app.route("/api/luggage", methods=["POST"])
def create_luggage():
    data = request.get_json(silent=True) or {}

    required = ["hotel", "name", "room", "date", "time", "items"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    record = LuggageRequest(
        hotel=data["hotel"].strip(),
        name=data["name"].strip(),
        room=data["room"].strip(),
        date=data["date"].strip(),
        time=data["time"].strip(),
        items=data["items"].strip(),
        special=data.get("special", "").strip(),
    )
    db.session.add(record)
    db.session.commit()
    log.info(f"New request: {record.name} / Room {record.room} / {record.hotel}")
    return jsonify({"id": record.id}), 201


# ── GET — trashed records ─────────────────────────────
@app.route("/api/luggage/trash", methods=["GET"])
def get_trash():
    records = (
        LuggageRequest.query
        .filter_by(trashed=True)
        .order_by(LuggageRequest.deleted_at.desc())
        .all()
    )
    return jsonify([r.to_dict(include_deleted=True) for r in records])


# ── POST — move to trash ──────────────────────────────
@app.route("/api/luggage/trash", methods=["POST"])
def move_to_trash():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "No ids provided"}), 400

    LuggageRequest.query.filter(LuggageRequest.id.in_(ids)).update(
        {"trashed": True, "deleted_at": datetime.utcnow()},
        synchronize_session=False,
    )
    db.session.commit()
    return jsonify({"ok": True})


# ── POST — restore from trash ─────────────────────────
@app.route("/api/luggage/restore", methods=["POST"])
def restore_from_trash():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "No ids provided"}), 400

    LuggageRequest.query.filter(LuggageRequest.id.in_(ids)).update(
        {"trashed": False, "deleted_at": None},
        synchronize_session=False,
    )
    db.session.commit()
    return jsonify({"ok": True})


# ── DELETE — permanent delete ─────────────────────────
@app.route("/api/luggage/permanent", methods=["DELETE"])
def perm_delete():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "No ids provided"}), 400

    LuggageRequest.query.filter(LuggageRequest.id.in_(ids)).delete(
        synchronize_session=False
    )
    db.session.commit()
    return jsonify({"ok": True})



# ── POST — admin login ────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    users = load_admin_users()

    # Case-insensitive username lookup
    matched_user = None
    matched_pass = None
    for u, p in users.items():
        if u.lower() == username.lower():
            matched_user = u
            matched_pass = p
            break

    log.info(f"Login attempt: '{username}' | known users: {list(users.keys())} | match: {matched_user}")

    if not matched_pass:
        time.sleep(0.5)
        return jsonify({"error": "Invalid credentials"}), 401

    # Safe constant-time comparison — pad to same length to avoid length leak
    def safe_compare(a, b):
        a = a.encode() if isinstance(a, str) else a
        b = b.encode() if isinstance(b, str) else b
        if len(a) != len(b):
            # Still do a compare to avoid timing leak, but return False
            hmac.compare_digest(a, a)
            return False
        return hmac.compare_digest(a, b)

    if not safe_compare(matched_pass, password):
        time.sleep(0.5)
        return jsonify({"error": "Invalid credentials"}), 401

    token = make_session_token(matched_user)
    log.info(f"Admin login success: {matched_user}")
    return jsonify({"token": token, "username": matched_user}), 200

# ── DAILY REPORT — Hilton ─────────────────────────────
@app.route("/api/send-daily-report", methods=["POST"])
def send_daily_report():
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    # ── Validate secret token ──
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    report_secret = os.environ.get("REPORT_SECRET", "")
    if not report_secret or token != report_secret:
        return jsonify({"error": "Unauthorized"}), 401

    # ── Tomorrow's date in JST (UTC+9) ──
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    tomorrow_jst = now_jst + timedelta(days=1)
    tomorrow_str = tomorrow_jst.strftime("%Y-%m-%d")

    # ── Query: Hilton requests for tomorrow ──
    HOTEL = "Hilton"
    records = (
        LuggageRequest.query
        .filter_by(trashed=False, hotel=HOTEL, date=tomorrow_str)
        .order_by(LuggageRequest.time)
        .all()
    )

    if not records:
        log.info(f"Daily report: no {HOTEL} requests for {tomorrow_str} — email not sent")
        return jsonify({"sent": False, "date": tomorrow_str, "count": 0})

    # ── Build Excel ──
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Hilton {tomorrow_str}"

    header_fill = PatternFill("solid", fgColor="1A3A6B")   # Hilton navy
    header_font = Font(color="FFFFFF", bold=True, size=11)
    center      = Alignment(horizontal="center", vertical="center")

    headers = ["Hotel", "Room", "Guest Name", "Pick-up Date", "Pick-up Time", "Items", "Special Notes"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill      = header_fill
        cell.font      = header_font
        cell.alignment = center

    for row_idx, r in enumerate(records, 2):
        ws.cell(row=row_idx, column=1, value=r.hotel)
        ws.cell(row=row_idx, column=2, value=r.room)
        ws.cell(row=row_idx, column=3, value=r.name)
        ws.cell(row=row_idx, column=4, value=r.date)
        ws.cell(row=row_idx, column=5, value=r.time)
        ws.cell(row=row_idx, column=6, value=r.items)
        ws.cell(row=row_idx, column=7, value=r.special or "")

    # Auto-fit column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 4

    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)

    # ── Send email via Resend HTTP API ──
    import json
    import urllib.request
    import urllib.error

    resend_key     = os.environ.get("RESEND_API_KEY", "")
    report_from    = os.environ.get("REPORT_EMAIL_FROM", "")   # e.g. luggage@nisekocluster.com (verified domain)
    reply_to       = os.environ.get("GMAIL_FROM", "")          # optional: replies go here
    report_to_raw  = os.environ.get("REPORT_EMAIL_TO_HILTON", "")
    report_to_list = [e.strip() for e in report_to_raw.split(",") if e.strip()]

    if not all([resend_key, report_from, report_to_list]):
        log.error("Daily report: one or more email env vars are missing")
        return jsonify({"error": "Email configuration incomplete"}), 500

    subject = f"Luggage Pick-up — Hilton — {tomorrow_str} ({len(records)} request{'s' if len(records) != 1 else ''})"
    body = (
        f"お疲れ様です。\n\n"
        f"ラゲッジピックアップのご依頼 — ヒルトンニセコビレッジ\n"
        f"日付：{tomorrow_str}\n"
        f"リクエスト数：{len(records)}\n\n"
        f"詳細は添付のExcelファイルをご確認ください。\n\n"
        f"よろしくお願いいたします。\n\n"
        f"ヒルトン ニセコビレッジ - ラゲッジピックアップシステム\n"
        f"コンシエル・ベルデスク\n"
        f"オルテガ・イエンリー\n"
        f"{'─' * 40}\n"
        f"Good evening,\n\n"
        f"Luggage Pick-up Requests — Hilton Niseko Village\n"
        f"Date: {tomorrow_str}\n"
        f"Total requests: {len(records)}\n\n"
        f"Please find the attached Excel file with the full details.\n\n"
        f"Best regards,\n\n"
        f"Hilton Niseko Village - Luggage Pick-Up System\n"
        f"Concierge-Bell Desk\n"
        f"Yenry Ortega"
    )

    filename       = f"hilton-luggage-pick-up-{tomorrow_str}.xlsx"
    encoded_excel  = base64.b64encode(excel_buffer.read()).decode()

    payload = {
        "from": f"Hilton Niseko Village - Luggage Pick-Up <{report_from}>",
        "to": report_to_list,
        "subject": subject,
        "text": body,
        "attachments": [{
            "filename": filename,
            "content": encoded_excel,
        }],
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
                "User-Agent": "niseko-luggage/1.0",  # Resend rejects the default Python-urllib agent
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            result = json.loads(resp.read().decode() or "{}")
        log.info(f"Daily report sent: {len(records)} Hilton requests for {tomorrow_str} → {report_to_list} (HTTP {status}, id {result.get('id')})")
        return jsonify({"sent": True, "date": tomorrow_str, "count": len(records)})
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        log.error(f"Daily report email failed: HTTP {e.code} — {detail}")
        return jsonify({"error": f"HTTP {e.code}", "detail": detail}), 500
    except Exception as e:
        log.error(f"Daily report email failed: {e}")
        return jsonify({"error": str(e)}), 500


# ── ENTRY POINT ───────────────────────────────────────
# init_db() runs at module load — before gunicorn serves any traffic
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
