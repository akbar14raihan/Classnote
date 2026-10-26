import os
import time

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, abort, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "ganti-secret-key-ini")

CATEGORIES = ["Materi", "Tugas", "Ujian", "Ide"]


# ---------- Database helpers ----------
def get_conn():
    """Buka koneksi ke PostgreSQL. Coba ulang beberapa kali sampai database siap."""
    for _ in range(15):
        try:
            return psycopg2.connect(
                host=os.getenv("DB_HOST", "db"),
                port=os.getenv("DB_PORT", "5432"),
                dbname=os.getenv("DB_NAME", "appdb"),
                user=os.getenv("DB_USER", "appuser"),
                password=os.getenv("DB_PASS", "apppass"),
                # Azure Database for PostgreSQL mewajibkan SSL: isi DB_SSLMODE=require
                sslmode=os.getenv("DB_SSLMODE", "prefer"),
            )
        except psycopg2.OperationalError:
            time.sleep(2)
    raise RuntimeError("Database tidak bisa dihubungi")


def query(sql, params=(), one=False):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or None)
            rows = cur.fetchall()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        conn.close()


def execute(sql, params=(), returning=False):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or None)
            row = cur.fetchone() if returning else None
        conn.commit()
        return row
    finally:
        conn.close()


def init_db():
    execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) UNIQUE NOT NULL,
            lecturer VARCHAR(100) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title VARCHAR(150) NOT NULL,
            content TEXT NOT NULL,
            category VARCHAR(20) NOT NULL DEFAULT 'Materi',
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    # Data awal supaya halaman tidak kosong saat pertama kali dibuka
    if query("SELECT COUNT(*) AS n FROM courses", one=True)["n"] == 0:
        row = execute(
            "INSERT INTO courses (name, lecturer) VALUES (%s, %s) RETURNING id",
            ("Komputasi Awan", "Tim Dosen"),
            returning=True,
        )
        execute(
            "INSERT INTO notes (course_id, title, content, category, pinned) "
            "VALUES (%s, %s, %s, %s, TRUE)",
            (
                row["id"],
                "Apa itu Docker?",
                "Docker membungkus aplikasi beserta kebutuhannya menjadi image, "
                "lalu menjalankannya sebagai container.\n"
                "Docker Compose menjalankan beberapa container sekaligus, "
                "misalnya aplikasi dan database.",
                "Materi",
            ),
        )


def clean(value, limit):
    return (value or "").strip()[:limit]


