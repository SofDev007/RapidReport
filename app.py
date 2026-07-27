from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
from psycopg2 import Error
from psycopg2.extras import RealDictCursor
import bcrypt
import os
import secrets
import math
import csv
import io
import time
import smtplib
import requests
import uuid
from email.message import EmailMessage
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from supabase import create_client

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rapidreport-secret-key-change-in-production')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/rapidreport_db')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_KEY else None
EVIDENCE_BUCKET = 'evidence'
EVIDENCE_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'mov', 'avi', 'webm', 'mkv'}
EVIDENCE_MAX_FILES = 5
EVIDENCE_MAX_SIZE_BYTES = 25 * 1024 * 1024

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Error as e:
        print(f"Database connection error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        print("Could not connect to database.")
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DO $$ BEGIN
                CREATE TYPE user_role AS ENUM ('user', 'admin');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        cursor.execute("""
            DO $$ BEGIN
                CREATE TYPE report_status AS ENUM ('pending', 'under_review', 'resolved', 'closed');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                email VARCHAR(120) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role user_role DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                report_id VARCHAR(20) UNIQUE NOT NULL,
                user_id INT,
                type_of_crime VARCHAR(100) NOT NULL,
                date_of_incident DATE NOT NULL,
                location VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                suspect_description TEXT,
                evidence_details TEXT,
                status report_status DEFAULT 'pending',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_messages (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(120) NOT NULL,
                message TEXT NOT NULL,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_evidence (
                id SERIAL PRIMARY KEY,
                report_id INT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                file_path VARCHAR(255) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                mime_type VARCHAR(100),
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_report ON report_evidence(report_id)")
        cursor.execute("""
            CREATE OR REPLACE FUNCTION set_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        cursor.execute("""
            CREATE OR REPLACE TRIGGER trg_reports_updated_at
            BEFORE UPDATE ON reports
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)
        conn.commit()
        print("Database initialized successfully.")
    except Error as e:
        print(f"Error initializing database: {e}")
    finally:
        cursor.close()
        conn.close()

def seed_admin():
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@rapidreport.com')
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('ADMIN_PASSWORD')
    generated_password = False
    if not admin_password:
        admin_password = secrets.token_urlsafe(18)
        generated_password = True
    conn = get_db_connection()
    if not conn:
        print("Could not connect to database to seed admin.")
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
        if cursor.fetchone():
            return
        cursor.execute("SELECT id FROM users WHERE email=%s OR username=%s", (admin_email, admin_username))
        if cursor.fetchone():
            return
        pw_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, 'admin')",
            (admin_username, admin_email, pw_hash)
        )
        conn.commit()
        if generated_password:
            print(f"Admin account seeded: {admin_email} / generated password: {admin_password}")
        else:
            print(f"Admin account seeded: {admin_email}")
    except Error as e:
        print(f"Error seeding admin account: {e}")
    finally:
        cursor.close()
        conn.close()

def ensure_evidence_bucket():
    if not supabase_client:
        print("Supabase Storage not configured (SUPABASE_URL/SUPABASE_SERVICE_KEY missing); evidence uploads disabled.")
        return
    try:
        supabase_client.storage.create_bucket(EVIDENCE_BUCKET, options={'public': False})
        print(f"Created Supabase Storage bucket: {EVIDENCE_BUCKET}")
    except Exception as e:
        if 'already exists' not in str(e).lower() and 'duplicate' not in str(e).lower():
            print(f"Error ensuring evidence bucket: {e}")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

def generate_report_id():
    import random, string
    return 'RR' + ''.join(random.choices(string.digits, k=8))

# --- Report escalation helpers ---

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
NOMINATIM_USER_AGENT = 'RapidReport/1.0 (crime reporting app)'
ESCALATION_THRESHOLD = 20

def geocode_location(location):
    """Geocode a free-text location via OpenStreetMap Nominatim.
    Returns (lat, lon) as floats, or (None, None) on any failure/no result."""
    try:
        # Nominatim usage policy: identify via User-Agent, max 1 request/second.
        time.sleep(1)
        resp = requests.get(
            NOMINATIM_URL,
            params={'q': location, 'format': 'json', 'limit': 1},
            headers={'User-Agent': NOMINATIM_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            print(f"Geocoding returned no results for location: {location!r}")
            return None, None
        return float(results[0]['lat']), float(results[0]['lon'])
    except Exception as e:
        print(f"Geocoding failed for location {location!r}: {e}")
        return None, None

def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def _csv_safe(value):
    """Neutralize CSV formula injection: report fields are user-supplied and the
    CSV is opened in spreadsheet apps by station staff. Prefix a leading formula
    trigger with a single quote so it's treated as literal text."""
    s = '' if value is None else str(value)
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        s = "'" + s
    return s

def send_station_email(station_email, station_name, reports_rows):
    """Build an in-memory CSV of reports_rows and email it to the station as an
    attachment via Gmail SMTP. Raises on any failure (caller handles it)."""
    email_address = os.environ.get('EMAIL_ADDRESS')
    email_password = os.environ.get('EMAIL_APP_PASSWORD')
    if not email_address or not email_password:
        raise RuntimeError('EMAIL_ADDRESS / EMAIL_APP_PASSWORD environment variables not set')

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    writer.writerow([
        'report_id', 'type_of_crime', 'date_of_incident', 'location',
        'description', 'suspect_description', 'evidence_details', 'submitted_at',
    ])
    for r in reports_rows:
        writer.writerow([_csv_safe(v) for v in (
            r['report_id'], r['type_of_crime'], r['date_of_incident'], r['location'],
            r['description'], r['suspect_description'], r['evidence_details'], r['submitted_at'],
        )])
    csv_bytes = buffer.getvalue().encode('utf-8')

    msg = EmailMessage()
    msg['Subject'] = f'RapidReport: {len(reports_rows)} new reports for {station_name}'
    msg['From'] = email_address
    msg['To'] = station_email
    msg.set_content(
        f'Attached are {len(reports_rows)} crime reports assigned to {station_name}.\n\n'
        f'This is an automated message from RapidReport.'
    )
    msg.add_attachment(csv_bytes, maintype='text', subtype='csv', filename='reports.csv')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(email_address, email_password)
        smtp.send_message(msg)

def process_report_escalation(conn, report_db_id, location):
    """Geocode a just-submitted report, assign the nearest police station, and
    batch-email that station once ESCALATION_THRESHOLD unsent reports accumulate.
    Self-contained and never raises, so it can never break report submission."""
    try:
        lat, lon = geocode_location(location)
        if lat is None or lon is None:
            # Leave latitude/longitude NULL; don't assign or escalate.
            return

        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reports SET latitude=%s, longitude=%s WHERE id=%s",
            (lat, lon, report_db_id),
        )
        conn.commit()

        dict_cursor = conn.cursor(cursor_factory=RealDictCursor)
        dict_cursor.execute("SELECT id, name, email, latitude, longitude FROM police_stations")
        stations = dict_cursor.fetchall()
        if not stations:
            print("No police stations configured; skipping station assignment.")
            return

        nearest, nearest_dist = None, None
        for s in stations:
            if s['latitude'] is None or s['longitude'] is None:
                continue
            d = haversine(lat, lon, s['latitude'], s['longitude'])
            if nearest_dist is None or d < nearest_dist:
                nearest, nearest_dist = s, d
        if nearest is None:
            return

        cursor.execute(
            "UPDATE reports SET assigned_station_id=%s WHERE id=%s",
            (nearest['id'], report_db_id),
        )
        conn.commit()

        dict_cursor.execute(
            "SELECT COUNT(*) AS cnt FROM reports WHERE assigned_station_id=%s AND sent_to_station=FALSE",
            (nearest['id'],),
        )
        unsent_count = dict_cursor.fetchone()['cnt']
        if unsent_count < ESCALATION_THRESHOLD:
            return

        dict_cursor.execute("""
            SELECT id, report_id, type_of_crime, date_of_incident, location, description,
                   suspect_description, evidence_details, submitted_at
            FROM reports
            WHERE assigned_station_id=%s AND sent_to_station=FALSE
            ORDER BY submitted_at ASC
            LIMIT %s
        """, (nearest['id'], ESCALATION_THRESHOLD))
        batch = dict_cursor.fetchall()

        try:
            send_station_email(nearest['email'], nearest['name'], batch)
            batch_ids = [r['id'] for r in batch]
            cursor.execute(
                "UPDATE reports SET sent_to_station=TRUE WHERE id = ANY(%s)",
                (batch_ids,),
            )
            conn.commit()
            print(f"Escalated {len(batch_ids)} reports to station "
                  f"{nearest['name']} ({nearest['email']}).")
        except Exception as e:
            # Leave sent_to_station=FALSE so the next report retries the batch.
            conn.rollback()
            print(f"Failed to email reports to station {nearest['name']}: {e}")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"Escalation processing failed for report id {report_db_id}: {e}")

def upload_evidence_files(conn, report_db_id, report_id, files):
    """Upload up to EVIDENCE_MAX_FILES evidence files to Supabase Storage and record
    them in report_evidence. Validates extension and size per file. Never raises -
    a failed file is skipped (with a flash message) rather than breaking submission."""
    if not supabase_client:
        if files:
            flash('Evidence upload is not configured; files were not saved.', 'error')
        return

    files = [f for f in files if f and f.filename][:EVIDENCE_MAX_FILES]
    if not files:
        return

    cursor = conn.cursor()
    for f in files:
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in EVIDENCE_ALLOWED_EXTENSIONS:
            flash(f'Skipped "{f.filename}": unsupported file type.', 'error')
            continue
        data = f.read()
        if len(data) > EVIDENCE_MAX_SIZE_BYTES:
            flash(f'Skipped "{f.filename}": exceeds 25MB limit.', 'error')
            continue
        try:
            storage_path = f"{report_id}/{uuid.uuid4().hex}.{ext}"
            supabase_client.storage.from_(EVIDENCE_BUCKET).upload(
                storage_path, data, {"content-type": f.mimetype or 'application/octet-stream'}
            )
            cursor.execute(
                "INSERT INTO report_evidence (report_id, file_path, file_name, mime_type) VALUES (%s, %s, %s, %s)",
                (report_db_id, storage_path, secure_filename(f.filename), f.mimetype),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f'Failed to upload "{f.filename}".', 'error')
            print(f"Evidence upload failed for report {report_id}, file {f.filename!r}: {e}")
    cursor.close()

@app.route('/')
def home():
    return render_template('index.html', user=session.get('username'))

@app.route('/about')
def about():
    return render_template('about.html', user=session.get('username'))

@app.route('/services')
def services():
    return render_template('services.html', user=session.get('username'))

@app.route('/blog')
def blog():
    return render_template('blog.html', user=session.get('username'))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()
        if not all([name, email, message]):
            flash('All fields are required.', 'error')
        else:
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO contact_messages (name, email, message) VALUES (%s, %s, %s)", (name, email, message))
                    conn.commit()
                    flash('Message sent successfully!', 'success')
                except Error as e:
                    print(f"DB error in contact: {e}")
                    flash('Error sending message. Please try again.', 'error')
                finally:
                    cursor.close()
                    conn.close()
            else:
                flash('Database unavailable.', 'error')
    return render_template('contact.html', user=session.get('username'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not all([username, email, password, confirm]):
            flash('All fields are required.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
        else:
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM users WHERE email=%s OR username=%s", (email, username))
                    if cursor.fetchone():
                        flash('Username or email already exists.', 'error')
                    else:
                        pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        cursor.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)", (username, email, pw_hash))
                        conn.commit()
                        flash('Account created! Please log in.', 'success')
                        return redirect(url_for('login'))
                except Error as e:
                    print(f"DB error in register: {e}")
                    flash('Registration failed. Please try again.', 'error')
                finally:
                    cursor.close()
                    conn.close()
            else:
                flash('Database unavailable.', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
                user = cursor.fetchone()
                if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['role'] = user['role']
                    flash(f'Welcome back, {user["username"]}!', 'success')
                    return redirect(url_for('admin_panel') if user['role'] == 'admin' else url_for('dashboard'))
                else:
                    flash('Invalid email or password.', 'error')
            except Error as e:
                print(f"DB error in login: {e}")
                flash('Login failed. Please try again.', 'error')
            finally:
                cursor.close()
                conn.close()
        else:
            flash('Database unavailable.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    reports = []
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM reports WHERE user_id=%s ORDER BY submitted_at DESC", (session['user_id'],))
            reports = cursor.fetchall()
        except Error as e:
            print(f"DB error in dashboard: {e}")
            flash('Error loading reports.', 'error')
        finally:
            cursor.close()
            conn.close()
    return render_template('dashboard.html', user=session.get('username'), reports=reports)

@app.route('/report', methods=['GET', 'POST'])
@login_required
def submit_report():
    if request.method == 'POST':
        crime_type = request.form.get('crime_type', '').strip()
        incident_date = request.form.get('incident_date', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        suspect_desc = request.form.get('suspect_description', '').strip()
        evidence = request.form.get('evidence_details', '').strip()
        if not all([crime_type, incident_date, location, description]):
            flash('Please fill all required fields.', 'error')
        else:
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    report_id = generate_report_id()
                    cursor.execute("""
                        INSERT INTO reports (report_id, user_id, type_of_crime, date_of_incident, location, description, suspect_description, evidence_details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (report_id, session['user_id'], crime_type, incident_date, location, description, suspect_desc, evidence))
                    report_db_id = cursor.fetchone()[0]
                    conn.commit()
                    # Geocode, assign nearest station, and escalate if threshold reached.
                    # Fully self-contained; never breaks the submission response.
                    process_report_escalation(conn, report_db_id, location)
                    upload_evidence_files(conn, report_db_id, report_id, request.files.getlist('evidence_files'))
                    flash(f'Report submitted! Your Report ID: {report_id}', 'success')
                    return redirect(url_for('dashboard'))
                except Error as e:
                    print(f"DB error in submit_report: {e}")
                    flash('Error submitting report. Please try again.', 'error')
                finally:
                    cursor.close()
                    conn.close()
            else:
                flash('Database unavailable.', 'error')
    return render_template('report.html', user=session.get('username'))

@app.route('/admin')
@admin_required
def admin_panel():
    conn = get_db_connection()
    reports = []
    stats = {'total': 0, 'pending': 0, 'under_review': 0, 'resolved': 0, 'closed': 0}
    users_count = 0
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT r.*, u.username FROM reports r LEFT JOIN users u ON r.user_id=u.id ORDER BY r.submitted_at DESC")
            reports = cursor.fetchall()
            for r in reports:
                stats['total'] += 1
                stats[r['status']] = stats.get(r['status'], 0) + 1
            cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role='user'")
            users_count = cursor.fetchone()['cnt']
        except Error as e:
            print(f"DB error in admin_panel: {e}")
            flash('Error loading admin data.', 'error')
        finally:
            cursor.close()
            conn.close()
    return render_template('admin.html', user=session.get('username'), reports=reports, stats=stats, users_count=users_count)

@app.route('/admin/report/<report_id>')
@admin_required
def admin_report_detail(report_id):
    conn = get_db_connection()
    if not conn:
        flash('Database unavailable.', 'error')
        return redirect(url_for('admin_panel'))
    report = None
    evidence = []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT r.*, u.username FROM reports r LEFT JOIN users u ON r.user_id=u.id WHERE r.report_id=%s",
            (report_id,),
        )
        report = cursor.fetchone()
        if not report:
            flash('Report not found.', 'error')
            return redirect(url_for('admin_panel'))

        cursor.execute(
            "SELECT * FROM report_evidence WHERE report_id=%s ORDER BY uploaded_at ASC",
            (report['id'],),
        )
        for row in cursor.fetchall():
            signed_url = None
            if supabase_client:
                try:
                    signed = supabase_client.storage.from_(EVIDENCE_BUCKET).create_signed_url(row['file_path'], 300)
                    signed_url = signed.get('signedURL') or signed.get('signed_url')
                except Exception as e:
                    print(f"Failed to sign URL for {row['file_path']}: {e}")
            evidence.append({**row, 'signed_url': signed_url})
    except Error as e:
        print(f"DB error in admin_report_detail: {e}")
        flash('Error loading report.', 'error')
        return redirect(url_for('admin_panel'))
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_report_detail.html', user=session.get('username'), report=report, evidence=evidence)

@app.route('/admin/update_status', methods=['POST'])
@admin_required
def update_status():
    report_id = request.form.get('report_id')
    new_status = request.form.get('status')
    valid_statuses = ['pending', 'under_review', 'resolved', 'closed']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'})
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE reports SET status=%s WHERE report_id=%s", (new_status, report_id))
            conn.commit()
            return jsonify({'success': True})
        except Error as e:
            return jsonify({'success': False, 'error': str(e)})
        finally:
            cursor.close()
            conn.close()
    return jsonify({'success': False, 'error': 'DB unavailable'})

if __name__ == '__main__':
    init_db()
    seed_admin()
    ensure_evidence_bucket()
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true')
    app.run(debug=debug_mode, port=5000)