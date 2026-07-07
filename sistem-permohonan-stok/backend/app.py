from flask import Flask, request, jsonify, session, send_from_directory
import sqlite3
import hashlib
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "tukar-ni-kepada-rawak-panjang-untuk-produksi"  # PENTING: tukar untuk projek sebenar
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

UPLOAD_FOLDER = "uploads"
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

# ================= CORS MANUAL (support cookies/session) =================
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/<path:path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def handle_options(path=""):
    return jsonify({"message": "ok"}), 200

DB = "database.db"

# Kod pendaftaran rahsia untuk pegawai - tukar kod ni dan kongsi hanya dengan pegawai yang sah
KOD_PENDAFTARAN_PEGAWAI = "PKPJ2026"

# ================= CONNECT DB =================
def connect():
    return sqlite3.connect(DB)

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ================= INIT DATABASE =================
def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        nama_penuh TEXT,
        jawatan TEXT,
        role TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS permohonan_stok (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        item_name TEXT,
        qty_dipesan INTEGER,
        pemohon_nama TEXT,
        pemohon_jawatan TEXT,
        pemohon_tarikh TEXT,

        kod_pegawai_pengawal TEXT,
        kump_ptj TEXT,
        vot_dana TEXT,
        program_aktiviti TEXT,
        projek TEXT,
        setia TEXT,
        sub_setia TEXT,
        cp TEXT,
        kod_akaun TEXT,
        kod_item TEXT,
        harga_seunit REAL,
        amaun REAL,

        pegawai_meluluskan TEXT,
        qty_diluluskan INTEGER,
        baki_qty INTEGER,
        catatan TEXT,
        pelulus_nama TEXT,
        pelulus_jawatan TEXT,
        pelulus_tarikh TEXT,

        kemaskini_nama TEXT,
        kemaskini_jawatan TEXT,
        kemaskini_tarikh TEXT,

        penerima_nama TEXT,
        penerima_jawatan TEXT,
        penerima_tarikh TEXT,

        gambar TEXT,

        status TEXT DEFAULT 'PENDING'
    )
    """)

    conn.commit()

    # ================= JADUAL SEJARAH PERGERAKAN/SERAHAN STOK =================
    # Satu permohonan boleh ada BERBILANG rekod pergerakan (contoh: stor -> jabatan A -> jabatan B)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pergerakan_stok (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        permohonan_id INTEGER NOT NULL,

        qty_diserahkan INTEGER,

        diserah_oleh_nama TEXT,
        diserah_oleh_jawatan TEXT,

        diterima_oleh_nama TEXT,
        diterima_oleh_jawatan TEXT,

        lokasi_unit TEXT,
        catatan TEXT,
        tarikh TEXT,

        dicipta_pada TEXT,

        FOREIGN KEY (permohonan_id) REFERENCES permohonan_stok (id)
    )
    """)
    conn.commit()

    # MIGRASI: tambah kolum baharu kalau DB lama belum ada
    cur.execute("PRAGMA table_info(permohonan_stok)")
    existing_cols = [c[1] for c in cur.fetchall()]

    kolum_baharu = {
        "gambar": "TEXT",
        "kod_pegawai_pengawal": "TEXT",
        "kump_ptj": "TEXT",
        "vot_dana": "TEXT",
        "program_aktiviti": "TEXT",
        "projek": "TEXT",
        "setia": "TEXT",
        "sub_setia": "TEXT",
        "cp": "TEXT",
        "kod_akaun": "TEXT",
        "kod_item": "TEXT",
        "harga_seunit": "REAL",
        "amaun": "REAL",
    }

    for nama_kolum, jenis in kolum_baharu.items():
        if nama_kolum not in existing_cols:
            cur.execute(f"ALTER TABLE permohonan_stok ADD COLUMN {nama_kolum} {jenis}")
            conn.commit()

    # SEED default users kalau belum ada (untuk testing)
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        seed_users = [
            ("pemohon1", hash_password("password123"), "Ahmad bin Ali", "Penolong Pegawai Tadbir", "pemohon"),
            ("pelulus1", hash_password("password123"), "Zainal bin Abu", "Ketua Jabatan", "pelulus"),
            ("stor1", hash_password("password123"), "Siti binti Musa", "Penyelia Stor", "stor"),
        ]
        cur.executemany("""
            INSERT INTO users (username, password, nama_penuh, jawatan, role)
            VALUES (?, ?, ?, ?, ?)
        """, seed_users)
        conn.commit()

    conn.close()

