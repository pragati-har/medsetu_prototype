import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "medsetu.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
REPORTS_DIR = UPLOAD_DIR / "reports"
EXTERNAL_DIR = UPLOAD_DIR / "external"

ACCESS_WINDOW_MINUTES = 30
SESSION_HOURS = 8

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "medsetu-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


MEDICINES = [
    ("Dolo 650", "Paracetamol", "Fever, mild pain", "650 mg every 6-8 hours", "Avoid overdose; monitor liver disease"),
    ("Crocin Advance", "Paracetamol", "Fever, headache", "500 mg every 6 hours", "Do not exceed daily max dose"),
    ("Augmentin 625", "Amoxicillin + Clavulanic Acid", "Bacterial infections", "1 tablet every 12 hours", "Complete course; watch penicillin allergy"),
    ("Azithral 500", "Azithromycin", "Respiratory infections", "500 mg once daily", "Take before food if tolerated"),
    ("Pantocid 40", "Pantoprazole", "Acidity, GERD", "40 mg once daily before breakfast", "Long-term use may lower magnesium"),
    ("Rantac", "Ranitidine", "Acid reflux", "150 mg twice daily", "Use alternatives where restricted"),
    ("Glycomet 500", "Metformin", "Type 2 diabetes", "500 mg once or twice daily with meals", "Monitor renal function"),
    ("Amaryl 1", "Glimepiride", "Type 2 diabetes", "1 mg once daily", "Risk of hypoglycemia"),
    ("Telma 40", "Telmisartan", "Hypertension", "40 mg once daily", "Monitor kidney function and potassium"),
    ("Amlong 5", "Amlodipine", "Hypertension", "5 mg once daily", "May cause ankle swelling"),
    ("Ecosprin 75", "Aspirin", "Antiplatelet therapy", "75 mg once daily", "Avoid in active bleeding"),
    ("Atorva 10", "Atorvastatin", "High cholesterol", "10 mg at bedtime", "Monitor liver enzymes"),
    ("Montek LC", "Montelukast + Levocetirizine", "Allergic rhinitis", "1 tablet at night", "May cause drowsiness"),
    ("Cetzine", "Cetirizine", "Allergy symptoms", "10 mg once daily", "Sedation in some patients"),
    ("Becosules", "Vitamin B-Complex", "Nutritional deficiency", "1 capsule once daily", "Use as supplement only"),
    ("Shelcal 500", "Calcium + Vitamin D3", "Bone health", "1 tablet once daily", "Take after meals"),
    ("Zifi 200", "Cefixime", "Bacterial infections", "200 mg twice daily", "Adjust dose in renal disease"),
    ("Omez D", "Omeprazole + Domperidone", "GERD, nausea", "1 capsule before breakfast", "Avoid prolonged unsupervised use"),
    ("Volini Gel", "Diclofenac (topical)", "Muscle pain", "Apply thin layer 2-3 times daily", "Do not apply on open wounds"),
    ("Calpol 250", "Paracetamol", "Pediatric fever", "Weight-based dosing", "Use measured pediatric dosing"),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", ""))


def init_db():
    with closing(get_db()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('doctor', 'pharmacist', 'patient')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                mobile TEXT UNIQUE NOT NULL,
                dob TEXT,
                gender TEXT,
                allergies TEXT DEFAULT '[]',
                chronic_conditions TEXT DEFAULT '[]',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                medical_registration_number TEXT UNIQUE NOT NULL,
                specialization TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS pharmacists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                pharmacy_name TEXT,
                license_number TEXT UNIQUE NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_name TEXT NOT NULL,
                generic_name TEXT NOT NULL,
                indications TEXT,
                standard_dosage TEXT,
                precautions TEXT
            );

            CREATE TABLE IF NOT EXISTS prescriptions (
                prescription_id TEXT PRIMARY KEY,
                doctor_id INTEGER NOT NULL,
                patient_id INTEGER NOT NULL,
                medicines_json TEXT NOT NULL,
                doctor_notes TEXT,
                digital_signature TEXT,
                status TEXT NOT NULL CHECK(status IN ('Active', 'Dispensed', 'Expired')),
                created_at TEXT NOT NULL,
                dispensed_at TEXT,
                pharmacist_id INTEGER,
                qr_payload TEXT,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id),
                FOREIGN KEY (patient_id) REFERENCES patients(id),
                FOREIGN KEY (pharmacist_id) REFERENCES pharmacists(id)
            );

            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id INTEGER,
                patient_id INTEGER,
                pharmacist_id INTEGER,
                action TEXT NOT NULL,
                success INTEGER NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id),
                FOREIGN KEY (patient_id) REFERENCES patients(id),
                FOREIGN KEY (pharmacist_id) REFERENCES pharmacists(id)
            );

            CREATE TABLE IF NOT EXISTS patient_otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                otp_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                verified_at TEXT,
                FOREIGN KEY (patient_id) REFERENCES patients(id),
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            );

            CREATE TABLE IF NOT EXISTS doctor_access_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id INTEGER NOT NULL,
                patient_id INTEGER NOT NULL,
                otp_id INTEGER NOT NULL,
                granted_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id),
                FOREIGN KEY (patient_id) REFERENCES patients(id),
                FOREIGN KEY (otp_id) REFERENCES patient_otps(id)
            );

            CREATE TABLE IF NOT EXISTS uploaded_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                uploader_user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(id),
                FOREIGN KEY (uploader_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS external_prescriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )

        cur = conn.execute("SELECT COUNT(*) AS c FROM medicines")
        if cur.fetchone()["c"] == 0:
            conn.executemany(
                """
                INSERT INTO medicines (brand_name, generic_name, indications, standard_dosage, precautions)
                VALUES (?, ?, ?, ?, ?)
                """,
                MEDICINES,
            )
        conn.commit()


