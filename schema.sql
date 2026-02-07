-- Chamber-AI Database schema

-- 0. Users (Required for Authentication)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name TEXT,
    role TEXT DEFAULT 'staff',
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 1. Patients
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    nid TEXT UNIQUE,
    phone TEXT,
    age INTEGER,
    gender TEXT CHECK(gender IN ('Male', 'Female', 'Third-Gender')),
    address TEXT,
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- 2. Remedies (inventory)
CREATE TABLE IF NOT EXISTS remedies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    potency TEXT CHECK(potency IN ('1X','2X', '6X', '12X', '200', '30', '60')),     --here check is a constraint keyword 
    description TEXT,
    current_unit_price REAL NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. Visits
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    visit_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    chief_complaint TEXT,
    diagnosis TEXT,
    notes TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(id)
);

-- 4. Visit medicines (snapshot of price)
CREATE TABLE IF NOT EXISTS visit_medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL,
    remedy_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_snapshot REAL NOT NULL,
    line_total REAL NOT NULL,
    FOREIGN KEY (visit_id) REFERENCES visits(id),
    FOREIGN KEY (remedy_id) REFERENCES remedies(id)
);

-- 5. Payments
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL,
    consultation_fee REAL DEFAULT 0.00, 
    medicine_bill REAL DEFAULT 0.00,
    total_bill REAL NOT NULL,
    amount_paid REAL DEFAULT 0.00,
    due_amount REAL DEFAULT 0.00, 
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (visit_id) REFERENCES visits(id)
);


CREATE VIEW IF NOT EXISTS view_patient_history AS
SELECT
    v.id AS visit_id,
    p.id AS patient_id,
    p.name AS patient_name,
    v.visit_date,
    v.chief_complaint,
    v.diagnosis,
    pay.consultation_fee,
    pay.medicine_bill,
    pay.total_bill,
    pay.amount_paid,
    pay.due_amount,
    pay.status
FROM visits v
JOIN patients p ON v.patient_id = p.id
LEFT JOIN payments pay ON pay.visit_id = v.id;


CREATE VIEW IF NOT EXISTS view_daily_revenue AS
SELECT
    DATE(created_at) AS revenue_date,
    SUM(total_bill) AS total_bill_sum,
    SUM(amount_paid) AS amount_paid_sum
FROM payments
GROUP BY DATE(created_at)
ORDER BY revenue_date;


CREATE VIEW IF NOT EXISTS view_visit_medicines_detail AS
SELECT
    v.id AS visit_id,
    p.name AS patient_name,
    v.visit_date,
    r.name AS remedy_name,
    r.potency,
    vm.quantity,
    vm.unit_price_snapshot,
    vm.line_total
FROM visit_medicines vm
JOIN visits v ON vm.visit_id = v.id
JOIN patients p ON v.patient_id = p.id
JOIN remedies r ON vm.remedy_id = r.id;

-- VIEWS (Analytics)
CREATE VIEW IF NOT EXISTS today_stats AS
SELECT 
    (SELECT COUNT(*) FROM visits WHERE DATE(visit_date) = DATE('now')) as visits_today,
    (SELECT COUNT(*) FROM patients WHERE DATE(created_at) = DATE('now')) as patients_today;