init_db()

# ================= DECORATORS =================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"message": "Sila log masuk dahulu"}), 401
        return f(*args, **kwargs)
    return wrapper

def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return jsonify({"message": "Sila log masuk dahulu"}), 401
            if session.get("role") != role:
                return jsonify({"message": "Tidak dibenarkan untuk peranan anda"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ================= SERVE GAMBAR YANG DIMUAT NAIK =================
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ================= HOME =================
@app.route("/")
def home():
    return "🔥 SISTEM PERMOHONAN STOK RUNNING"

# ================= DAFTAR AKAUN PEGAWAI (PERLUKAN KOD PENDAFTARAN) =================
@app.route("/register-pegawai", methods=["POST"])
def register_pegawai():
    data = request.json

    username = data.get("username", "").strip()
    password = data.get("password", "")
    nama_penuh = data.get("nama_penuh", "").strip()
    jawatan = data.get("jawatan", "").strip()
    role = data.get("role", "")
    kod = data.get("kod_pendaftaran", "")

    if not username or not password or not nama_penuh or not jawatan or not role:
        return jsonify({"message": "Sila isi semua ruangan"}), 400

    # Hanya role pegawai yang dibenarkan daftar sendiri - TIDAK boleh jadi 'admin'
    if role not in ("pelulus", "stor"):
        return jsonify({"message": "Peranan tidak sah"}), 400

    if kod != KOD_PENDAFTARAN_PEGAWAI:
        return jsonify({"message": "Kod pendaftaran salah. Sila dapatkan kod daripada pentadbir sistem."}), 403

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    if cur.fetchone():
        conn.close()
        return jsonify({"message": "Username telah digunakan, sila pilih username lain"}), 400

    cur.execute("""
        INSERT INTO users (username, password, nama_penuh, jawatan, role)
        VALUES (?, ?, ?, ?, ?)
    """, (username, hash_password(password), nama_penuh, jawatan, role))

    conn.commit()
    conn.close()

    return jsonify({"message": "success"})

# ================= DAFTAR AKAUN GUEST/PEMOHON (SELF-SERVICE) =================
@app.route("/register", methods=["POST"])
def register():
    data = request.json

    username = data.get("username", "").strip()
    password = data.get("password", "")
    nama_penuh = data.get("nama_penuh", "").strip()
    jawatan = data.get("jawatan", "").strip()

    if not username or not password or not nama_penuh or not jawatan:
        return jsonify({"message": "Sila isi semua ruangan"}), 400

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    if cur.fetchone():
        conn.close()
        return jsonify({"message": "Username telah digunakan, sila pilih username lain"}), 400

    # Guest yang daftar sendiri SENTIASA role 'pemohon' - tak boleh pilih role lain
    cur.execute("""
        INSERT INTO users (username, password, nama_penuh, jawatan, role)
        VALUES (?, ?, ?, ?, 'pemohon')
    """, (username, hash_password(password), nama_penuh, jawatan))

    conn.commit()
    conn.close()

    return jsonify({"message": "success"})

# ================= LOG MASUK GUEST/PEMOHON (TANPA PASSWORD, NAMA SAHAJA) =================
@app.route("/guest-login", methods=["POST"])
def guest_login():
    data = request.json

    nama_penuh = data.get("nama_penuh", "").strip()
    jawatan = data.get("jawatan", "").strip() or "Pemohon"

    if not nama_penuh:
        return jsonify({"message": "Sila isi nama"}), 400

    # Guest tidak perlu akaun dalam DB - sesi dicipta terus
    session["user_id"] = 0
    session["nama_penuh"] = nama_penuh
    session["jawatan"] = jawatan
    session["role"] = "pemohon"

    return jsonify({
        "message": "success",
        "nama_penuh": nama_penuh,
        "jawatan": jawatan,
        "role": "pemohon"
    })

# ================= LOGIN (PEGAWAI - PERLUKAN PASSWORD) =================
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "")
    password = hash_password(data.get("password", ""))

    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT id, nama_penuh, jawatan, role FROM users WHERE username=? AND password=?", (username, password))
    user = cur.fetchone()
    conn.close()

    if user is None:
        return jsonify({"message": "Username atau kata laluan salah"}), 401

    session["user_id"] = user[0]
    session["nama_penuh"] = user[1]
    session["jawatan"] = user[2]
    session["role"] = user[3]

    return jsonify({
        "message": "success",
        "nama_penuh": user[1],
        "jawatan": user[2],
        "role": user[3]
    })

# ================= LOGOUT =================
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "logged out"})

