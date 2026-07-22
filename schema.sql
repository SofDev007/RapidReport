CREATE DATABASE IF NOT EXISTS rapidreport_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE rapidreport_db;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('user', 'admin') DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reports table
CREATE TABLE IF NOT EXISTS reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    report_id VARCHAR(20) UNIQUE NOT NULL,
    user_id INT,
    type_of_crime VARCHAR(100) NOT NULL,
    date_of_incident DATE NOT NULL,
    location VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    suspect_description TEXT,
    evidence_details TEXT,
    status ENUM('pending', 'under_review', 'resolved', 'closed') DEFAULT 'pending',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Contact messages table
CREATE TABLE IF NOT EXISTS contact_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL,
    message TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create a default admin user
-- Password: Admin@1234  (change this after first login!)
-- Hash generated via bcrypt
INSERT IGNORE INTO users (username, email, password_hash, role)
VALUES (
    'admin',
    'admin@rapidreport.in',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36zLa.X2yxwmJv5phrBZa2i',
    'admin'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(submitted_at);