# ---------- Halaman ----------
@app.route("/")
def index():
    q = clean(request.args.get("q"), 100)
    course_id = request.args.get("course", type=int)
    category = request.args.get("category", "")

    where, params = [], []
    if q:
        where.append("(n.title ILIKE %s OR n.content ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    if course_id:
        where.append("n.course_id = %s")
        params.append(course_id)
    if category in CATEGORIES:
        where.append("n.category = %s")
        params.append(category)

    sql = (
        "SELECT n.*, c.name AS course_name FROM notes n "
        "JOIN courses c ON c.id = n.course_id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY n.pinned DESC, n.created_at DESC"

    notes = query(sql, params)
    courses = query("SELECT id, name FROM courses ORDER BY name")
    stats = query(
        "SELECT (SELECT COUNT(*) FROM notes) AS notes, "
        "(SELECT COUNT(*) FROM courses) AS courses, "
        "(SELECT COUNT(*) FROM notes WHERE pinned) AS pinned",
        one=True,
    )
    return render_template(
        "index.html",
        notes=notes,
        courses=courses,
        stats=stats,
        categories=CATEGORIES,
        q=q,
        course_id=course_id,
        category=category,
    )


@app.route("/notes/new", methods=["GET", "POST"])
def note_new():
    courses = query("SELECT id, name FROM courses ORDER BY name")
    if not courses:
        flash("Tambahkan mata kuliah dulu sebelum membuat catatan.", "warn")
        return redirect(url_for("courses_page"))

    if request.method == "POST":
        title = clean(request.form.get("title"), 150)
        content = clean(request.form.get("content"), 5000)
        category = request.form.get("category", "Materi")
        course_id = request.form.get("course_id", type=int)
        pinned = request.form.get("pinned") == "on"
        if title and content and course_id and category in CATEGORIES:
            row = execute(
                "INSERT INTO notes (course_id, title, content, category, pinned) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (course_id, title, content, category, pinned),
                returning=True,
            )
            flash("Catatan berhasil disimpan.", "ok")
            return redirect(url_for("note_detail", note_id=row["id"]))
        flash("Judul dan isi catatan wajib diisi.", "warn")

    return render_template(
        "note_form.html", note=None, courses=courses, categories=CATEGORIES
    )


@app.route("/notes/<int:note_id>")
def note_detail(note_id):
    note = query(
        "SELECT n.*, c.name AS course_name FROM notes n "
        "JOIN courses c ON c.id = n.course_id WHERE n.id = %s",
        (note_id,),
        one=True,
    )
    if not note:
        abort(404)
    return render_template("note_detail.html", note=note)


@app.route("/notes/<int:note_id>/edit", methods=["GET", "POST"])
def note_edit(note_id):
    note = query("SELECT * FROM notes WHERE id = %s", (note_id,), one=True)
    if not note:
        abort(404)
    courses = query("SELECT id, name FROM courses ORDER BY name")

    if request.method == "POST":
        title = clean(request.form.get("title"), 150)
        content = clean(request.form.get("content"), 5000)
        category = request.form.get("category", "Materi")
        course_id = request.form.get("course_id", type=int)
        pinned = request.form.get("pinned") == "on"
        if title and content and course_id and category in CATEGORIES:
            execute(
                "UPDATE notes SET course_id=%s, title=%s, content=%s, category=%s, "
                "pinned=%s, updated_at=NOW() WHERE id=%s",
                (course_id, title, content, category, pinned, note_id),
            )
            flash("Catatan berhasil diperbarui.", "ok")
            return redirect(url_for("note_detail", note_id=note_id))
        flash("Judul dan isi catatan wajib diisi.", "warn")

    return render_template(
        "note_form.html", note=note, courses=courses, categories=CATEGORIES
    )


@app.route("/notes/<int:note_id>/pin", methods=["POST"])
def note_pin(note_id):
    execute("UPDATE notes SET pinned = NOT pinned WHERE id = %s", (note_id,))
    return redirect(request.referrer or url_for("index"))


@app.route("/notes/<int:note_id>/delete", methods=["POST"])
def note_delete(note_id):
    execute("DELETE FROM notes WHERE id = %s", (note_id,))
    flash("Catatan dihapus.", "ok")
    return redirect(url_for("index"))


@app.route("/courses", methods=["GET", "POST"])
def courses_page():
    if request.method == "POST":
        name = clean(request.form.get("name"), 100)
        lecturer = clean(request.form.get("lecturer"), 100)
        if name:
            execute(
                "INSERT INTO courses (name, lecturer) VALUES (%s, %s) "
                "ON CONFLICT (name) DO NOTHING",
                (name, lecturer),
            )
            flash("Mata kuliah disimpan.", "ok")
        else:
            flash("Nama mata kuliah wajib diisi.", "warn")
        return redirect(url_for("courses_page"))

    courses = query(
        "SELECT c.id, c.name, c.lecturer, COUNT(n.id) AS total "
        "FROM courses c LEFT JOIN notes n ON n.course_id = c.id "
        "GROUP BY c.id, c.name, c.lecturer ORDER BY c.name"
    )
    return render_template("courses.html", courses=courses)


@app.route("/courses/<int:course_id>/delete", methods=["POST"])
def course_delete(course_id):
    execute("DELETE FROM courses WHERE id = %s", (course_id,))
    flash("Mata kuliah dan seluruh catatannya dihapus.", "ok")
    return redirect(url_for("courses_page"))


@app.route("/health")
def health():
    return {"status": "ok"}


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