# ================= SEMAK SESI SEMASA =================
@app.route("/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"message": "not logged in"}), 401

    return jsonify({
        "nama_penuh": session.get("nama_penuh"),
        "jawatan": session.get("jawatan"),
        "role": session.get("role")
    })

# ================= PERINGKAT 1: BUAT PERMOHONAN =================
@app.route("/permohonan", methods=["POST"])
@login_required
def buat_permohonan():
    # Guna form-data (bukan JSON) sebab ada fail gambar
    item_name = request.form["item_name"]
    qty_dipesan = int(request.form["qty_dipesan"])
    pemohon_nama = session.get("nama_penuh")
    pemohon_jawatan = session.get("jawatan")
    pemohon_tarikh = request.form.get("pemohon_tarikh") or datetime.now().strftime("%Y-%m-%d")

    # Kod dipertanggung / maklumat akaun (setiap permohonan boleh berbeza)
    kod_pegawai_pengawal = request.form.get("kod_pegawai_pengawal", "").strip()
    kump_ptj = request.form.get("kump_ptj", "").strip()
    vot_dana = request.form.get("vot_dana", "").strip()
    program_aktiviti = request.form.get("program_aktiviti", "").strip()
    projek = request.form.get("projek", "").strip()
    setia = request.form.get("setia", "").strip()
    sub_setia = request.form.get("sub_setia", "").strip()
    cp = request.form.get("cp", "").strip()
    kod_akaun = request.form.get("kod_akaun", "").strip()
    kod_item = request.form.get("kod_item", "").strip()

    harga_seunit_raw = request.form.get("harga_seunit", "").strip()
    harga_seunit = float(harga_seunit_raw) if harga_seunit_raw else None
    amaun = round(harga_seunit * qty_dipesan, 2) if harga_seunit is not None else None

    gambar_filename = None
    file = request.files.get("gambar")
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        gambar_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{ext}"
        file.save(os.path.join(UPLOAD_FOLDER, secure_filename(gambar_filename)))

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO permohonan_stok
        (item_name, qty_dipesan, pemohon_nama, pemohon_jawatan, pemohon_tarikh, gambar,
         kod_pegawai_pengawal, kump_ptj, vot_dana, program_aktiviti, projek, setia, sub_setia, cp,
         kod_akaun, kod_item, harga_seunit, amaun, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (
        item_name, qty_dipesan, pemohon_nama, pemohon_jawatan, pemohon_tarikh, gambar_filename,
        kod_pegawai_pengawal, kump_ptj, vot_dana, program_aktiviti, projek, setia, sub_setia, cp,
        kod_akaun, kod_item, harga_seunit, amaun
    ))

    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    return jsonify({"message": "success", "id": new_id})

# ================= SENARAI SEMUA PERMOHONAN =================
@app.route("/senarai", methods=["GET"])
@login_required
def senarai():
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM permohonan_stok ORDER BY id DESC")
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]

    conn.close()

    return jsonify([dict(zip(cols, row)) for row in rows])

# ================= PERINGKAT 2: KELULUSAN (hanya role 'pelulus') =================
@app.route("/kelulusan/<int:id>", methods=["PUT"])
@role_required("pelulus")
def kelulusan(id):

    data = request.json

    pegawai_meluluskan = data["pegawai_meluluskan"]
    qty_diluluskan = int(data["qty_diluluskan"])
    catatan = data.get("catatan", "")
    pelulus_nama = session.get("nama_penuh")
    pelulus_jawatan = session.get("jawatan")
    pelulus_tarikh = data.get("pelulus_tarikh") or datetime.now().strftime("%Y-%m-%d")
    keputusan = data.get("keputusan", "DILULUSKAN")

    if keputusan == "DITOLAK" and not catatan.strip():
        return jsonify({"message": "Sebab penolakan wajib diisi dalam ruangan catatan"}), 400

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT qty_dipesan FROM permohonan_stok WHERE id=?", (id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return jsonify({"message": "not found"}), 404

    qty_dipesan = row[0]
    baki_qty = qty_dipesan - qty_diluluskan

    cur.execute("""
    UPDATE permohonan_stok
    SET pegawai_meluluskan=?, qty_diluluskan=?, baki_qty=?, catatan=?,
        pelulus_nama=?, pelulus_jawatan=?, pelulus_tarikh=?, status=?
    WHERE id=?
    """, (
        pegawai_meluluskan, qty_diluluskan, baki_qty, catatan,
        pelulus_nama, pelulus_jawatan, pelulus_tarikh, keputusan, id
    ))

    conn.commit()
    conn.close()

    return jsonify({"message": "success", "status": keputusan})