def create_session(user_id, role):
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = now + timedelta(hours=SESSION_HOURS)
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, role, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (token, user_id, role, expires.isoformat() + "Z", now.isoformat() + "Z"),
        )
        conn.commit()
    return token, expires.isoformat() + "Z"


def auth_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return jsonify({"error": "Missing bearer token"}), 401
            token = header.split(" ", 1)[1]
            with closing(get_db()) as conn:
                session = conn.execute(
                    "SELECT * FROM sessions WHERE token = ?", (token,)
                ).fetchone()
                if not session:
                    return jsonify({"error": "Invalid session"}), 401
                if parse_iso(session["expires_at"]) < datetime.utcnow():
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
                    return jsonify({"error": "Session expired"}), 401

                user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
                if not user:
                    return jsonify({"error": "User not found"}), 401

                if role and user["role"] != role:
                    return jsonify({"error": "Forbidden"}), 403

                request.current_user = dict(user)
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def doctor_record(conn, user_id):
    return conn.execute("SELECT * FROM doctors WHERE user_id = ?", (user_id,)).fetchone()


def patient_record(conn, user_id):
    return conn.execute("SELECT * FROM patients WHERE user_id = ?", (user_id,)).fetchone()


def pharmacist_record(conn, user_id):
    return conn.execute("SELECT * FROM pharmacists WHERE user_id = ?", (user_id,)).fetchone()


def has_doctor_access(conn, doctor_id, patient_id):
    grant = conn.execute(
        """
        SELECT * FROM doctor_access_grants
        WHERE doctor_id = ? AND patient_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (doctor_id, patient_id),
    ).fetchone()
    if not grant:
        return False
    return parse_iso(grant["expires_at"]) > datetime.utcnow()


def log_action(conn, action, success=1, doctor_id=None, patient_id=None, pharmacist_id=None, details=None, expires_at=None):
    conn.execute(
        """
        INSERT INTO access_logs (doctor_id, patient_id, pharmacist_id, action, success, details, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (doctor_id, patient_id, pharmacist_id, action, success, details, now_iso(), expires_at),
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "MedSetu"})


