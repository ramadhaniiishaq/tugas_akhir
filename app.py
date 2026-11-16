
from flask import Flask, render_template, url_for, redirect, request,session, send_from_directory, abort,flash
from flask_mysqldb import MySQL, MySQLdb
import bcrypt
import os
import uuid
from secrets import token_hex
from datetime import date

# ============================================================
#  KONFIGURASI
# ============================================================
app = Flask(__name__)
app.secret_key = token_hex(16)
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'db_archive'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB per request

# ============ KUOTA PENYIMPANAN ============
STORAGE_QUOTA_BYTES = 500 * 1024 * 1024 * 1024  # 500 GB
app.config['STORAGE_QUOTA'] = STORAGE_QUOTA_BYTES

ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'zip', 'rar'
}

MAX_FILES_PER_BATCH = 20

mysql = MySQL(app)


# ============================================================
#  HELPER FUNCTIONS
# ============================================================
def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def human_size(num):
    if not num:
        return "0 B"
    num = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


app.jinja_env.filters['filesize'] = human_size


def storage_info(terpakai_bytes):
    """Hitung info penyimpanan: terpakai, sisa, total, persen."""
    total = float(app.config['STORAGE_QUOTA'])
    terpakai = float(terpakai_bytes or 0)
    sisa = max(total - terpakai, 0)
    persen = round((terpakai / total) * 100, 2) if total > 0 else 0.0
    return {
        'total': total,
        'terpakai': terpakai,
        'sisa': sisa,
        'persen': min(persen, 100),
        'persen_sisa': max(round(100 - persen, 2), 0),
    }


def get_total_ukuran_admin(id_admin):
    """Total ukuran semua file milik admin (via user)."""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(file.ukuran), 0) AS total
        FROM file
        JOIN folder ON file.id_folder = folder.id
        JOIN user   ON folder.id_user = user.id
        WHERE user.id_admin = %s
    """, (id_admin,))
    total = float(cur.fetchone()['total'] or 0)
    cur.close()
    return total


def get_total_ukuran_user(id_user):
    """Total ukuran semua file milik user."""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(file.ukuran), 0) AS total
        FROM file
        JOIN folder ON file.id_folder = folder.id
        WHERE folder.id_user = %s
    """, (id_user,))
    total = float(cur.fetchone()['total'] or 0)
    cur.close()
    return total


# ============================================================
#  AUTH
# ============================================================
@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    gagal1 = None
    if request.method == 'POST':
        nama = request.form['name']
        password = request.form['password'].encode('utf-8')

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM admin WHERE name = %s", (nama,))
        admin = cur.fetchone()
        cur.execute("SELECT * FROM user WHERE nama = %s", (nama,))
        user = cur.fetchone()
        cur.close()

        if admin and bcrypt.checkpw(password, admin['password'].encode('utf-8')):
            session.permanent = True
            session['role'] = 'admin'
            session['id_admin'] = admin['id']
            session['username'] = admin['username']
            session['name'] = admin['name']
            session['jabatan'] = admin['jabatan']
            return redirect(url_for('dashboard'))

        elif user and bcrypt.checkpw(password, user['password'].encode('utf-8')):
            if user['status'] != 'aktif':
                gagal1 = "Akun Anda nonaktif. Hubungi admin."
            else:
                session.permanent = True
                session['role'] = 'user'
                session['id_user'] = user['id']
                session['nama'] = user['nama']
                session['jabatan'] = user['jabatan']
                session['status'] = user['status']
                return redirect(url_for('user_dashboard'))
        else:
            gagal1 = "Password atau Name salah, jika belum punya akun silahkan daftar!!"

    return render_template('login.html', gagal1=gagal1)