# ================= PERINGKAT 3: KEMASKINI REKOD (semua pengguna log masuk) =================
@app.route("/kemaskini/<int:id>", methods=["PUT"])
@login_required
def kemaskini(id):

    kemaskini_nama = session.get("nama_penuh")
    kemaskini_jawatan = session.get("jawatan")
    data = request.json or {}
    kemaskini_tarikh = data.get("kemaskini_tarikh") or datetime.now().strftime("%Y-%m-%d")

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT status FROM permohonan_stok WHERE id=?", (id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return jsonify({"message": "not found"}), 404

    if row[0] != "DILULUSKAN":
        conn.close()
        return jsonify({"message": "Permohonan belum diluluskan"}), 400

    cur.execute("""
    UPDATE permohonan_stok
    SET kemaskini_nama=?, kemaskini_jawatan=?, kemaskini_tarikh=?, status='DIKEMASKINI'
    WHERE id=?
    """, (kemaskini_nama, kemaskini_jawatan, kemaskini_tarikh, id))

    conn.commit()
    conn.close()

    return jsonify({"message": "success", "status": "DIKEMASKINI"})

# ================= PERINGKAT 4: PERAKUAN PENERIMAAN (mana-mana user log masuk) =================
@app.route("/penerimaan/<int:id>", methods=["PUT"])
@login_required
def penerimaan(id):

    penerima_nama = session.get("nama_penuh")
    penerima_jawatan = session.get("jawatan")
    data = request.json or {}
    penerima_tarikh = data.get("penerima_tarikh") or datetime.now().strftime("%Y-%m-%d")

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT status FROM permohonan_stok WHERE id=?", (id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return jsonify({"message": "not found"}), 404

    if row[0] != "DIKEMASKINI":
        conn.close()
        return jsonify({"message": "Rekod belum dikemaskini"}), 400

    cur.execute("""
    UPDATE permohonan_stok
    SET penerima_nama=?, penerima_jawatan=?, penerima_tarikh=?, status='DITERIMA'
    WHERE id=?
    """, (penerima_nama, penerima_jawatan, penerima_tarikh, id))

    conn.commit()
    conn.close()

    return jsonify({"message": "success", "status": "DITERIMA"})

# ================= TAMBAH REKOD PERGERAKAN/SERAHAN STOK =================
@app.route("/pergerakan/<int:id>", methods=["POST"])
@login_required
def tambah_pergerakan(id):
    data = request.json or {}

    diterima_oleh_nama = data.get("diterima_oleh_nama", "").strip()
    diterima_oleh_jawatan = data.get("diterima_oleh_jawatan", "").strip()
    lokasi_unit = data.get("lokasi_unit", "").strip()
    catatan = data.get("catatan", "").strip()
    tarikh = data.get("tarikh") or datetime.now().strftime("%Y-%m-%d")

    qty_raw = data.get("qty_diserahkan")
    qty_diserahkan = int(qty_raw) if qty_raw not in (None, "") else None

    if not diterima_oleh_nama:
        return jsonify({"message": "Nama penerima wajib diisi"}), 400

    diserah_oleh_nama = session.get("nama_penuh")
    diserah_oleh_jawatan = session.get("jawatan")

    conn = connect()
    cur = conn.cursor()

    # Pastikan permohonan wujud
    cur.execute("SELECT id FROM permohonan_stok WHERE id=?", (id,))
    if cur.fetchone() is None:
        conn.close()
        return jsonify({"message": "Permohonan tidak dijumpai"}), 404

    cur.execute("""
    INSERT INTO pergerakan_stok
        (permohonan_id, qty_diserahkan, diserah_oleh_nama, diserah_oleh_jawatan,
         diterima_oleh_nama, diterima_oleh_jawatan, lokasi_unit, catatan, tarikh, dicipta_pada)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id, qty_diserahkan, diserah_oleh_nama, diserah_oleh_jawatan,
        diterima_oleh_nama, diterima_oleh_jawatan, lokasi_unit, catatan, tarikh,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    return jsonify({"message": "success", "id": new_id})

# ================= SENARAI SEJARAH PERGERAKAN/SERAHAN STOK =================
@app.route("/pergerakan/<int:id>", methods=["GET"])
@login_required
def senarai_pergerakan(id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM pergerakan_stok
        WHERE permohonan_id=?
        ORDER BY id ASC
    """, (id,))
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]

    conn.close()

    return jsonify([dict(zip(cols, row)) for row in rows])

