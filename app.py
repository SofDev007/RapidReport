from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
from psycopg2 import Error
from psycopg2.extras import RealDictCursor
import bcrypt
import os
import secrets
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rapidreport-secret-key-change-in-production')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/rapidreport_db')

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
                    """, (report_id, session['user_id'], crime_type, incident_date, location, description, suspect_desc, evidence))
                    conn.commit()
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
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true')
    app.run(debug=debug_mode, port=5000)