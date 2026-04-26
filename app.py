import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow requests from any frontend origin

# ── DATABASE ──────────────────────────────────────────
# Railway injects DATABASE_URL automatically.
# SQLAlchemy requires "postgresql://" not "postgres://"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///luggage.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ── MODEL ─────────────────────────────────────────────
class LuggageRequest(db.Model):
    __tablename__ = "luggage_requests"

    id           = db.Column(db.Integer, primary_key=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    hotel        = db.Column(db.String(100), nullable=False)
    name         = db.Column(db.String(200), nullable=False)
    room         = db.Column(db.String(50),  nullable=False)
    date         = db.Column(db.String(20),  nullable=False)   # YYYY-MM-DD
    time         = db.Column(db.String(20),  nullable=False)   # e.g. "9:00 AM"
    items        = db.Column(db.String(20),  nullable=False)   # e.g. "3" or "10+"
    special      = db.Column(db.Text,        default="")
    trashed      = db.Column(db.Boolean,     default=False,    nullable=False)
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


# ── CREATE TABLES ON FIRST START ──────────────────────
with app.app_context():
    db.create_all()


# ── HEALTH CHECK ──────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Niseko Luggage API"}), 200


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
    ids = request.get_json(silent=True).get("ids", [])
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
    ids = request.get_json(silent=True).get("ids", [])
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
    ids = request.get_json(silent=True).get("ids", [])
    if not ids:
        return jsonify({"error": "No ids provided"}), 400

    LuggageRequest.query.filter(LuggageRequest.id.in_(ids)).delete(
        synchronize_session=False
    )
    db.session.commit()
    return jsonify({"ok": True})


# ── RUN ───────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