@app.route('/seeder')
def seeder():
    username = 'bim'
    nama = 'bimu'
    password = '1234'
    jabatan = 'kabag kesra'

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    cursor = mysql.connection.cursor()
    cursor.execute(
        "INSERT IGNORE INTO admin (username,name,password,jabatan) VALUES (%s,%s,%s,%s)",
        (username, nama, hashed.decode('utf-8'), jabatan)
    )
    mysql.connection.commit()
    cursor.close()
    return "berhasil"


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ============================================================
#  DASHBOARD ADMIN
# ============================================================
@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    today = date.today()
    id_admin = session.get('id_admin')
    type_file = ('pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'csv')
    type_image = ('png', 'jpg', 'jpeg', 'gif', 'webp')
    type_video = ('mp4', 'avi', 'mkv')
    all_type = type_image + type_video + type_file

    cur = mysql.connection.cursor()
    cur.execute("""SELECT COUNT(*) AS image FROM file
        JOIN folder ON file.id_folder=folder.id
        JOIN user ON folder.id_user=user.id
        WHERE user.id_admin=%s AND file.type IN %s""", (id_admin, type_image))
    image = cur.fetchone()['image']

    cur.execute("""SELECT COUNT(*) AS video FROM file
        JOIN folder ON file.id_folder=folder.id
        JOIN user ON folder.id_user=user.id
        WHERE user.id_admin=%s AND file.type IN %s""", (id_admin, type_video))
    video = cur.fetchone()['video']

    cur.execute("""SELECT COUNT(*) AS semua FROM file
        JOIN folder ON file.id_folder=folder.id
        JOIN user ON folder.id_user=user.id
        WHERE user.id_admin=%s AND file.type IN %s""", (id_admin, all_type))
    semua = cur.fetchone()['semua']

    cur.execute("""SELECT COUNT(*) AS folders FROM folder
        JOIN user ON folder.id_user=user.id
        WHERE user.id_admin=%s""", (id_admin,))
    folders = cur.fetchone()['folders']

    cur.execute("""SELECT COUNT(*) AS files FROM file
        JOIN folder ON file.id_folder=folder.id
        JOIN user ON folder.id_user=user.id
        WHERE user.id_admin=%s AND file.type IN %s""", (id_admin, type_file))
    files = cur.fetchone()['files']

    cur.execute("""SELECT file.nama, file.type, DATE_FORMAT(file.tanggal, '%%d-%%m-%%Y') AS tanggal
        FROM file
        JOIN folder ON file.id_folder=folder.id
        JOIN user ON folder.id_user=user.id
        WHERE user.id_admin=%s AND DATE(file.tanggal)=%s""", (id_admin, today))
    data = cur.fetchall()

    cur.execute("SELECT * FROM user WHERE id_admin=%s", (id_admin,))
    user = cur.fetchall()
    cur.close()

    # ============ INFO STORAGE ============
    total_ukuran_admin = get_total_ukuran_admin(id_admin)
    storage = storage_info(total_ukuran_admin)

    return render_template('admin/Beranda.html',
                           image=image, video=video, semua=semua,
                           folders=folders, files=files, data=data, user=user,
                           storage=storage)


# ============================================================
#  MANAJEMEN USER (ADMIN)
# ============================================================
@app.route('/user', methods=['GET', 'POST'])
def user():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    id_admin = session.get('id_admin')

    if request.method == 'POST':
        nama = request.form['nama']
        password = request.form['password']
        jabatan = request.form['jabatan']
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO user (id_admin,nama,password,jabatan) VALUES(%s,%s,%s,%s)",
            (id_admin, nama, hashed.decode('utf-8'), jabatan)
        )
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('user'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM user WHERE id_admin=%s", (id_admin,))
    semua = cur.fetchone()['total']

    cur.execute("SELECT COUNT(*) AS aktif FROM user WHERE status='aktif' AND id_admin=%s", (id_admin,))
    aktif = cur.fetchone()['aktif']

    cur.execute("SELECT COUNT(*) AS noaktif FROM user WHERE status='nonaktif' AND id_admin=%s", (id_admin,))
    nonaktif = cur.fetchone()['noaktif']

    cur.execute("SELECT * FROM admin")
    bag = cur.fetchall()

    cur.execute("SELECT * FROM user WHERE id_admin=%s ORDER BY id DESC", (id_admin,))
    use = cur.fetchall()
    cur.close()

    return render_template('admin/user.html', aktif=aktif, nonaktif=nonaktif,
                           semua=semua, bag=bag, use=use)


@app.route('/aksi/<int:id>', methods=['POST'])
def aksi(id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT status FROM user WHERE id=%s", (id,))
    user = cur.fetchone()
    if user:
        status_baru = 'nonaktif' if user['status'] == 'aktif' else 'aktif'
        cur.execute("UPDATE user SET status=%s WHERE id=%s", (status_baru, id))
        mysql.connection.commit()
    cur.close()
    return redirect(url_for('user'))


@app.route('/user/<int:id>/delete', methods=['POST'])
def user_delete(id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM user WHERE id=%s AND id_admin=%s",
                (id, session.get('id_admin')))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('user'))


# ============================================================
#  FILE (ADMIN VIEW)
# ============================================================
@app.route('/file', methods=['GET', 'POST'])
def file():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    id_admin = session.get('id_admin')

    # ============ LIST SEMUA FILE ============
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT
            file.id,
            file.nama   AS nama_file,
            file.type   AS type_file,
            file.ukuran AS ukuran_file,
            file.tanggal AS tanggal_file,
            folder.nama AS folder_nama,
            user.nama   AS nama_user
        FROM file
        JOIN folder ON file.id_folder = folder.id
        JOIN user   ON folder.id_user = user.id
        WHERE user.id_admin = %s
        ORDER BY file.tanggal DESC
    """, (id_admin,))
    data = cur.fetchall()

    # ============ TOTAL & JUMLAH ============
    total_ukuran = float(sum((float(r['ukuran_file'] or 0) for r in data)))
    jumlah_file = len(data)

    # ============ STATISTIK PER TIPE (COUNT) ============
    cur.execute("""
        SELECT
        (SELECT COUNT(*) FROM file JOIN folder ON file.id_folder=folder.id JOIN user ON folder.id_user=user.id WHERE type='pdf' AND id_admin=%s) AS pdf,
        (SELECT COUNT(*) FROM file JOIN folder ON file.id_folder=folder.id JOIN user ON folder.id_user=user.id WHERE type IN ('doc','docx') AND id_admin=%s) AS word,
        (SELECT COUNT(*) FROM file JOIN folder ON file.id_folder=folder.id JOIN user ON folder.id_user=user.id WHERE type IN ('xls','xlsx') AND id_admin=%s) AS excel,
        (SELECT COUNT(*) FROM file JOIN folder ON file.id_folder=folder.id JOIN user ON folder.id_user=user.id WHERE type IN ('jpg','jpeg') AND id_admin=%s) AS jpg,
        (SELECT COUNT(*) FROM file JOIN folder ON file.id_folder=folder.id JOIN user ON folder.id_user=user.id WHERE type='png' AND id_admin=%s) AS png,
        (SELECT COUNT(*) FROM file JOIN folder ON file.id_folder=folder.id JOIN user ON folder.id_user=user.id WHERE type='mp4' AND id_admin=%s) AS mp4
    """, (id_admin,) * 6)
    files = cur.fetchone()

    # ============ TOTAL UKURAN PER TIPE (untuk bar chart) ============
    cur.execute("""
        SELECT file.type, COUNT(*) AS jumlah,
               COALESCE(SUM(file.ukuran),0) AS total
        FROM file
        JOIN folder ON file.id_folder = folder.id
        JOIN user   ON folder.id_user = user.id
        WHERE user.id_admin = %s
        GROUP BY file.type
        ORDER BY total DESC
    """, (id_admin,))
    per_type_raw = cur.fetchall()

    # 🔧 Cast Decimal -> float supaya aman dari Decimal * float
    total_semua = float(sum((float(p['total'] or 0) for p in per_type_raw))) or 1.0
    per_type = []
    for p in per_type_raw:
        total_val = float(p['total'] or 0)
        per_type.append({
            'type': p['type'],
            'jumlah': int(p['jumlah'] or 0),
            'total': total_val,
            'persen': round(total_val * 100.0 / total_semua, 1),
        })

    # ============ FOLDER ============
    cur.execute("""SELECT COUNT(*) AS folder1 FROM folder
        JOIN user ON folder.id_user=user.id WHERE id_admin=%s""", (id_admin,))
    folder1 = cur.fetchone()['folder1']

    cur.execute("""
        SELECT folder.id, folder.nama AS folder_nama, user.nama AS user_nama,
            (SELECT COUNT(*) FROM file WHERE id_folder=folder.id) AS jml_file,
            (SELECT COALESCE(SUM(ukuran),0) FROM file WHERE id_folder=folder.id) AS total_ukuran
        FROM folder JOIN user ON folder.id_user=user.id WHERE id_admin=%s
    """, (id_admin,))
    folder_raw = cur.fetchall()
    folder = []
    for f in folder_raw:
        folder.append({
            'id': f['id'],
            'folder_nama': f['folder_nama'],
            'user_nama': f['user_nama'],
            'jml_file': f['jml_file'],
            'total_ukuran': float(f['total_ukuran'] or 0),
        })

    cur.close()

    # ============ INFO STORAGE ============
    storage = storage_info(total_ukuran)

    return render_template('admin/file.html',
                           files=files,
                           folder=folder,
                           folder1=folder1,
                           data=data,
                           total_ukuran=total_ukuran,
                           jumlah_file=jumlah_file,
                           per_type=per_type,
                           storage=storage)


# ============================================================
#  DASHBOARD USER
# ============================================================
@app.route('/u/dashboard')
def user_dashboard():
    if session.get('role') != 'user':
        return redirect(url_for('login'))

    id_user = session.get('id_user')
    cur = mysql.connection.cursor()
    cur.execute("""SELECT f.*, (SELECT COUNT(*) FROM file WHERE id_folder=f.id) AS jumlah_file
        FROM folder f WHERE f.id_user=%s ORDER BY f.tanggal DESC""", (id_user,))
    folders = cur.fetchall()
    total_file = sum((int(f['jumlah_file'] or 0) for f in folders))
    cur.close()

    total_ukuran_user = get_total_ukuran_user(id_user)
    storage = storage_info(total_ukuran_user)

    return render_template('user/dashboard.html',
                           folders=folders,
                           total_file=total_file,
                           storage=storage)


# ============================================================
#  FOLDER (USER)
# ============================================================
@app.route('/folder', methods=['GET', 'POST'])
def folder():
    if session.get('role') != 'user':
        return redirect(url_for('login'))

    id_user = session.get('id_user')

    if request.method == 'POST':
        nama = request.form.get('nama', '').strip()
        if nama:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO folder (id_user, nama) VALUES (%s,%s)", (id_user, nama))
            mysql.connection.commit()
            cur.close()
        return redirect(url_for('folder'))

    cur = mysql.connection.cursor()
    cur.execute("""SELECT f.*, (SELECT COUNT(*) FROM file WHERE id_folder=f.id) AS jumlah_file
        FROM folder f WHERE f.id_user=%s ORDER BY f.tanggal DESC""", (id_user,))
    folders = cur.fetchall()
    cur.close()
    return render_template('user/folder.html', folders=folders)


@app.route('/folder/<int:id>/rename', methods=['POST'])
def folder_rename(id):
    if session.get('role') != 'user':
        return redirect(url_for('login'))
    nama = request.form.get('nama', '').strip()
    if nama:
        cur = mysql.connection.cursor()
        cur.execute("UPDATE folder SET nama=%s WHERE id=%s AND id_user=%s",
                    (nama, id, session.get('id_user')))
        mysql.connection.commit()
        cur.close()
    return redirect(url_for('folder'))


@app.route('/folder/<int:id>/delete', methods=['POST'])
def folder_delete(id):
    if session.get('role') != 'user':
        return redirect(url_for('login'))

    id_user = session.get('id_user')
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM folder WHERE id=%s AND id_user=%s", (id, id_user))
    if not cur.fetchone():
        cur.close()
        abort(404)

    # hapus file fisik
    cur.execute("SELECT file FROM file WHERE id_folder=%s", (id,))
    for row in cur.fetchall():
        path = os.path.join(app.config['UPLOAD_FOLDER'], row['file'])
        if os.path.exists(path):
            os.remove(path)

    cur.execute("DELETE FROM folder WHERE id=%s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('folder'))


# ============================================================
#  FOLDER DETAIL + FILES
# ============================================================
@app.route('/folder/<int:id>')
def folder_detail(id):
    if session.get('role') != 'user':
        return redirect(url_for('login'))

    id_user = session.get('id_user')
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM folder WHERE id=%s AND id_user=%s", (id, id_user))
    f = cur.fetchone()
    if not f:
        cur.close()
        abort(404)

    cur.execute("SELECT * FROM file WHERE id_folder=%s ORDER BY tanggal DESC", (id,))
    files = cur.fetchall()

    total_ukuran = float(sum((float(fl['ukuran'] or 0) for fl in files)))
    per_type = {}
    for fl in files:
        t = (fl['type'] or 'lainnya').lower()
        per_type[t] = per_type.get(t, 0) + 1

    cur.close()

    # storage per-user (bukan hanya folder ini)
    total_ukuran_user = get_total_ukuran_user(id_user)
    storage = storage_info(total_ukuran_user)

    return render_template('user/folder_detail.html',
                           folder=f, files=files,
                           total_ukuran=total_ukuran,
                           per_type=per_type,
                           jumlah_file=len(files),
                           storage=storage)


# ============================================================
#  UPLOAD FILE (MULTIPLE)
# ============================================================
@app.route('/folder/<int:id>/upload', methods=['POST'])
def file_upload(id):
    if session.get('role') != 'user':
        return redirect(url_for('login'))

    id_user = session.get('id_user')
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM folder WHERE id=%s AND id_user=%s", (id, id_user))
    if not cur.fetchone():
        cur.close()
        abort(404)

    uploads = request.files.getlist('file')
    if not uploads or all(not u.filename for u in uploads):
        flash("Tidak ada file yang dipilih.", "warning")
        cur.close()
        return redirect(url_for('folder_detail', id=id))

    if len(uploads) > MAX_FILES_PER_BATCH:
        flash(f"Maksimal {MAX_FILES_PER_BATCH} file per upload.", "warning")
        cur.close()
        return redirect(url_for('folder_detail', id=id))

    # ============ CEK KUOTA ============
    terpakai = get_total_ukuran_user(id_user)
    sisa = app.config['STORAGE_QUOTA'] - terpakai
    if sisa <= 0:
        flash("❌ Kuota penyimpanan habis. Hapus file lama terlebih dahulu.", "danger")
        cur.close()
        return redirect(url_for('folder_detail', id=id))

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    berhasil = 0
    dilewati = []
    gagal = []
    kuota_penuh = []

    for up in uploads:
        if not up or up.filename == '':
            continue
        if not allowed_file(up.filename):
            dilewati.append(up.filename)
            continue

        try:
            up.seek(0, os.SEEK_END)
            file_size = up.tell()
            up.seek(0)

            if terpakai + file_size > app.config['STORAGE_QUOTA']:
                kuota_penuh.append(up.filename)
                continue

            ext = up.filename.rsplit('.', 1)[1].lower()
            unique = f"{uuid.uuid4().hex}.{ext}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], unique)
            up.save(path)
            size = os.path.getsize(path)
            nama_tampil = up.filename.rsplit('.', 1)[0]

            cur.execute("""INSERT INTO file (id_folder, file, nama, type, ukuran)
                VALUES (%s,%s,%s,%s,%s)""",
                (id, unique, nama_tampil, ext, size))
            berhasil += 1
            terpakai += size
        except Exception:
            gagal.append(up.filename)
            continue

    mysql.connection.commit()
    cur.close()

    if berhasil:
        flash(f"✅ {berhasil} file berhasil diupload.", "success")
    if dilewati:
        flash(f"⚠️ {len(dilewati)} file dilewati (tipe tidak didukung): "
              f"{', '.join(dilewati[:3])}"
              f"{'...' if len(dilewati) > 3 else ''}", "warning")
    if kuota_penuh:
        flash(f"💾 {len(kuota_penuh)} file tidak diupload karena kuota tidak cukup: "
              f"{', '.join(kuota_penuh[:3])}"
              f"{'...' if len(kuota_penuh) > 3 else ''}", "warning")
    if gagal:
        flash(f"❌ {len(gagal)} file gagal disimpan: "
              f"{', '.join(gagal[:3])}"
              f"{'...' if len(gagal) > 3 else ''}", "danger")

    return redirect(url_for('folder_detail', id=id))


# ============================================================
#  DOWNLOAD & DELETE FILE
# ============================================================
@app.route('/file/<int:id>/download')
def file_download(id):
    if session.get('role') not in ('user', 'admin'):
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("""SELECT file.*, folder.id_user FROM file
        JOIN folder ON file.id_folder=folder.id WHERE file.id=%s""", (id,))
    fl = cur.fetchone()
    cur.close()
    if not fl:
        abort(404)

    if session.get('role') == 'user' and fl['id_user'] != session.get('id_user'):
        abort(403)

    return send_from_directory(
        app.config['UPLOAD_FOLDER'], fl['file'],
        as_attachment=True,
        download_name=f"{fl['nama']}.{fl['type']}"
    )


@app.route('/file/<int:id>/delete', methods=['POST'])
def file_delete(id):
    if session.get('role') not in ('user', 'admin'):
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("""SELECT file.*, folder.id_user FROM file
        JOIN folder ON file.id_folder=folder.id WHERE file.id=%s""", (id,))
    fl = cur.fetchone()
    if not fl:
        cur.close()
        abort(404)

    if session.get('role') == 'user' and fl['id_user'] != session.get('id_user'):
        cur.close()
        abort(403)

    path = os.path.join(app.config['UPLOAD_FOLDER'], fl['file'])
    if os.path.exists(path):
        os.remove(path)
    cur.execute("DELETE FROM file WHERE id=%s", (id,))
    mysql.connection.commit()
    cur.close()

    if session.get('role') == 'user':
        return redirect(url_for('folder_detail', id=fl['id_folder']))
    return redirect(url_for('file'))


# ============================================================
#  PROFILE
# ============================================================
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'role' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    id_ = session.get('id_admin') if role == 'admin' else session.get('id_user')
    table = 'admin' if role == 'admin' else 'user'

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        new_pass = request.form.get('password', '').strip()
        if new_pass:
            hashed = bcrypt.hashpw(new_pass.encode('utf-8'), bcrypt.gensalt())
            cur.execute(f"UPDATE {table} SET password=%s WHERE id=%s",
                        (hashed.decode('utf-8'), id_))
            mysql.connection.commit()
            cur.close()
            return redirect(url_for('profile'))

    cur.execute(f"SELECT * FROM {table} WHERE id=%s", (id_,))
    data = cur.fetchone()
    cur.close()
    return render_template('profile.html', data=data, role=role)


@app.errorhandler(403)
def err403(e):
    return render_template('error.html', code=403, msg="Akses ditolak"), 403


@app.errorhandler(404)
def err404(e):
    return render_template('error.html', code=404, msg="Halaman tidak ditemukan"), 404


@app.errorhandler(500)
def err500(e):
    try:
        mysql.connection.rollback()
    except Exception:
        pass
    return render_template('error.html', code=500, msg="Kesalahan server internal"), 500


# ============================================================
#  MAIN
# ============================================================
if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)