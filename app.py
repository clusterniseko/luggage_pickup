import os
import sys
import logging
import hmac
import hashlib
import time
import base64
from functools import wraps
from datetime import datetime
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
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400

    users = load_admin_users()
    stored = users.get(username, "")

    if not stored or not hmac.compare_digest(stored, password):
        time.sleep(0.5)  # slow down brute force
        return jsonify({"error": "Invalid credentials"}), 401

    token = make_session_token(username)
    log.info(f"Admin login: {username}")
    return jsonify({"token": token, "username": username}), 200

# ── ENTRY POINT ───────────────────────────────────────
# init_db() runs at module load — before gunicorn serves any traffic
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
