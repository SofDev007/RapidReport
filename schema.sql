-- Enum types
CREATE TYPE user_role AS ENUM ('user', 'admin');
CREATE TYPE report_status AS ENUM ('pending', 'under_review', 'resolved', 'closed');

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role user_role DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reports table
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
);

-- Auto-update updated_at on row change (replaces MySQL's ON UPDATE CURRENT_TIMESTAMP)
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reports_updated_at
BEFORE UPDATE ON reports
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Police stations table (report escalation targets)
CREATE TABLE IF NOT EXISTS police_stations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    address VARCHAR(255),
    latitude FLOAT,
    longitude FLOAT,
    email VARCHAR(120)
);

-- Escalation columns on the existing reports table
ALTER TABLE reports ADD COLUMN IF NOT EXISTS latitude FLOAT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS longitude FLOAT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS assigned_station_id INT REFERENCES police_stations(id);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS sent_to_station BOOLEAN DEFAULT FALSE;

-- Contact messages table
CREATE TABLE IF NOT EXISTS contact_messages (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL,
    message TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evidence files uploaded against a report (stored in Supabase Storage; file_path is the bucket key)
CREATE TABLE IF NOT EXISTS report_evidence (
    id SERIAL PRIMARY KEY,
    report_id INT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    file_path VARCHAR(255) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_evidence_report ON report_evidence(report_id);

-- Create a default admin user
-- Password: Admin@1234  (change this after first login!)
-- Hash generated via bcrypt
INSERT INTO users (username, email, password_hash, role)
VALUES (
    'admin',
    'admin@rapidreport.in',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36zLa.X2yxwmJv5phrBZa2i',
    'admin'
)
ON CONFLICT (email) DO NOTHING;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(submitted_at);
CREATE INDEX IF NOT EXISTS idx_reports_station ON reports(assigned_station_id);

-- Placeholder police stations. Replace the values below with real station data.
INSERT INTO police_stations (name, address, latitude, longitude, email) VALUES
    ('Station One',   '123 Placeholder Rd, City',   28.6139, 77.2090, 'station.one@example.com'),
    ('Station Two',   '456 Placeholder Ave, City',  19.0760, 72.8777, 'station.two@example.com'),
    ('Station Three', '789 Placeholder St, City',   12.9716, 77.5946, 'station.three@example.com'),
    ('Station Four',  '321 Placeholder Ln, City',   22.5726, 88.3639, 'station.four@example.com');