@app.post("/api/register")
def register():
    data = request.get_json(force=True)
    role = data.get("role")
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()

    if role not in {"doctor", "pharmacist", "patient"}:
        return jsonify({"error": "Invalid role"}), 400
    if not email or not password or not full_name:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        with closing(get_db()) as conn:
            # Use PBKDF2 for compatibility with environments missing hashlib.scrypt.
            password_hash = generate_password_hash(password, method="pbkdf2:sha256")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (email, password_hash, role, now_iso()),
            )
            user_id = cur.lastrowid

            if role == "doctor":
                reg = (data.get("medical_registration_number") or "").strip()
                spec = (data.get("specialization") or "").strip()
                if not reg:
                    raise ValueError("Medical registration number is required")
                conn.execute(
                    """
                    INSERT INTO doctors (user_id, full_name, medical_registration_number, specialization)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, full_name, reg, spec),
                )
            elif role == "pharmacist":
                lic = (data.get("license_number") or "").strip()
                pharmacy = (data.get("pharmacy_name") or "").strip()
                if not lic:
                    raise ValueError("Pharmacy license number is required")
                conn.execute(
                    """
                    INSERT INTO pharmacists (user_id, full_name, pharmacy_name, license_number)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, full_name, pharmacy, lic),
                )
            else:
                mobile = (data.get("mobile") or "").strip()
                dob = (data.get("dob") or "").strip()
                gender = (data.get("gender") or "").strip()
                allergies = data.get("allergies") or []
                chronic_conditions = data.get("chronic_conditions") or []
                if not mobile:
                    raise ValueError("Mobile number is required")
                conn.execute(
                    """
                    INSERT INTO patients (user_id, full_name, mobile, dob, gender, allergies, chronic_conditions)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        full_name,
                        mobile,
                        dob,
                        gender,
                        json.dumps(allergies),
                        json.dumps(chronic_conditions),
                    ),
                )

            conn.commit()
            token, expires = create_session(user_id, role)
            return jsonify({"message": "Registered", "token": token, "session_expires_at": expires, "role": role})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email/mobile/license/registration already exists"}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/login")
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    with closing(get_db()) as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        if user["role"] == "doctor":
            reg = (data.get("medical_registration_number") or "").strip()
            if not reg:
                return jsonify({"error": "Medical registration number is mandatory for doctor login"}), 400
            doctor = doctor_record(conn, user["id"])
            if not doctor or doctor["medical_registration_number"] != reg:
                return jsonify({"error": "Invalid medical registration number"}), 401

        if user["role"] == "pharmacist":
            lic = (data.get("license_number") or "").strip()
            if not lic:
                return jsonify({"error": "Pharmacy license number is mandatory for pharmacist login"}), 400
            pharmacist = pharmacist_record(conn, user["id"])
            if not pharmacist or pharmacist["license_number"] != lic:
                return jsonify({"error": "Invalid pharmacy license number"}), 401

    token, expires = create_session(user["id"], user["role"])
    return jsonify(
        {
            "message": "Logged in",
            "token": token,
            "session_expires_at": expires,
            "role": user["role"],
            "user": {"id": user["id"], "email": user["email"]},
        }
    )


@app.post("/api/logout")
@auth_required()
def logout():
    header = request.headers.get("Authorization", "")
    token = header.split(" ", 1)[1]
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    return jsonify({"message": "Logged out"})


@app.get("/api/me")
@auth_required()
def me():
    user = request.current_user
    with closing(get_db()) as conn:
        profile = {}
        if user["role"] == "doctor":
            d = doctor_record(conn, user["id"])
            profile = dict(d) if d else {}
        elif user["role"] == "pharmacist":
            p = pharmacist_record(conn, user["id"])
            profile = dict(p) if p else {}
        else:
            pt = patient_record(conn, user["id"])
            profile = dict(pt) if pt else {}
        return jsonify({"user": {"id": user["id"], "email": user["email"], "role": user["role"]}, "profile": profile})


@app.get("/api/medicines")
@auth_required()
def medicines():
    with closing(get_db()) as conn:
        rows = conn.execute("SELECT * FROM medicines ORDER BY brand_name").fetchall()
        return jsonify({"medicines": [dict(r) for r in rows]})


@app.get("/api/doctor/patients/search")
@auth_required("doctor")
def doctor_search_patient():
    mobile = (request.args.get("mobile") or "").strip()
    if not mobile:
        return jsonify({"error": "mobile query param required"}), 400

    with closing(get_db()) as conn:
        patient = conn.execute("SELECT * FROM patients WHERE mobile = ?", (mobile,)).fetchone()
        if not patient:
            return jsonify({"error": "Patient not found"}), 404
        return jsonify(
            {
                "patient": {
                    "id": patient["id"],
                    "full_name": patient["full_name"],
                    "mobile": patient["mobile"],
                    "dob": patient["dob"],
                    "gender": patient["gender"],
                }
            }
        )


@app.post("/api/doctor/access/send-otp")
@auth_required("doctor")
def send_otp():
    data = request.get_json(force=True)
    patient_id = data.get("patient_id")
    if not patient_id:
        return jsonify({"error": "patient_id is required"}), 400

    with closing(get_db()) as conn:
        doctor = doctor_record(conn, request.current_user["id"])
        patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if not doctor or not patient:
            return jsonify({"error": "Doctor/patient not found"}), 404

        otp = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.utcnow() + timedelta(minutes=ACCESS_WINDOW_MINUTES)

        conn.execute(
            """
            INSERT INTO patient_otps (patient_id, doctor_id, otp_code, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, doctor["id"], otp, now_iso(), expires.isoformat() + "Z"),
        )
        log_action(
            conn,
            action="OTP_SENT",
            success=1,
            doctor_id=doctor["id"],
            patient_id=patient_id,
            details="Simulated OTP sent",
            expires_at=expires.isoformat() + "Z",
        )
        conn.commit()

        return jsonify(
            {
                "message": "OTP generated (simulation)",
                "otp": otp,
                "expires_at": expires.isoformat() + "Z",
                "valid_for_minutes": ACCESS_WINDOW_MINUTES,
            }
        )