# ================= PAPAR SATU REKOD PENUH =================
@app.route("/permohonan/<int:id>", methods=["GET"])
@login_required
def get_permohonan(id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM permohonan_stok WHERE id=?", (id,))
    row = cur.fetchone()
    cols = [desc[0] for desc in cur.description]

    conn.close()

    if row is None:
        return jsonify({"message": "not found"}), 404

    return jsonify(dict(zip(cols, row)))

# ================= EDIT PERMOHONAN =================
@app.route("/permohonan/<int:id>", methods=["PUT"])
@login_required
def edit_permohonan(id):
    data = request.json or {}

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT status FROM permohonan_stok WHERE id=?", (id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return jsonify({"message": "not found"}), 404

    item_name = data.get("item_name", "").strip() if data.get("item_name") else None
    qty_dipesan_raw = data.get("qty_dipesan")
    qty_dipesan = int(qty_dipesan_raw) if qty_dipesan_raw not in (None, "") else None
    pemohon_tarikh = data.get("pemohon_tarikh")

    if not item_name or qty_dipesan is None:
        conn.close()
        return jsonify({"message": "Sila isi semua ruangan wajib"}), 400

    kod_pegawai_pengawal = data.get("kod_pegawai_pengawal", "").strip()
    kump_ptj = data.get("kump_ptj", "").strip()
    vot_dana = data.get("vot_dana", "").strip()
    program_aktiviti = data.get("program_aktiviti", "").strip()
    projek = data.get("projek", "").strip()
    setia = data.get("setia", "").strip()
    sub_setia = data.get("sub_setia", "").strip()
    cp = data.get("cp", "").strip()
    kod_akaun = data.get("kod_akaun", "").strip()
    kod_item = data.get("kod_item", "").strip()

    harga_seunit_raw = data.get("harga_seunit", "")
    harga_seunit = float(harga_seunit_raw) if harga_seunit_raw not in (None, "") else None
    amaun = round(harga_seunit * qty_dipesan, 2) if harga_seunit is not None else None

    cur.execute("""
        UPDATE permohonan_stok
        SET item_name=?, qty_dipesan=?, pemohon_tarikh=?,
            kod_pegawai_pengawal=?, kump_ptj=?, vot_dana=?, program_aktiviti=?,
            projek=?, setia=?, sub_setia=?, cp=?, kod_akaun=?, kod_item=?,
            harga_seunit=?, amaun=?
        WHERE id=?
    """, (
        item_name, qty_dipesan, pemohon_tarikh,
        kod_pegawai_pengawal, kump_ptj, vot_dana, program_aktiviti,
        projek, setia, sub_setia, cp, kod_akaun, kod_item,
        harga_seunit, amaun, id
    ))

    conn.commit()
    conn.close()

    return jsonify({"message": "success"})

# ================= PADAM PERMOHONAN =================
@app.route("/permohonan/<int:id>", methods=["DELETE"])
@login_required
def padam_permohonan(id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT gambar FROM permohonan_stok WHERE id=?", (id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return jsonify({"message": "not found"}), 404

    gambar_filename = row[0]

    # Padam rekod pergerakan berkaitan dahulu (sebab foreign key)
    cur.execute("DELETE FROM pergerakan_stok WHERE permohonan_id=?", (id,))
    cur.execute("DELETE FROM permohonan_stok WHERE id=?", (id,))

    conn.commit()
    conn.close()

    # Padam fail gambar kalau ada, jangan biarkan sampah dalam folder uploads
    if gambar_filename:
        try:
            file_path = os.path.join(UPLOAD_FOLDER, gambar_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    return jsonify({"message": "success"})

# ================= RUN =================
if __name__ == "__main__":
    print("🔥 SISTEM PERMOHONAN STOK STARTING...")
    app.run(debug=False, use_reloader=False)