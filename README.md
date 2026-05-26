# 🚨 RapidReport — Flask + MySQL Web Application

**Report. Protect. Empower.**

A full-stack crime reporting web application built with Python Flask and MySQL.

---

## 📁 Project Structure

```
rapidreport/
├── app.py                  ← Main Flask application
├── schema.sql              ← MySQL database schema
├── requirements.txt        ← Python dependencies
├── .env.example            ← Environment variables template
├── README.md               ← This file
├── templates/
│   ├── base.html           ← Base layout (navbar, footer, flash)
│   ├── index.html          ← Homepage
│   ├── about.html          ← About page
│   ├── services.html       ← Services page
│   ├── blog.html           ← Blog page
│   ├── contact.html        ← Contact page
│   ├── login.html          ← Login page
│   ├── register.html       ← Registration page
│   ├── dashboard.html      ← User dashboard
│   ├── report.html         ← Submit report form
│   └── admin.html          ← Admin panel
└── static/
    ├── css/style.css       ← All styles
    └── js/main.js          ← Animations, counters, navbar
```

---

## ⚙️ Setup Instructions

### Step 1 — Prerequisites
- Python 3.9+
- MySQL 8.0+
- VS Code (recommended)

### Step 2 — Clone & Install

```bash
# Navigate to the project folder in VS Code terminal
cd rapidreport

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 3 — Setup MySQL Database

```bash
# Login to MySQL
mysql -u root -p

# Run the schema file
source schema.sql
# OR
mysql -u root -p < schema.sql
```

### Step 4 — Configure Environment

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and fill in your MySQL password and a secret key
```

Then update `app.py` → `DB_CONFIG` with your MySQL password, OR set the `.env` variables.

### Step 5 — Run the App

```bash
python app.py
```

Visit: **http://localhost:5000**

---

## 🔐 Default Admin Login

| Field    | Value                  |
|----------|------------------------|
| Email    | admin@rapidreport.in   |
| Password | Admin@1234             |

> ⚠️ Change the admin password immediately after first login!

To create a new admin manually in MySQL:
```sql
UPDATE users SET role='admin' WHERE email='your@email.com';
```

---

## 🗄️ Database Tables

| Table              | Purpose                          |
|--------------------|----------------------------------|
| `users`            | Registered users with hashed passwords |
| `reports`          | All crime reports with status    |
| `contact_messages` | Messages from contact form       |

---

## 🧩 Features

- ✅ User Registration & Login (bcrypt password hashing)
- ✅ Session-based Authentication
- ✅ Anonymous Crime Report Submission
- ✅ User Dashboard (view own reports)
- ✅ Admin Panel (view all reports, update status)
- ✅ Contact Form (saves to DB)
- ✅ Animated Homepage (counters, scroll reveal)
- ✅ Fully Responsive Design
- ✅ MySQL backend with proper foreign keys

---

## 🛠️ Tech Stack

- **Backend:** Python Flask
- **Database:** MySQL (via mysql-connector-python)
- **Auth:** bcrypt password hashing + Flask sessions
- **Frontend:** HTML5, CSS3, Vanilla JS
- **Fonts:** Bebas Neue, DM Sans, Space Mono (Google Fonts)

---

© 2026 RapidReport