@app.post("/api/doctor/access/verify-otp")
@auth_required("doctor")
def verify_otp():
    data = request.get_json(force=True)
    patient_id = data.get("patient_id")
    otp_code = (data.get("otp_code") or "").strip()

    if not patient_id or not otp_code:
        return jsonify({"error": "patient_id and otp_code are required"}), 400

    with closing(get_db()) as conn:
        doctor = doctor_record(conn, request.current_user["id"])
        otp = conn.execute(
            """
            SELECT * FROM patient_otps
            WHERE patient_id = ? AND doctor_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id, doctor["id"]),
        ).fetchone()

        if not otp:
            return jsonify({"error": "OTP not found"}), 404
        if otp["verified_at"] is not None:
            return jsonify({"error": "OTP already used"}), 400
        if parse_iso(otp["expires_at"]) < datetime.utcnow():
            log_action(conn, "OTP_VERIFY", success=0, doctor_id=doctor["id"], patient_id=patient_id, details="OTP expired")
            conn.commit()
            return jsonify({"error": "OTP expired"}), 400
        if otp["otp_code"] != otp_code:
            log_action(conn, "OTP_VERIFY", success=0, doctor_id=doctor["id"], patient_id=patient_id, details="OTP mismatch")
            conn.commit()
            return jsonify({"error": "Invalid OTP"}), 400

        now = datetime.utcnow()
        expiry = now + timedelta(minutes=ACCESS_WINDOW_MINUTES)

        conn.execute("UPDATE patient_otps SET verified_at = ? WHERE id = ?", (now_iso(), otp["id"]))
        conn.execute(
            """
            INSERT INTO doctor_access_grants (doctor_id, patient_id, otp_id, granted_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (doctor["id"], patient_id, otp["id"], now.isoformat() + "Z", expiry.isoformat() + "Z"),
        )
        log_action(
            conn,
            action="OTP_VERIFY",
            success=1,
            doctor_id=doctor["id"],
            patient_id=patient_id,
            details="Patient access granted",
            expires_at=expiry.isoformat() + "Z",
        )
        conn.commit()

        return jsonify({"message": "OTP verified", "access_expires_at": expiry.isoformat() + "Z"})


def get_patient_overview(conn, patient_id):
    patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    if not patient:
        return None

    prescriptions = conn.execute(
        """
        SELECT p.*, d.full_name as doctor_name, d.medical_registration_number
        FROM prescriptions p
        JOIN doctors d ON d.id = p.doctor_id
        WHERE p.patient_id = ?
        ORDER BY p.created_at DESC
        """,
        (patient_id,),
    ).fetchall()

    reports = conn.execute(
        """
        SELECT id, file_name, uploaded_at
        FROM uploaded_reports
        WHERE patient_id = ?
        ORDER BY uploaded_at DESC
        """,
        (patient_id,),
    ).fetchall()

    return {
        "profile": {
            "id": patient["id"],
            "full_name": patient["full_name"],
            "mobile": patient["mobile"],
            "dob": patient["dob"],
            "gender": patient["gender"],
            "allergies": json.loads(patient["allergies"] or "[]"),
            "chronic_conditions": json.loads(patient["chronic_conditions"] or "[]"),
        },
        "prescriptions": [
            {
                "prescription_id": p["prescription_id"],
                "doctor_id": p["doctor_id"],
                "doctor_name": p["doctor_name"],
                "doctor_reg_no": p["medical_registration_number"],
                "medicines": json.loads(p["medicines_json"]),
                "doctor_notes": p["doctor_notes"],
                "status": p["status"],
                "created_at": p["created_at"],
                "dispensed_at": p["dispensed_at"],
            }
            for p in prescriptions
        ],
        "reports": [dict(r) for r in reports],
    }


@app.get("/api/doctor/patient/<int:patient_id>/overview")
@auth_required("doctor")
def doctor_patient_overview(patient_id):
    with closing(get_db()) as conn:
        doctor = doctor_record(conn, request.current_user["id"])
        if not has_doctor_access(conn, doctor["id"], patient_id):
            log_action(conn, "PATIENT_OVERVIEW", success=0, doctor_id=doctor["id"], patient_id=patient_id, details="No active access")
            conn.commit()
            return jsonify({"error": "Access denied. OTP verification required or expired."}), 403

        payload = get_patient_overview(conn, patient_id)
        if not payload:
            return jsonify({"error": "Patient not found"}), 404

        log_action(conn, "PATIENT_OVERVIEW", success=1, doctor_id=doctor["id"], patient_id=patient_id, details="Overview viewed")
        conn.commit()
        return jsonify(payload)


@app.post("/api/doctor/patient/<int:patient_id>/reports")
@auth_required("doctor")
def doctor_upload_report(patient_id):
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    with closing(get_db()) as conn:
        doctor = doctor_record(conn, request.current_user["id"])
        if not has_doctor_access(conn, doctor["id"], patient_id):
            return jsonify({"error": "Access denied. OTP verification required or expired."}), 403

        safe_name = secure_filename(file.filename)
        stored_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}_{safe_name}"
        path = REPORTS_DIR / stored_name
        file.save(path)

        conn.execute(
            """
            INSERT INTO uploaded_reports (patient_id, uploader_user_id, file_name, file_path, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, request.current_user["id"], safe_name, str(path), now_iso()),
        )
        log_action(conn, "REPORT_UPLOAD", success=1, doctor_id=doctor["id"], patient_id=patient_id, details=safe_name)
        conn.commit()

    return jsonify({"message": "Report uploaded"})


@app.post("/api/doctor/prescriptions")
@auth_required("doctor")
def create_prescription():
    data = request.get_json(force=True)
    patient_id = data.get("patient_id")
    meds = data.get("medicines") or []
    doctor_notes = data.get("doctor_notes", "")
    digital_signature = data.get("digital_signature", "")

    if not patient_id or not meds:
        return jsonify({"error": "patient_id and medicines are required"}), 400

    with closing(get_db()) as conn:
        doctor = doctor_record(conn, request.current_user["id"])
        if not has_doctor_access(conn, doctor["id"], patient_id):
            return jsonify({"error": "Access denied. OTP verification required or expired."}), 403

        patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if not patient:
            return jsonify({"error": "Patient not found"}), 404

        medicine_rows = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT * FROM medicines").fetchall()
        }

        resolved_meds = []
        for item in meds:
            med_id = item.get("medicine_id")
            dosage = (item.get("dosage") or "").strip()
            if med_id not in medicine_rows:
                return jsonify({"error": f"Invalid medicine_id: {med_id}"}), 400
            med = medicine_rows[med_id]
            resolved_meds.append(
                {
                    "medicine_id": med_id,
                    "brand_name": med["brand_name"],
                    "generic_name": med["generic_name"],
                    "dosage": dosage or med["standard_dosage"],
                    "indications": med["indications"],
                    "standard_dosage": med["standard_dosage"],
                    "precautions": med["precautions"],
                }
            )

        prescription_id = f"RX-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2).upper()}"
        qr_payload = f"MEDSETU:{prescription_id}"

        conn.execute(
            """
            INSERT INTO prescriptions
            (prescription_id, doctor_id, patient_id, medicines_json, doctor_notes, digital_signature, status, created_at, qr_payload)
            VALUES (?, ?, ?, ?, ?, ?, 'Active', ?, ?)
            """,
            (
                prescription_id,
                doctor["id"],
                patient_id,
                json.dumps(resolved_meds),
                doctor_notes,
                digital_signature,
                now_iso(),
                qr_payload,
            ),
        )
        log_action(
            conn,
            action="PRESCRIPTION_CREATE",
            success=1,
            doctor_id=doctor["id"],
            patient_id=patient_id,
            details=prescription_id,
        )
        conn.commit()

        return jsonify({"message": "Prescription created", "prescription_id": prescription_id, "qr_payload": qr_payload})


@app.post("/api/pharmacist/prescriptions/lookup")
@auth_required("pharmacist")
def pharmacist_lookup():
    data = request.get_json(force=True)
    value = (data.get("value") or "").strip()
    if not value:
        return jsonify({"error": "value is required"}), 400

    prescription_id = value
    if value.startswith("MEDSETU:"):
        prescription_id = value.split(":", 1)[1]

    with closing(get_db()) as conn:
        row = conn.execute(
            """
            SELECT p.*, d.full_name AS doctor_name, d.medical_registration_number,
                   pt.full_name AS patient_name, pt.mobile AS patient_mobile
            FROM prescriptions p
            JOIN doctors d ON d.id = p.doctor_id
            JOIN patients pt ON pt.id = p.patient_id
            WHERE p.prescription_id = ?
            """,
            (prescription_id,),
        ).fetchone()

        if not row:
            return jsonify({"error": "Prescription not found"}), 404

        return jsonify(
            {
                "prescription": {
                    "prescription_id": row["prescription_id"],
                    "doctor_name": row["doctor_name"],
                    "doctor_reg": row["medical_registration_number"],
                    "patient_name": row["patient_name"],
                    "patient_mobile": row["patient_mobile"],
                    "medicines": json.loads(row["medicines_json"]),
                    "doctor_notes": row["doctor_notes"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "dispensed_at": row["dispensed_at"],
                    "pharmacist_id": row["pharmacist_id"],
                }
            }
        )


@app.post("/api/pharmacist/prescriptions/<prescription_id>/dispense")
@auth_required("pharmacist")
def pharmacist_dispense(prescription_id):
    with closing(get_db()) as conn:
        pharmacist = pharmacist_record(conn, request.current_user["id"])
        row = conn.execute(
            "SELECT * FROM prescriptions WHERE prescription_id = ?",
            (prescription_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Prescription not found"}), 404

        if row["status"] != "Active":
            log_action(
                conn,
                action="DISPENSE_ATTEMPT",
                success=0,
                pharmacist_id=pharmacist["id"],
                patient_id=row["patient_id"],
                details=f"Blocked for {prescription_id}; status={row['status']}",
            )
            conn.commit()
            return jsonify({"error": f"Prescription is {row['status']} and cannot be reopened"}), 400

        dispensed_time = now_iso()
        conn.execute(
            """
            UPDATE prescriptions
            SET status = 'Expired', dispensed_at = ?, pharmacist_id = ?
            WHERE prescription_id = ?
            """,
            (dispensed_time, pharmacist["id"], prescription_id),
        )
        log_action(
            conn,
            action="DISPENSED",
            success=1,
            pharmacist_id=pharmacist["id"],
            patient_id=row["patient_id"],
            details=prescription_id,
        )
        conn.commit()

        return jsonify({"message": "Marked as dispensed. Prescription is now expired.", "dispensed_at": dispensed_time})


@app.get("/api/patient/history")
@auth_required("patient")
def patient_history():
    with closing(get_db()) as conn:
        patient = patient_record(conn, request.current_user["id"])
        if not patient:
            return jsonify({"error": "Patient profile not found"}), 404

        prescriptions = conn.execute(
            """
            SELECT p.*, d.full_name AS doctor_name
            FROM prescriptions p
            JOIN doctors d ON d.id = p.doctor_id
            WHERE p.patient_id = ?
            ORDER BY p.created_at DESC
            """,
            (patient["id"],),
        ).fetchall()

        external = conn.execute(
            "SELECT * FROM external_prescriptions WHERE patient_id = ? ORDER BY uploaded_at DESC",
            (patient["id"],),
        ).fetchall()

        reports = conn.execute(
            "SELECT * FROM uploaded_reports WHERE patient_id = ? ORDER BY uploaded_at DESC",
            (patient["id"],),
        ).fetchall()

        timeline = []
        for p in prescriptions:
            timeline.append(
                {
                    "type": "prescription",
                    "timestamp": p["created_at"],
                    "title": f"Prescription {p['prescription_id']}",
                    "status": p["status"],
                    "doctor_name": p["doctor_name"],
                }
            )
        for e in external:
            timeline.append(
                {
                    "type": "external_upload",
                    "timestamp": e["uploaded_at"],
                    "title": f"External Prescription Uploaded: {e['file_name']}",
                    "status": "Uploaded",
                }
            )
        for r in reports:
            timeline.append(
                {
                    "type": "report",
                    "timestamp": r["uploaded_at"],
                    "title": f"Report Uploaded: {r['file_name']}",
                    "status": "Uploaded",
                }
            )

        timeline.sort(key=lambda x: x["timestamp"], reverse=True)

        return jsonify(
            {
                "patient": {
                    "id": patient["id"],
                    "full_name": patient["full_name"],
                    "mobile": patient["mobile"],
                    "allergies": json.loads(patient["allergies"] or "[]"),
                    "chronic_conditions": json.loads(patient["chronic_conditions"] or "[]"),
                },
                "prescriptions": [
                    {
                        "prescription_id": p["prescription_id"],
                        "doctor_name": p["doctor_name"],
                        "medicines": json.loads(p["medicines_json"]),
                        "doctor_notes": p["doctor_notes"],
                        "digital_signature": p["digital_signature"],
                        "status": p["status"],
                        "created_at": p["created_at"],
                        "dispensed_at": p["dispensed_at"],
                        "qr_payload": p["qr_payload"],
                    }
                    for p in prescriptions
                ],
                "timeline": timeline,
            }
        )


@app.get("/api/patient/access-logs")
@auth_required("patient")
def patient_access_logs():
    with closing(get_db()) as conn:
        patient = patient_record(conn, request.current_user["id"])
        logs = conn.execute(
            """
            SELECT l.*, d.full_name AS doctor_name, ph.full_name AS pharmacist_name
            FROM access_logs l
            LEFT JOIN doctors d ON d.id = l.doctor_id
            LEFT JOIN pharmacists ph ON ph.id = l.pharmacist_id
            WHERE l.patient_id = ?
            ORDER BY l.created_at DESC
            """,
            (patient["id"],),
        ).fetchall()

        return jsonify(
            {
                "logs": [
                    {
                        "id": r["id"],
                        "action": r["action"],
                        "success": bool(r["success"]),
                        "details": r["details"],
                        "doctor_name": r["doctor_name"],
                        "pharmacist_name": r["pharmacist_name"],
                        "created_at": r["created_at"],
                        "expires_at": r["expires_at"],
                    }
                    for r in logs
                ]
            }
        )


@app.post("/api/patient/external-prescriptions")
@auth_required("patient")
def upload_external_prescription():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    with closing(get_db()) as conn:
        patient = patient_record(conn, request.current_user["id"])
        safe_name = secure_filename(file.filename)
        stored_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}_{safe_name}"
        path = EXTERNAL_DIR / stored_name
        file.save(path)

        conn.execute(
            """
            INSERT INTO external_prescriptions (patient_id, file_name, file_path, uploaded_at)
            VALUES (?, ?, ?, ?)
            """,
            (patient["id"], safe_name, str(path), now_iso()),
        )
        conn.commit()

        return jsonify({"message": "External prescription uploaded"})


@app.get("/api/files/reports/<int:file_id>")
@auth_required()
def get_report_file(file_id):
    with closing(get_db()) as conn:
        report = conn.execute("SELECT * FROM uploaded_reports WHERE id = ?", (file_id,)).fetchone()
        if not report:
            return jsonify({"error": "File not found"}), 404

        user = request.current_user
        if user["role"] == "patient":
            patient = patient_record(conn, user["id"])
            if not patient or patient["id"] != report["patient_id"]:
                return jsonify({"error": "Forbidden"}), 403
        elif user["role"] == "doctor":
            doctor = doctor_record(conn, user["id"])
            if not has_doctor_access(conn, doctor["id"], report["patient_id"]):
                return jsonify({"error": "Forbidden. OTP access required."}), 403

        folder = str(Path(report["file_path"]).parent)
        filename = Path(report["file_path"]).name
        return send_from_directory(folder, filename, as_attachment=True, download_name=report["file_name"])


@app.get("/api/files/external/<int:file_id>")
@auth_required("patient")
def get_external_file(file_id):
    with closing(get_db()) as conn:
        patient = patient_record(conn, request.current_user["id"])
        row = conn.execute("SELECT * FROM external_prescriptions WHERE id = ?", (file_id,)).fetchone()
        if not row or row["patient_id"] != patient["id"]:
            return jsonify({"error": "File not found"}), 404

        folder = str(Path(row["file_path"]).parent)
        filename = Path(row["file_path"]).name
        return send_from_directory(folder, filename, as_attachment=True, download_name=row["file_name"])


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
else:
    init_db()
