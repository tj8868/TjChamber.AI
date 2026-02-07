#!/usr/bin/env python3
"""
🏥 CHAMBER AI - COMPLETE MANAGEMENT SYSTEM
FastAPI Application with SQLite Database
Integrated with 'schema.sql' for Patients, Visits, Inventory, and Analytics.
"""

from fastapi import FastAPI, HTTPException, Request, Depends, status, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import secrets
import jwt
import os
# from ml_service import ChatService

# ============================================================
# CONFIGURATION
# ============================================================

DB_PATH = "chamber.db"
SECRET_KEY = os.getenv("SECRET_KEY", "chamber-ai-super-secret-key-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Chat Service
# Pass DB Path so chatbot can read inventory
# chat_service = ChatService(DB_PATH)

app = FastAPI(
    title="Jahan Health Care",
    description="Homeopathic Clinic Management System",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# PYDANTIC MODELS
# ============================================================

class RemedyRequest(BaseModel):
    name: str
    barcode: Optional[str] = None
    potency: Optional[str] = None
    description: Optional[str] = None
    current_unit_price: float = 0.0
    stock_quantity: int = 0

class PatientRequest(BaseModel):
    name: str
    age: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None

class VisitRequest(BaseModel):
    patient_id: int
    visit_date: str
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    medicines: Optional[List[Dict[str, Any]]] = None
    total_amount: float = 0.0
    paid_amount: float = 0.0

# ============================================================
# DATABASE UTILS
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def init_database():
    """Initialize database and seed admin user"""
    # 1. Create Tables if DB doesn't exist OR tables are missing
    initialize_schema = False
    
    if not os.path.exists(DB_PATH):
        initialize_schema = True
    else:
        # Check if 'users' table exists to recover from failed init
        try:
            conn = get_db()
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cursor.fetchone():
                initialize_schema = True
            conn.close()
        except:
            initialize_schema = True

    if initialize_schema:
        print("📁 Initializing database from schema.sql...")
        try:
            conn = get_db()
            with open('schema.sql', 'r') as f:
                schema = f.read()
            conn.executescript(schema)
            
            # --- NEW FEATURE: Add Expenses Table manually if not in schema.sql ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL, -- Rent, Salary, Restocking, Utility, Other
                    amount REAL NOT NULL,
                    description TEXT,
                    expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    recorded_by INTEGER
                )
            """)
            # ---------------------------------------------------------------------

            conn.commit()
            conn.close()
            print("✅ Database tables created successfully!")
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            # Don't return here, attempt to seed anyway to see errors clearly

    # Ensure expenses table exists even if schema wasn't re-initialized
    try:
        conn = get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                recorded_by INTEGER
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning checking expenses table: {e}")

    # 2. Seed Users (Always run to ensure users exist)
    conn = get_db()
    try:
        # Seed Admin User
        admin_pwd = hash_password("admin123")
        try:
            conn.execute(
                "INSERT INTO users (username, hashed_password, full_name, role) VALUES (?, ?, ?, ?)",
                ("admin", admin_pwd, "System Administrator", "admin")
            )
            print("✅ Admin user created (admin / admin123)")
        except sqlite3.IntegrityError:
            conn.execute("UPDATE users SET hashed_password = ? WHERE username = ?", (admin_pwd, "admin"))
            print("↻ Admin user password reset (admin / admin123)")

        # Seed Doctor User
        doc_pwd = hash_password("doctor123")
        try:
            conn.execute(
                "INSERT INTO users (username, hashed_password, full_name, role) VALUES (?, ?, ?, ?)",
                ("doctor", doc_pwd, "Doctor Strange", "doctor")
            )
            print("✅ Doctor user created (doctor / doctor123)")
        except sqlite3.IntegrityError:
            conn.execute("UPDATE users SET hashed_password = ? WHERE username = ?", (doc_pwd, "doctor"))
            print("↻ Doctor user password reset (doctor / doctor123)")

        # Seed Staff User
        staff_pwd = hash_password("staff123")
        try:
            conn.execute(
                "INSERT INTO users (username, hashed_password, full_name, role) VALUES (?, ?, ?, ?)",
                ("staff", staff_pwd, "Front Desk", "staff")
            )
            print("✅ Staff user created (staff / staff123)")
        except sqlite3.IntegrityError:
            conn.execute("UPDATE users SET hashed_password = ? WHERE username = ?", (staff_pwd, "staff"))
            print("↻ Staff user password reset (staff / staff123)")
            
        conn.commit()
    except Exception as e:
        print(f"❌ User seeding failed: {e}")
    finally:
        conn.close()




# ============================================================
# AUTHENTICATION
# ============================================================

def create_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/login")
def login(data: dict):
    username = data.get("username")
    password = data.get("password")
    
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    
    if not user or user['hashed_password'] != hash_password(password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token({"sub": user['username'], "role": user['role'], "id": user['id']})
    return {"access_token": token, "type": "bearer", "username": username, "role": user['role']}

# ============================================================
# API ENDPOINTS - PATIENTS
# ============================================================

@app.get("/api/patients/generate-id")
def generate_patient_id(user: dict = Depends(get_current_user)):
    """Generate a unique ID for a new patient"""
    # Simple timestamp-based unique ID, or you could use UUID
    return {"unique_id": datetime.now().strftime("P%Y%m%d%H%M%S")}

@app.post("/api/patients")
def create_patient(patient: PatientRequest, user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        # Sanitize inputs for SQLite constraints
        gender = getattr(patient, 'gender', None)
        if not gender: gender = None
        
        nid = getattr(patient, 'nid', None)
        if not nid: nid = None  # Ensure NULL for uniqueness if empty

        cursor = conn.execute("""
            INSERT INTO patients (name, nid, phone, age, gender, address, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            patient.name, 
            nid, 
            patient.phone, 
            patient.age, 
            gender, 
            patient.address,
            user['id']
        ))
        conn.commit()
        pid = cursor.lastrowid
        return {"id": pid, "message": "Patient created successfully"}
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")
    finally:
        conn.close()

@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: int, patient: dict, user: dict = Depends(get_current_user)):
    # if user['role'] != 'admin':
    #     raise HTTPException(status_code=403, detail="Permission denied. Only Admins can update patient details.")
    
    conn = get_db()
    try:
        # Check if patient exists
        exists = conn.execute("SELECT id FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Patient not found")

        # Sanitize inputs
        gender = patient.get('gender')
        if not gender: gender = None
        
        nid = patient.get('nid')
        if not nid: nid = None

        conn.execute("""
            UPDATE patients 
            SET name=?, nid=?, phone=?, age=?, gender=?, address=?
            WHERE id=?
        """, (
            patient.get('name'), 
            nid, 
            patient.get('phone'), 
            patient.get('age'), 
            gender, 
            patient.get('address'),
            patient_id
        ))
        conn.commit()
        return {"message": "Patient updated successfully"}
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")
    finally:
        conn.close()

@app.get("/api/patients")
def list_patients(user: dict = Depends(get_current_user)):
    conn = get_db()
    patients = conn.execute("SELECT * FROM patients ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in patients]

# ============================================================
# API ENDPOINTS - INVENTORY (REMEDIES)
# ============================================================

@app.post("/api/remedies")
def create_remedy(remedy: RemedyRequest, user: dict = Depends(get_current_user)):
    if user['role'] not in ['admin', 'doctor']:
        raise HTTPException(status_code=403, detail="Permission denied. Only Doctors and Admins can manage inventory.")
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO remedies (name, barcode, potency, description, current_unit_price, stock_quantity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            remedy.name,
            remedy.barcode,
            remedy.potency,
            remedy.description,
            remedy.current_unit_price,
            remedy.stock_quantity
        ))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Remedy added"}
    finally:
        conn.close()

@app.put("/api/remedies/{remedy_id}")
def update_remedy(remedy_id: int, remedy: RemedyRequest, user: dict = Depends(get_current_user)):
    if user['role'] not in ['admin', 'doctor']:
        raise HTTPException(status_code=403, detail="Permission denied. Only Doctors and Admins can update inventory.")
    
    conn = get_db()
    try:
        conn.execute("""
            UPDATE remedies 
            SET name=?, barcode=?, potency=?, description=?, current_unit_price=?, stock_quantity=?
            WHERE id=?
        """, (
            remedy.name,
            remedy.barcode,
            remedy.potency,
            remedy.description,
            remedy.current_unit_price,
            remedy.stock_quantity,
            remedy_id
        ))
        conn.commit()
        return {"message": "Remedy updated"}
    finally:
        conn.close()

@app.delete("/api/remedies/{remedy_id}")
def delete_remedy(remedy_id: int, user: dict = Depends(get_current_user)):
    if user['role'] not in ['admin', 'doctor']:
        raise HTTPException(status_code=403, detail="Permission denied. Only Doctors and Admins can delete inventory.")
    
    conn = get_db()
    try:
        conn.execute("DELETE FROM remedies WHERE id = ?", (remedy_id,))
        conn.commit()
        return {"message": "Remedy deleted"}
    finally:
        conn.close()

@app.get("/api/remedies/search/barcode")
def search_remedy_by_barcode(barcode: str, user: dict = Depends(get_current_user)):
    """Search remedy by barcode, manual code, or QR code"""
    if not barcode or barcode.strip() == "":
        raise HTTPException(status_code=400, detail="Barcode cannot be empty")
    
    conn = get_db()
    try:
        remedy = conn.execute(
            "SELECT id, name, barcode, potency, description, current_unit_price, stock_quantity FROM remedies WHERE barcode = ?",
            (barcode.strip(),)
        ).fetchone()
        
        if not remedy:
            raise HTTPException(status_code=404, detail=f"No remedy found with barcode: {barcode}")
        
        return dict(remedy)
    finally:
        conn.close()

@app.get("/api/remedies")
def list_remedies(user: dict = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM remedies ORDER BY name").fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ============================================================
# API ENDPOINTS - VISITS
# ============================================================

@app.post("/api/visits")
def create_visit(visit: dict = Body(...), user: dict = Depends(get_current_user)):
    """Create new visit with optional patient details update"""
    conn = get_db()
    try:
        patient_id = visit.get('patient_id')
        
        # Validate patient exists
        patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if not patient:
            raise HTTPException(status_code=400, detail="Patient not found")
        
        # Update patient details if provided
        if visit.get('patient_name'):
            conn.execute(
                "UPDATE patients SET name = ? WHERE id = ?",
                (visit.get('patient_name'), patient_id)
            )
        
        if visit.get('patient_phone'):
            conn.execute(
                "UPDATE patients SET phone = ? WHERE id = ?",
                (visit.get('patient_phone'), patient_id)
            )
        
        if visit.get('patient_age'):
            conn.execute(
                "UPDATE patients SET age = ? WHERE id = ?",
                (int(visit.get('patient_age')), patient_id)
            )
        
        if visit.get('patient_gender'):
            conn.execute(
                "UPDATE patients SET gender = ? WHERE id = ?",
                (visit.get('patient_gender'), patient_id)
            )
        
        # Create visit
        visit_date = visit.get('visit_date') or datetime.now().isoformat()
        
        cursor = conn.execute("""
            INSERT INTO visits (patient_id, visit_date, chief_complaint, diagnosis, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (
            patient_id,
            visit_date,
            visit.get('chief_complaint', ''),
            visit.get('diagnosis', ''),
            visit.get('notes', '')
        ))
        visit_id = cursor.lastrowid
        
        # Add medicines
        med_cost = 0.0
        if visit.get('medicines'):
            for item in visit['medicines']:
                remedy = conn.execute(
                    "SELECT id, current_unit_price, stock_quantity FROM remedies WHERE id = ?",
                    (item['remedy_id'],)
                ).fetchone()
                
                if remedy:
                    price = float(remedy['current_unit_price'])
                    qty = int(item.get('quantity', 1))
                    
                    if remedy['stock_quantity'] < qty:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Insufficient stock for remedy {remedy['id']}"
                        )
                    
                    line_total = price * qty
                    med_cost += line_total
                    
                    conn.execute("""
                        INSERT INTO visit_medicines (visit_id, remedy_id, quantity, unit_price_snapshot, line_total)
                        VALUES (?, ?, ?, ?, ?)
                    """, (visit_id, item['remedy_id'], qty, price, line_total))
                    
                    conn.execute(
                        "UPDATE remedies SET stock_quantity = stock_quantity - ? WHERE id = ?",
                        (qty, item['remedy_id'])
                    )
        
        # Create payment record
        consultation_fee = float(visit.get('consultation_fee', 0))
        amount_paid = float(visit.get('amount_paid', 0))
        total_bill = consultation_fee + med_cost
        due_amount = total_bill - amount_paid
        
        if total_bill <= 0:
            status = 'n/a'
        elif due_amount <= 0:
            status = 'paid'
        elif amount_paid > 0:
            status = 'partially paid'
        else:
            status = 'pending'
        
        conn.execute("""
            INSERT INTO payments (visit_id, consultation_fee, medicine_bill, amount_paid, due_amount, total_bill, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            visit_id, consultation_fee, med_cost, amount_paid, due_amount, total_bill, status
        ))
        
        conn.commit()
        return {
            "message": "Visit created successfully",
            "visit_id": visit_id,
            "patient_id": patient_id
        }
    
    except HTTPException as he:
        conn.rollback()
        raise he
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"ERROR in create_visit: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating visit: {str(e)}")
    finally:
        conn.close()

@app.get("/api/visits")
def list_visits(user: dict = Depends(get_current_user)):
    conn = get_db()
    # Join with patients AND payments to show full details
    query = """
        SELECT 
            v.*, 
            p.name as patient_name,
            pay.total_bill,
            pay.amount_paid,
            pay.due_amount,
            pay.status as payment_status,
            pay.consultation_fee,
            pay.medicine_bill
        FROM visits v 
        JOIN patients p ON v.patient_id = p.id 
        LEFT JOIN payments pay ON pay.visit_id = v.id
        ORDER BY v.visit_date DESC
    """
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.put("/api/visits/{visit_id}")
def update_visit(visit_id: int, visit: dict, user: dict = Depends(get_current_user)):
    """Update entire visit including patient details - Admin only"""
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Permission denied. Only Admins can edit visits.")
    
    conn = get_db()
    try:
        # Check if visit exists
        visit_record = conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if not visit_record:
            raise HTTPException(status_code=404, detail="Visit not found")
        
        old_patient_id = visit_record['patient_id']
        new_patient_id = visit.get('patient_id')
        
        # If patient changed, validate new patient exists
        if new_patient_id and new_patient_id != old_patient_id:
            patient_exists = conn.execute(
                "SELECT id FROM patients WHERE id = ?", 
                (new_patient_id,)
            ).fetchone()
            if not patient_exists:
                raise HTTPException(status_code=400, detail="Patient not found")
        
        # If patient_id not provided, use existing one
        if not new_patient_id:
            new_patient_id = old_patient_id
        
        # Update patient name if provided
        if visit.get('patient_name'):
            conn.execute(
                "UPDATE patients SET name = ? WHERE id = ?",
                (visit.get('patient_name'), new_patient_id)
            )
        
        # Update patient phone if provided
        if visit.get('patient_phone'):
            conn.execute(
                "UPDATE patients SET phone = ? WHERE id = ?",
                (visit.get('patient_phone'), new_patient_id)
            )
        
        # Update patient age if provided
        if visit.get('patient_age'):
            conn.execute(
                "UPDATE patients SET age = ? WHERE id = ?",
                (int(visit.get('patient_age')), new_patient_id)
            )
        
        # Update patient gender if provided
        if visit.get('patient_gender'):
            conn.execute(
                "UPDATE patients SET gender = ? WHERE id = ?",
                (visit.get('patient_gender'), new_patient_id)
            )
        
        # Get all old visit medicines to restore stock
        old_medicines = conn.execute(
            "SELECT remedy_id, quantity FROM visit_medicines WHERE visit_id = ?",
            (visit_id,)
        ).fetchall()
        
        # Restore old stock
        for med in old_medicines:
            conn.execute(
                "UPDATE remedies SET stock_quantity = stock_quantity + ? WHERE id = ?",
                (med['quantity'], med['remedy_id'])
            )
        
        # Delete old visit medicines
        conn.execute("DELETE FROM visit_medicines WHERE visit_id = ?", (visit_id,))
        
        # Update visit details
        visit_date = visit.get('visit_date')
        if not visit_date:
            visit_date = datetime.now().isoformat()
        
        conn.execute("""
            UPDATE visits 
            SET patient_id=?, visit_date=?, chief_complaint=?, diagnosis=?, notes=?, recorded_by=?
            WHERE id=?
        """, (
            new_patient_id,
            visit_date,
            visit.get('chief_complaint', ''),
            visit.get('diagnosis', ''),
            visit.get('notes', ''),
            user['id'],
            visit_id
        ))
        
        # Re-insert medicines if provided
        med_cost = 0.0
        if 'medicines' in visit and visit['medicines']:
            for item in visit['medicines']:
                rem = conn.execute(
                    "SELECT id, current_unit_price, stock_quantity FROM remedies WHERE id = ?",
                    (item['remedy_id'],)
                ).fetchone()
                if rem:
                    price = float(rem['current_unit_price'])
                    qty = int(item.get('quantity', 1))
                    
                    if rem['stock_quantity'] < qty:
                        raise HTTPException(
                            status_code=400, 
                            detail=f"Insufficient stock for remedy {rem['id']}"
                        )
                    
                    line_total = price * qty
                    med_cost += line_total
                    
                    conn.execute("""
                        INSERT INTO visit_medicines (visit_id, remedy_id, quantity, unit_price_snapshot, line_total)
                        VALUES (?, ?, ?, ?, ?)
                    """, (visit_id, item['remedy_id'], qty, price, line_total))
                    
                    # Reduce stock
                    conn.execute(
                        "UPDATE remedies SET stock_quantity = stock_quantity - ? WHERE id = ?",
                        (qty, item['remedy_id'])
                    )
        
        # Update/Create payment record
        existing_payment = conn.execute(
            "SELECT * FROM payments WHERE visit_id=?", 
            (visit_id,)
        ).fetchone()
        
        consultation_fee = float(visit.get('consultation_fee', 0))
        amount_paid = float(visit.get('amount_paid', 0))
        medicine_bill = med_cost
        total_bill = consultation_fee + medicine_bill
        due_amount = total_bill - amount_paid
        
        # Determine payment status
        if total_bill <= 0:
            status = 'n/a'
        elif due_amount <= 0:
            status = 'paid'
        elif amount_paid > 0:
            status = 'partially paid'
        else:
            status = 'pending'
        
        if existing_payment:
            conn.execute("""
                UPDATE payments
                SET patient_id=?, consultation_fee=?, medicine_bill=?, amount_paid=?, 
                    due_amount=?, total_bill=?, status=?, recorded_by=?
                WHERE visit_id=?
            """, (
                new_patient_id, 
                consultation_fee, 
                medicine_bill, 
                amount_paid, 
                due_amount, 
                total_bill, 
                status,
                user['id'],
                visit_id
            ))
        else:
            conn.execute("""
                INSERT INTO payments 
                (visit_id, patient_id, consultation_fee, medicine_bill, amount_paid, due_amount, total_bill, status, recorded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                visit_id,
                new_patient_id,
                consultation_fee,
                medicine_bill,
                amount_paid,
                due_amount,
                total_bill,
                status,
                user['id']
            ))
        
        conn.commit()
        return {
            "message": "Visit updated successfully",
            "visit_id": visit_id,
            "patient_id": new_patient_id
        }
    
    except HTTPException as he:
        conn.rollback()
        raise he
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating visit: {str(e)}")
    finally:
        conn.close()

# ============================================================
# API ENDPOINTS - VIEWS / ANALYTICS
# ============================================================

@app.put("/api/visits/{visit_id}/payment")
def update_payment(visit_id: int, payment: dict, user: dict = Depends(get_current_user)):
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Permission denied. Only Admins can update billing.")
        
    conn = get_db()
    try:
        current = conn.execute("SELECT * FROM payments WHERE visit_id=?", (visit_id,)).fetchone()
        if not current: 
             raise HTTPException(404, "Visit payment not found")
        
        consult = float(payment.get('consultation_fee', current['consultation_fee']))
        med_bill = float(payment.get('medicine_bill', current['medicine_bill']))
        paid = float(payment.get('amount_paid', current['amount_paid']))
        
        total = consult + med_bill
        due = total - paid
        
        status = 'paid' if due <= 0 else 'partially paid'
        if total == 0: status = 'n/a'
        if paid == 0 and total > 0: status = 'pending'

        conn.execute("""
            UPDATE payments 
            SET consultation_fee=?, medicine_bill=?, total_bill=?, amount_paid=?, due_amount=?, status=?
            WHERE visit_id=?
        """, (consult, med_bill, total, paid, due, status, visit_id))
        conn.commit()
        return {"message": "Payment updated"}
    finally:
        conn.close()

@app.get("/api/reports/history")
def report_history(user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        # Check if view exists, else fallback to simple query
        rows = conn.execute("SELECT * FROM view_patient_history LIMIT 100").fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

@app.get("/api/reports/revenue")
def report_revenue(user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM view_daily_revenue").fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()

# --- NEW FINANCIAL ENDPOINTS ---

@app.get("/api/finance/summary")
def get_financial_summary(user: dict = Depends(get_current_user)):
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Access denied")

    conn = get_db()
    try:
        # 1. Income Breakdown (Based on billed amounts)
        income_query = """
            SELECT 
                SUM(consultation_fee) as total_consult,
                SUM(medicine_bill) as total_meds,
                SUM(amount_paid) as total_collected
            FROM payments
        """
        income = conn.execute(income_query).fetchone()

        # 2. Expenses Breakdown
        expense_query = """
            SELECT category, SUM(amount) as total 
            FROM expenses 
            GROUP BY category
        """
        expenses_rows = conn.execute(expense_query).fetchall()
        
        # Calculate totals
        inc_consult = income['total_consult'] or 0
        inc_meds = income['total_meds'] or 0
        total_collected = income['total_collected'] or 0
        
        total_expense = sum(row['total'] for row in expenses_rows)
        net_profit = total_collected - total_expense

        return {
            "income": {
                "consultation": inc_consult,
                "medicine": inc_meds,
                "total_collected": total_collected
            },
            "expenses": {
                "total": total_expense,
                "breakdown": [dict(row) for row in expenses_rows]
            },
            "net_profit": net_profit
        }
    finally:
        conn.close()

@app.post("/api/expenses")
def add_expense(expense: dict, user: dict = Depends(get_current_user)):
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Access denied")
    
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO expenses (category, amount, description, recorded_by)
            VALUES (?, ?, ?, ?)
        """, (
            expense.get('category'),
            expense.get('amount'),
            expense.get('description'),
            user['id']
        ))
        conn.commit()
        return {"message": "Expense recorded successfully"}
    finally:
        conn.close()

@app.get("/api/expenses")
def list_expenses(user: dict = Depends(get_current_user)):
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Access denied")
    conn = get_db()
    rows = conn.execute("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(row) for row in rows]
# -------------------------------

@app.get("/api/stats")
def dashboard_stats(user: dict = Depends(get_current_user)):
    """Get all dashboard statistics with clean direct queries"""
    conn = get_db()
    
    try:
        stats = {
            # Total counts (all time)
            "patients": conn.execute(
                "SELECT COUNT(*) as c FROM patients"
            ).fetchone()['c'],
            
            "visits": conn.execute(
                "SELECT COUNT(*) as c FROM visits"
            ).fetchone()['c'],
            
            "remedies": conn.execute(
                "SELECT COUNT(*) as c FROM remedies WHERE stock_quantity > 0"
            ).fetchone()['c'],
            
            # Today's counts
            "today_visits": conn.execute(
                "SELECT COUNT(*) as c FROM visits WHERE DATE(visit_date) = DATE('now')"
            ).fetchone()['c'],
            
            "today_new_patients": conn.execute(
                "SELECT COUNT(*) as c FROM patients WHERE DATE(created_at) = DATE('now')"
            ).fetchone()['c'],
            
            # This month's counts
            "month_visits": conn.execute(
                "SELECT COUNT(*) as c FROM visits WHERE strftime('%Y-%m', visit_date) = strftime('%Y-%m', 'now')"
            ).fetchone()['c'],
            
            "month_new_patients": conn.execute(
                "SELECT COUNT(*) as c FROM patients WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            ).fetchone()['c'],
            
            # Financial (bonus)
            "revenue_today": conn.execute(
                "SELECT COALESCE(SUM(total_bill), 0) as c FROM payments WHERE DATE(created_at) = DATE('now')"
            ).fetchone()['c'],
            
            "revenue_month": conn.execute(
                "SELECT COALESCE(SUM(total_bill), 0) as c FROM payments WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            ).fetchone()['c'],
            
            "outstanding_dues": conn.execute(
                "SELECT COALESCE(SUM(due_amount), 0) as c FROM payments WHERE status = 'pending'"
            ).fetchone()['c'],
            
            # Inventory
            "total_remedies": conn.execute(
                "SELECT COUNT(*) as c FROM remedies"
            ).fetchone()['c'],
            
            "out_of_stock": conn.execute(
                "SELECT COUNT(*) as c FROM remedies WHERE stock_quantity = 0"
            ).fetchone()['c'],
        }
        
        return stats
    
    finally:
        conn.close()

# ============================================================
# STATIC FRONTEND
# ============================================================

@app.get("/", response_class=HTMLResponse)
def serve_app():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chamber AI - Homeopathic Clinic Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #f0fdf4; }
        ::-webkit-scrollbar-thumb { background: #166534; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #14532d; }
    </style>
</head>
<body class="bg-green-50 text-gray-800 font-sans">
    <div id="app" class="min-h-screen flex flex-col">
        
        <!-- LOGIN SCREEN -->
        <div v-if="!token" class="flex-grow flex items-center justify-center bg-green-50">
            <div class="bg-white p-8 rounded-2xl shadow-2xl w-full max-w-md border border-green-100">
                <div class="text-center mb-6">
                    <h1 class="text-3xl font-bold bg-gradient-to-r from-green-700 to-emerald-600 bg-clip-text text-transparent">Chamber AI</h1>
                    <p class="text-gray-500 mt-2">Homeopathic Clinic Management</p>
                </div>
                
                <form @submit.prevent="login" class="space-y-4">
                    <input v-model="loginForm.username" placeholder="Username" class="w-full border border-green-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500">
                    <input v-model="loginForm.password" type="password" placeholder="Password" class="w-full border border-green-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500">
                    <button type="submit" class="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-2 rounded-lg">Login</button>
                </form>
            </div>
        </div>

        <!-- MAIN APP -->
        <div v-else class="flex-grow flex">
            <!-- Sidebar -->
            <aside class="w-64 bg-emerald-900 text-green-50 border-r border-emerald-800 p-6">
                <div class="flex items-center gap-3 mb-8">
                    <div class="w-8 h-8 rounded bg-green-500 flex items-center justify-center text-white">
                        <i class="fas fa-first-aid"></i>
                    </div>
                    <h2 class="text-xl font-bold">Chamber AI</h2>
                </div>
                
                <nav class="space-y-2">
                    <button @click="currentView = 'dashboard'" :class="currentView === 'dashboard' ? 'bg-emerald-700 text-white' : 'text-emerald-100 hover:bg-emerald-800'" class="w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition">
                        <i class="fas fa-home"></i> Dashboard
                    </button>
                    <button @click="currentView = 'patients'" :class="currentView === 'patients' ? 'bg-emerald-700 text-white' : 'text-emerald-100 hover:bg-emerald-800'" class="w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition">
                        <i class="fas fa-user-injured"></i> Patients
                    </button>
                    <button @click="currentView = 'visits'" :class="currentView === 'visits' ? 'bg-emerald-700 text-white' : 'text-emerald-100 hover:bg-emerald-800'" class="w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition">
                        <i class="fas fa-stethoscope"></i> Visits
                    </button>
                    <button @click="currentView = 'inventory'" :class="currentView === 'inventory' ? 'bg-emerald-700 text-white' : 'text-emerald-100 hover:bg-emerald-800'" class="w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition">
                        <i class="fas fa-leaf"></i> Inventory
                    </button>
                    <button @click="currentView = 'finance'" :class="currentView === 'finance' ? 'bg-emerald-700 text-white' : 'text-emerald-100 hover:bg-emerald-800'" class="w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition">
                        <i class="fas fa-coins"></i> Finance
                    </button>
                </nav>
                
                <div class="mt-auto pt-4 border-t border-emerald-800/50">
                    <button @click="logout" class="w-full text-left px-4 py-2 text-red-300 hover:bg-red-900/30 rounded transition">
                        <i class="fas fa-sign-out-alt"></i> Logout
                    </button>
                </div>
            </aside>

            <!-- Content Area -->
            <main class="flex-grow p-8 bg-green-50 overflow-y-auto">
                
                <!-- DASHBOARD VIEW -->
                <div v-if="currentView === 'dashboard'" class="max-w-7xl">
                    <h2 class="text-3xl font-bold mb-8 text-emerald-900">Dashboard Overview</h2>
                    
                    <div class="grid grid-cols-1 md:grid-cols-5 gap-6 mb-8">
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-gray-500 text-sm font-medium">Patients</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.patients }}</p>
                        </div>
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-gray-500 text-sm font-medium">Visits Today</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.today_visits }}</p>
                        </div>
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-gray-500 text-sm font-medium">New Patients Today</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.today_new_patients }}</p>
                        </div>
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-gray-500 text-sm font-medium">Visits This Month</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.month_visits }}</p>
                        </div>
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-gray-500 text-sm font-medium">Remedies</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.remedies }}</p>
                        </div>
                    </div>
                </div>

                <!-- PATIENTS VIEW -->
                <div v-if="currentView === 'patients'" class="max-w-7xl">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-3xl font-bold text-emerald-900">Patient Management</h2>
                        <button @click="showPatientModal = true" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-semibold">
                            <i class="fas fa-plus"></i> New Patient
                        </button>
                    </div>

                    <div v-if="showPatientModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-lg shadow-2xl">
                            <h3 class="text-xl font-bold mb-6">{{ editPatientId ? 'Edit Patient' : 'Register New Patient' }}</h3>
                            <form @submit.prevent="editPatientId ? updatePatient() : savePatient()" class="space-y-4">
                                <input v-model="patientForm.name" placeholder="Full Name" required class="w-full border border-gray-200 p-3 rounded-lg">
                                <input v-model="patientForm.age" type="number" placeholder="Age" class="w-full border border-gray-200 p-3 rounded-lg">
                                <select v-model="patientForm.gender" class="w-full border border-gray-200 p-3 rounded-lg">
                                    <option value="">Select Gender</option>
                                    <option value="Male">Male</option>
                                    <option value="Female">Female</option>
                                    <option value="Third-Gender">Other</option>
                                </select>
                                <input v-model="patientForm.phone" placeholder="Phone" class="w-full border border-gray-200 p-3 rounded-lg">
                                <input v-model="patientForm.nid" placeholder="NID" class="w-full border border-gray-200 p-3 rounded-lg">
                                <textarea v-model="patientForm.address" placeholder="Address" class="w-full border border-gray-200 p-3 rounded-lg h-24"></textarea>
                                <div class="flex justify-end gap-3">
                                    <button type="button" @click="closePatientModal()" class="px-4 py-2 text-gray-600">Cancel</button>
                                    <button type="submit" class="bg-emerald-600 text-white px-6 py-2 rounded-lg">{{ editPatientId ? 'Update Patient' : 'Save Patient' }}</button>
                                </div>
                            </form>
                        </div>
                    </div>

                    <div class="bg-white rounded-xl shadow-lg border border-green-100 overflow-x-auto">
                        <table class="w-full text-left">
                            <thead class="bg-green-50 border-b border-green-100">
                                <tr>
                                    <th class="p-5 font-bold">Name</th>
                                    <th class="p-5 font-bold">Age</th>
                                    <th class="p-5 font-bold">Phone</th>
                                    <th class="p-5 font-bold">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100">
                                <tr v-for="p in patients" :key="p.id">
                                    <td class="p-5">{{ p.name }}</td>
                                    <td class="p-5">{{ p.age || 'N/A' }}</td>
                                    <td class="p-5">{{ p.phone }}</td>
                                    <td class="p-5"><button type="button" @click="openPatientEditModal(p)" class="text-blue-600 hover:text-blue-800"><i class="fas fa-edit"></i></button></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- INVENTORY VIEW - FULL EXCEL CLONE -->
                <div v-if="currentView === 'inventory'" class="w-full">
                    <h2 class="text-3xl font-bold text-emerald-900 mb-6 px-6">Medicine Inventory</h2>
                    
                    <!-- Barcode Scanner Section -->
                    <div class="mx-6 mb-6 p-6 bg-blue-50 rounded-lg border border-blue-200">
                        <label class="block text-lg font-bold mb-3">🔍 Scan Medicine Barcode to Add to Inventory</label>
                        <div class="flex gap-2 mb-3">
                            <input 
                                v-model="barcodeInput" 
                                @keyup.enter="addMedicineToInventory"
                                type="text" 
                                placeholder="Scan barcode or QR code..." 
                                class="flex-1 border border-blue-300 p-3 rounded-lg text-lg"
                                autofocus
                            >
                            <button type="button" @click="addMedicineToInventory" class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold">Add</button>
                            <button type="button" @click="showManualAddModal = true" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-semibold">
                                <i class="fas fa-plus-circle"></i> Manual Add
                            </button>
                        </div>
                        <p v-if="barcodeMessage" :class="barcodeError ? 'text-red-600' : 'text-green-600'" class="text-sm mt-3 font-semibold">{{ barcodeMessage }}</p>
                    </div>

                    <!-- Manual Add Medicine Modal -->
                    <div v-if="showManualAddModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-md shadow-2xl">
                            <h3 class="text-2xl font-bold mb-6 text-emerald-900">Add Medicine Manually</h3>
                            <form @submit.prevent="submitManualMedicine" class="space-y-4">
                                <div>
                                    <label class="block text-sm font-semibold mb-2">Medicine Name *</label>
                                    <input 
                                        v-model="manualMedicineForm.name" 
                                        type="text" 
                                        placeholder="e.g., Arnica Montana" 
                                        required 
                                        class="w-full border border-gray-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    >
                                </div>
                                <div>
                                    <label class="block text-sm font-semibold mb-2">Barcode</label>
                                    <input 
                                        v-model="manualMedicineForm.barcode" 
                                        type="text" 
                                        placeholder="(Optional)" 
                                        class="w-full border border-gray-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    >
                                </div>
                                <div>
                                    <label class="block text-sm font-semibold mb-2">Potency</label>
                                    <select v-model="manualMedicineForm.potency" class="w-full border border-gray-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500">
                                        <option value="">Select Potency</option>
                                        <option value="30">30</option>
                                        <option value="200">200</option>
                                        <option value="1X">1X</option>
                                        <option value="6X">6X</option>
                                        <option value="12X">12X</option>
                                        <option value="30X">30X</option>
                                        <option value="1M">1M</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-sm font-semibold mb-2">Price (BDT)</label>
                                    <input 
                                        v-model="manualMedicineForm.current_unit_price" 
                                        type="number" 
                                        step="0.01" 
                                        placeholder="0.00" 
                                        class="w-full border border-gray-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    >
                                </div>
                                <div>
                                    <label class="block text-sm font-semibold mb-2">Stock Quantity</label>
                                    <input 
                                        v-model="manualMedicineForm.stock_quantity" 
                                        type="number" 
                                        placeholder="0" 
                                        class="w-full border border-gray-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                                    >
                                </div>
                                <div>
                                    <label class="block text-sm font-semibold mb-2">Description</label>
                                    <textarea 
                                        v-model="manualMedicineForm.description" 
                                        placeholder="(Optional)" 
                                        class="w-full border border-gray-200 p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 h-16"
                                    ></textarea>
                                </div>
                                <div class="flex justify-end gap-3 pt-4">
                                    <button 
                                        type="button" 
                                        @click="closeManualAddModal()" 
                                        class="px-6 py-2 text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50"
                                    >
                                        Cancel
                                    </button>
                                    <button 
                                        type="submit" 
                                        class="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-semibold"
                                    >
                                        Add Medicine
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                    
                    <!-- Excel-like Table - Full Width -->
                    <div class="bg-white border border-gray-300 overflow-x-auto">
                        <table class="w-full text-sm border-collapse">
                            <thead class="bg-emerald-100 sticky top-0">
                                <tr class="border-b-2 border-gray-400">
                                    <th class="border border-gray-300 p-3 text-left font-bold bg-emerald-50">Barcode</th>
                                    <th class="border border-gray-300 p-3 text-left font-bold bg-emerald-50">Medicine Name</th>
                                    <th class="border border-gray-300 p-3 text-left font-bold bg-emerald-50">Potency</th>
                                    <th class="border border-gray-300 p-3 text-right font-bold bg-emerald-50">Price (BDT)</th>
                                    <th class="border border-gray-300 p-3 text-right font-bold bg-emerald-50">Stock</th>
                                    <th class="border border-gray-300 p-3 text-center font-bold bg-emerald-50 w-24">Adjust</th>
                                    <th class="border border-gray-300 p-3 text-left font-bold bg-emerald-50">Description</th>
                                    <th class="border border-gray-300 p-3 text-center font-bold bg-emerald-50 w-12">Del</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(r, idx) in remedies" :key="r.id" :class="idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'" class="border-b border-gray-200">
                                    <!-- Barcode Cell -->
                                    <td class="border border-gray-300 p-2 font-mono text-xs text-gray-600 cursor-pointer hover:bg-blue-100" @dblclick="editField = 'remedy_' + idx + '_barcode'; tempValue = String(r.barcode || '')" @click.prevent>
                                        <input v-if="editField === 'remedy_' + idx + '_barcode'" v-model="tempValue" @blur="saveField(r, 'barcode', idx)" @keyup.enter="saveField(r, 'barcode', idx)" @keyup.esc="editField = null" type="text" class="w-full border border-blue-500 p-1" autofocus>
                                        <span v-else>{{ r.barcode || '—' }}</span>
                                    </td>
                                    <!-- Medicine Name Cell -->
                                    <td class="border border-gray-300 p-2 font-bold cursor-pointer hover:bg-blue-100" @dblclick="editField = 'remedy_' + idx + '_name'; tempValue = String(r.name || '')" @click.prevent>
                                        <input v-if="editField === 'remedy_' + idx + '_name'" v-model="tempValue" @blur="saveField(r, 'name', idx)" @keyup.enter="saveField(r, 'name', idx)" @keyup.esc="editField = null" type="text" class="w-full border border-blue-500 p-1" autofocus>
                                        <span v-else>{{ r.name }}</span>
                                    </td>
                                    <!-- Potency Cell -->
                                    <td class="border border-gray-300 p-2 cursor-pointer hover:bg-blue-100" @dblclick="editField = 'remedy_' + idx + '_potency'; tempValue = String(r.potency || '')" @click.prevent>
                                        <select v-if="editField === 'remedy_' + idx + '_potency'" v-model="tempValue" @blur="saveField(r, 'potency', idx)" @change="saveField(r, 'potency', idx)" class="w-full border border-blue-500 p-1" autofocus>
                                            <option value="">None</option>
                                            <option value="30">30</option>
                                            <option value="200">200</option>
                                            <option value="1X">1X</option>
                                            <option value="6X">6X</option>
                                            <option value="12X">12X</option>
                                        </select>
                                        <span v-else class="text-center block">
                                            <span v-if="r.potency" class="bg-emerald-200 px-2 py-1 rounded text-xs font-bold">{{ r.potency }}</span>
                                            <span v-else class="text-gray-400">—</span>
                                        </span>
                                    </td>
                                    <!-- Price Cell -->
                                    <td class="border border-gray-300 p-2 text-right font-semibold cursor-pointer hover:bg-blue-100" @dblclick="editField = 'remedy_' + idx + '_price'; tempValue = String(r.current_unit_price || '')" @click.prevent>
                                        <input v-if="editField === 'remedy_' + idx + '_price'" v-model="tempValue" @blur="saveField(r, 'current_unit_price', idx)" @keyup.enter="saveField(r, 'current_unit_price', idx)" @keyup.esc="editField = null" type="number" step="0.01" class="w-full border border-blue-500 p-1" autofocus>
                                        <span v-else>{{ r.current_unit_price }}</span>
                                    </td>
                                    <!-- Stock Qty Cell -->
                                    <td class="border border-gray-300 p-2 text-center font-bold cursor-pointer" :class="r.stock_quantity < 10 ? 'bg-red-100 text-red-800 hover:bg-red-200' : 'bg-green-100 text-green-800 hover:bg-green-200'" @dblclick="editField = 'remedy_' + idx + '_stock'; tempValue = String(r.stock_quantity || '')" @click.prevent>
                                        <input v-if="editField === 'remedy_' + idx + '_stock'" v-model="tempValue" @blur="saveField(r, 'stock_quantity', idx)" @keyup.enter="saveField(r, 'stock_quantity', idx)" @keyup.esc="editField = null" type="number" class="w-full border border-blue-500 p-1 text-center" autofocus>
                                        <span v-else>{{ r.stock_quantity }}</span>
                                    </td>
                                    <!-- Quick Adjust Buttons -->
                                    <td class="border border-gray-300 p-2 text-center space-x-1 bg-yellow-50">
                                        <button @click="quickAdjustStock(r)" class="bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded text-xs font-bold" title="Decrease stock">−</button>
                                        <button @click="quickAdjustStock(r, 1)" class="bg-green-500 hover:bg-green-600 text-white px-2 py-1 rounded text-xs font-bold" title="Increase stock">+</button>
                                    </td>
                                    <!-- Description Cell -->
                                    <td class="border border-gray-300 p-2 text-gray-600 cursor-pointer hover:bg-blue-100 text-xs" @dblclick="editField = 'remedy_' + idx + '_desc'; tempValue = String(r.description || '')" @click.prevent>
                                        <input v-if="editField === 'remedy_' + idx + '_desc'" v-model="tempValue" @blur="saveField(r, 'description', idx)" @keyup.enter="saveField(r, 'description', idx)" @keyup.esc="editField = null" type="text" class="w-full border border-blue-500 p-1" autofocus>
                                        <span v-else class="truncate inline-block max-w-xs">{{ r.description || '—' }}</span>
                                    </td>
                                    <!-- Delete Button -->
                                    <td class="border border-gray-300 p-2 text-center">
                                        <button @click="deleteRemedy(r.id)" class="bg-red-600 hover:bg-red-700 text-white px-2 py-1 rounded text-xs font-bold" title="Delete"><i class="fas fa-trash"></i></button>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                        <div v-if="remedies.length === 0" class="p-8 text-center text-gray-400 bg-gray-50">
                            <p class="font-semibold text-lg">No medicines in inventory yet. Scan a barcode to add.</p>
                        </div>
                    </div>
                </div>

                <!-- VISITS VIEW -->
                <div v-if="currentView === 'visits'" class="max-w-7xl">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-3xl font-bold text-emerald-900">Medical Visits</h2>
                        <button @click="showVisitModal = true" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-semibold">
                            <i class="fas fa-stethoscope"></i> New Visit
                        </button>
                    </div>

                    <div v-if="showVisitModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-2xl shadow-2xl max-h-[90vh] overflow-y-auto">
                            <h3 class="text-xl font-bold mb-6">{{ editVisitId ? 'Edit Visit' : 'Record Visit' }}</h3>
                            <form @submit.prevent="editVisitId ? updateVisit() : createVisit()" class="space-y-4">
                                <!-- Patient Selection Section -->
                                <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
                                    <h4 class="font-bold mb-3">👤 Select or Add Patient</h4>
                                    
                                    <!-- Existing Patient Selector -->
                                    <div v-if="!showNewPatientInVisit" class="space-y-3">
                                        <select v-model="visitForm.patient_id" required class="w-full border border-gray-300 p-3 rounded-lg">
                                            <option value="">-- Choose Existing Patient --</option>
                                            <option v-for="p in patients" :key="p.id" :value="p.id">{{ p.name }}</option>
                                        </select>
                                        <button type="button" @click="showNewPatientInVisit = true" class="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-semibold">
                                            <i class="fas fa-plus"></i> Add New Patient
                                        </button>
                                    </div>
                                    
                                    <!-- New Patient Form (Inline) -->
                                    <div v-if="showNewPatientInVisit" class="space-y-3 border-t pt-4">
                                        <input v-model="newPatientInVisitForm.name" placeholder="Full Name" required class="w-full border border-gray-300 p-3 rounded-lg">
                                        <input v-model="newPatientInVisitForm.age" type="number" placeholder="Age" class="w-full border border-gray-300 p-3 rounded-lg">
                                        <select v-model="newPatientInVisitForm.gender" class="w-full border border-gray-300 p-3 rounded-lg">
                                            <option value="">Select Gender</option>
                                            <option value="Male">Male</option>
                                            <option value="Female">Female</option>
                                            <option value="Third-Gender">Other</option>
                                        </select>
                                        <input v-model="newPatientInVisitForm.phone" placeholder="Phone" class="w-full border border-gray-300 p-3 rounded-lg">
                                        <input v-model="newPatientInVisitForm.nid" placeholder="NID (optional)" class="w-full border border-gray-300 p-3 rounded-lg">
                                        <textarea v-model="newPatientInVisitForm.address" placeholder="Address" class="w-full border border-gray-300 p-3 rounded-lg h-16"></textarea>
                                        <div class="flex gap-2">
                                            <button type="button" @click="showNewPatientInVisit = false" class="flex-1 bg-gray-400 hover:bg-gray-500 text-white px-4 py-2 rounded-lg font-semibold">
                                                Back
                                            </button>
                                            <button type="button" @click="savePatientFromVisit()" class="flex-1 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg font-semibold">
                                                <i class="fas fa-check"></i> Create & Select
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                <input v-if="editVisitId" v-model="visitForm.visit_date" type="datetime-local" class="w-full border border-gray-200 p-3 rounded-lg">
                                <textarea v-model="visitForm.chief_complaint" placeholder="Chief Complaint" required class="w-full border border-gray-200 p-3 rounded-lg h-20"></textarea>
                                <textarea v-model="visitForm.diagnosis" placeholder="Diagnosis" class="w-full border border-gray-200 p-3 rounded-lg h-20"></textarea>
                                <textarea v-model="visitForm.notes" placeholder="Notes/Prescription" class="w-full border border-gray-200 p-3 rounded-lg h-20"></textarea>
                                
                                <!-- Medicine Selection Dropdown -->
                                <div class="p-4 bg-blue-50 rounded-lg border border-blue-200">
                                    <label class="block text-sm font-bold mb-2">💊 Select Medicines</label>
                                    <div class="flex gap-2">
                                        <select 
                                            v-model="selectedMedicineId"
                                            class="flex-1 border border-blue-300 p-3 rounded-lg"
                                        >
                                            <option value="">-- Choose a medicine --</option>
                                            <option v-for="r in remedies" :key="r.id" :value="r.id">
                                                {{ r.name }} {{ r.potency ? '(' + r.potency + ')' : '' }} - BDT {{ r.current_unit_price }}
                                            </option>
                                        </select>
                                        <input 
                                            v-model="medicineQuantity" 
                                            type="number" 
                                            min="1" 
                                            placeholder="Qty"
                                            class="w-20 border border-blue-300 p-3 rounded-lg"
                                        >
                                        <button type="button" @click="addMedicineFromDropdown" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-3 rounded-lg font-semibold">Add</button>
                                    </div>
                                </div>
                                
                                <!-- Selected Medicines List -->
                                <div v-if="visitMedicines.length > 0" class="bg-green-50 p-4 rounded-lg border border-green-200">
                                    <label class="block text-sm font-bold mb-3">📋 Selected Medicines</label>
                                    <div class="space-y-2">
                                        <div v-for="(med, idx) in visitMedicines" :key="idx" class="flex justify-between items-center bg-white p-3 rounded border border-green-100">
                                            <div>
                                                <span class="font-semibold">{{ med.name }}</span>
                                                <span v-if="med.potency" class="ml-2 text-xs bg-green-200 px-2 py-1 rounded">{{ med.potency }}</span>
                                                <span class="ml-2 text-sm text-gray-600">Qty: {{ med.quantity }} × BDT {{ med.price }}</span>
                                            </div>
                                            <button type="button" @click="removeMedicine(idx)" class="text-red-600 hover:text-red-800">
                                                <i class="fas fa-trash"></i>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                
                                <input v-model="visitForm.consultation_fee" type="number" step="0.01" placeholder="Consultation Fee" class="w-full border border-gray-200 p-3 rounded-lg">
                                <input v-model="visitForm.amount_paid" type="number" step="0.01" placeholder="Amount Paid" class="w-full border border-gray-200 p-3 rounded-lg">
                                <div class="flex justify-end gap-3">
                                    <button type="button" @click="closeVisitModal()" class="px-4 py-2 text-gray-600">Cancel</button>
                                    <button type="submit" class="bg-emerald-600 text-white px-6 py-2 rounded-lg">{{ editVisitId ? 'Update Visit' : 'Save Visit' }}</button>
                                </div>
                            </form>
                        </div>
                    </div>

                    <div class="space-y-4">
                        <div v-for="v in visits" :key="v.id" class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <div class="flex justify-between items-start">
                                <div class="flex-1">
                                    <h4 class="font-bold text-lg">{{ v.patient_name }}</h4>
                                    <p class="text-sm text-gray-500">{{ formatDate(v.visit_date) }}</p>
                                    <p class="text-sm mt-2"><strong>Chief Complaint:</strong> {{ v.chief_complaint }}</p>
                                    <p class="text-sm"><strong>Diagnosis:</strong> {{ v.diagnosis }}</p>
                                </div>
                                <button type="button" @click="openVisitEditModal(v)" class="text-blue-600 hover:text-blue-800 ml-4"><i class="fas fa-edit"></i></button>
                            </div>
                            <div class="mt-4 flex justify-between items-center">
                                <span :class="v.payment_status === 'paid' ? 'text-green-600' : 'text-red-600'" class="text-sm font-bold">{{ v.payment_status }}</span>
                                <span class="text-sm"><strong>Due:</strong> BDT {{ v.due_amount }}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- FINANCE VIEW -->
                <div v-if="currentView === 'finance'" class="max-w-7xl">
                    <h2 class="text-3xl font-bold mb-8 text-emerald-900">Finance & Accounts</h2>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-blue-500 text-sm font-bold">Revenue Today</p>
                            <p class="text-2xl font-bold mt-1">BDT {{ stats.revenue_today }}</p>
                        </div>
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-emerald-500 text-sm font-bold">Revenue This Month</p>
                            <p class="text-2xl font-bold mt-1">BDT {{ stats.revenue_month }}</p>
                        </div>
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm">
                            <p class="text-red-500 text-sm font-bold">Outstanding Dues</p>
                            <p class="text-2xl font-bold mt-1">BDT {{ stats.outstanding_dues }}</p>
                        </div>
                    </div>
                </div>

            </main>
        </div>
    </div>

    <script>
        const { createApp } = Vue;

        createApp({
            data() {
                return {
                    token: localStorage.getItem('token') || null,
                    currentView: 'dashboard',
                    loginForm: { username: '', password: '' },
                    stats: { patients: 0, visits: 0, remedies: 0, today_visits: 0, today_new_patients: 0, month_visits: 0, revenue_today: 0, revenue_month: 0, outstanding_dues: 0 },
                    patients: [],
                    remedies: [],
                    visits: [],
                    barcodeInput: '',
                    barcodeMessage: '',
                    barcodeError: false,
                    barcodeInputVisit: '',
                    visitBarcodeMessage: '',
                    visitBarcodeError: false,
                    selectedMedicineId: null,
                    medicineQuantity: 1,
                    visitMedicines: [],
                    
                    showPatientModal: false,
                    editPatientId: null,
                    patientForm: { name: '', age: '', gender: '', phone: '', nid: '', address: '' },
                    
                    showNewPatientInVisit: false,
                    newPatientInVisitForm: { name: '', age: '', gender: '', phone: '', nid: '', address: '' },
                    
                    showRemedyModal: false,
                    editField: null,
                    tempValue: '',
                    remedyForm: { name: '', barcode: '', potency: '30', current_unit_price: '', stock_quantity: 0, description: '' },
                    
                    showManualAddModal: false,
                    manualMedicineForm: { name: '', barcode: '', potency: '', current_unit_price: '', stock_quantity: 0, description: '' },
                    
                    showVisitModal: false,
                    editVisitId: null,
                    visitForm: { patient_id: '', visit_date: '', chief_complaint: '', diagnosis: '', notes: '', consultation_fee: 500, amount_paid: 0, medicines: [] }
                }
            },
            async mounted() {
                if (this.token) {
                    await this.loadAll();
                }
            },
            methods: {
                async login() {
                    try {
                        const res = await fetch('/api/login', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.loginForm)
                        });
                        const data = await res.json();
                        if (res.ok) {
                            this.token = data.access_token;
                            localStorage.setItem('token', this.token);
                            await this.loadAll();
                        } else {
                            alert(data.detail || 'Login failed');
                        }
                    } catch (e) { alert('Login error: ' + e.message); }
                },
                logout() {
                    this.token = null;
                    localStorage.removeItem('token');
                },
                async api(url, method='GET', body=null) {
                    const opts = {
                        method,
                        headers: { 
                            'Authorization': `Bearer ${this.token}`,
                            'Content-Type': 'application/json'
                        }
                    };
                    if (body) opts.body = JSON.stringify(body);
                    console.log('API Call:', method, url, body);
                    
                    const res = await fetch(url, opts);
                    console.log('Response Status:', res.status);
                    console.log('Response Headers:', res.headers);
                    
                    if (res.status === 401) {
                        this.logout();
                        alert("Session expired. Please login again.");
                        return null;
                    }
                    
                    let data;
                    const contentType = res.headers.get('content-type');
                    console.log('Content-Type:', contentType);
                    
                    try {
                        if (contentType && contentType.includes('application/json')) {
                            data = await res.json();
                        } else {
                            const text = await res.text();
                            console.log('Response Text:', text);
                            data = { detail: text };
                        }
                    } catch (e) {
                        console.error('Failed to parse response:', e);
                        const text = await res.text();
                        console.log('Raw response:', text);
                        throw new Error('Failed to parse API response: ' + text.substring(0, 100));
                    }
                    
                    console.log('Response Data:', data);
                    
                    if (!res.ok) {
                        console.error('API Error:', res.status, data);
                        throw new Error(data.detail || 'API Error');
                    }
                    
                    return data;
                },
                async loadAll() {
                    this.stats = await this.api('/api/stats');
                    this.patients = await this.api('/api/patients');
                    this.remedies = await this.api('/api/remedies');
                    this.visits = await this.api('/api/visits');
                },
                async savePatient() {
                    await this.api('/api/patients', 'POST', this.patientForm);
                    this.closePatientModal();
                    this.loadAll();
                },
                async updatePatient() {
                    await this.api(`/api/patients/${this.editPatientId}`, 'PUT', this.patientForm);
                    this.closePatientModal();
                    this.loadAll();
                },
                openPatientEditModal(patient) {
                    this.editPatientId = patient.id;
                    this.patientForm = {
                        name: patient.name,
                        age: patient.age || '',
                        gender: patient.gender || '',
                        phone: patient.phone || '',
                        nid: patient.nid || '',
                        address: patient.address || ''
                    };
                    this.showPatientModal = true;
                },
                closePatientModal() {
                    this.showPatientModal = false;
                    this.editPatientId = null;
                    this.patientForm = { name: '', age: '', gender: '', phone: '', nid: '', address: '' };
                },
                closeRemedyModal() {
                    this.showRemedyModal = false;
                    this.remedyForm = { name: '', barcode: '', potency: '30', current_unit_price: '', stock_quantity: 0, description: '' };
                    this.barcodeInput = '';
                    this.barcodeMessage = '';
                    this.barcodeError = false;
                },
                closeManualAddModal() {
                    this.showManualAddModal = false;
                    this.manualMedicineForm = { name: '', barcode: '', potency: '', current_unit_price: '', stock_quantity: 0, description: '' };
                },
                async submitManualMedicine() {
                    try {
                        const payload = {
                            name: this.manualMedicineForm.name,
                            barcode: this.manualMedicineForm.barcode || '',
                            potency: this.manualMedicineForm.potency || '',
                            description: this.manualMedicineForm.description || '',
                            current_unit_price: parseFloat(this.manualMedicineForm.current_unit_price) || 0,
                            stock_quantity: parseInt(this.manualMedicineForm.stock_quantity) || 0
                        };
                        
                        const result = await this.api('/api/remedies', 'POST', payload);
                        console.log('Manual medicine added:', result);
                        
                        alert('✅ Medicine added successfully!');
                        this.closeManualAddModal();
                        await this.loadAll();
                    } catch (e) {
                        console.error('Error adding medicine:', e);
                        alert('❌ Error adding medicine: ' + e.message);
                    }
                },
                async saveField(remedy, field, idx) {
                    console.log('Saving field:', field, 'Value:', this.tempValue, 'Remedy ID:', remedy.id);
                    
                    if (field === 'current_unit_price') {
                        remedy.current_unit_price = parseFloat(this.tempValue) || 0;
                    } else if (field === 'stock_quantity') {
                        remedy.stock_quantity = parseInt(this.tempValue) || 0;
                    } else {
                        remedy[field] = this.tempValue;
                    }
                    
                    try {
                        const payload = {
                            name: remedy.name,
                            barcode: remedy.barcode || '',
                            potency: remedy.potency || '',
                            description: remedy.description || '',
                            current_unit_price: parseFloat(remedy.current_unit_price) || 0,
                            stock_quantity: parseInt(remedy.stock_quantity) || 0
                        };
                        console.log('Sending payload:', payload);
                        
                        const result = await this.api(`/api/remedies/${remedy.id}`, 'PUT', payload);
                        console.log('Save successful:', result);
                        
                        this.editField = null;
                        this.tempValue = '';
                        await this.loadAll();
                    } catch (e) {
                        console.error('Error saving:', e);
                        alert('Error saving: ' + e.message);
                        this.editField = null;
                    }
                },
                async quickAdjustStock(remedy, amount = -1) {
                    console.log('quickAdjustStock called with remedy:', remedy, 'amount:', amount);
                    console.log('Remedy ID:', remedy.id);
                    console.log('Current Stock:', remedy.stock_quantity);
                    
                    const newStock = Math.max(0, parseInt(remedy.stock_quantity) + amount);
                    console.log('New Stock:', newStock);
                    
                    try {
                        const payload = {
                            name: remedy.name,
                            barcode: remedy.barcode || '',
                            potency: remedy.potency || '',
                            description: remedy.description || '',
                            current_unit_price: parseFloat(remedy.current_unit_price) || 0,
                            stock_quantity: newStock
                        };
                        console.log('Sending payload:', payload);
                        console.log('API URL:', `/api/remedies/${remedy.id}`);
                        
                        await this.api(`/api/remedies/${remedy.id}`, 'PUT', payload);
                        console.log('Stock adjustment successful');
                        await this.loadAll();
                    } catch (e) {
                        console.error('Error adjusting stock:', e);
                        alert('Error adjusting stock: ' + e.message);
                    }
                },
                async searchByBarcode() {
                    if (!this.barcodeInput || this.barcodeInput.trim() === '') {
                        this.barcodeError = true;
                        this.barcodeMessage = 'Please enter a barcode';
                        return;
                    }
                    
                    try {
                        const res = await fetch(`/api/remedies/search/barcode?barcode=${encodeURIComponent(this.barcodeInput.trim())}`, {
                            method: 'GET',
                            headers: { 'Authorization': `Bearer ${this.token}` }
                        });
                        
                        if (res.ok) {
                            const remedy = await res.json();
                            // Populate form with found remedy
                            this.remedyForm = {
                                name: remedy.name,
                                barcode: remedy.barcode || this.barcodeInput,
                                potency: remedy.potency || '',
                                current_unit_price: remedy.current_unit_price,
                                stock_quantity: remedy.stock_quantity,
                                description: remedy.description || ''
                            };
                            this.barcodeError = false;
                            this.barcodeMessage = '✅ Remedy found! Edit details and save.';
                            this.barcodeInput = '';
                        } else {
                            const data = await res.json();
                            this.barcodeError = true;
                            this.barcodeMessage = data.detail || 'Remedy not found';
                        }
                    } catch (e) {
                        this.barcodeError = true;
                        this.barcodeMessage = 'Error: ' + e.message;
                    }
                },
                async saveRemedy() {
                    await this.api('/api/remedies', 'POST', this.remedyForm);
                    this.closeRemedyModal();
                    this.loadAll();
                },
                async addMedicineByBarcode() {
                    if (!this.barcodeInputVisit || this.barcodeInputVisit.trim() === '') {
                        this.visitBarcodeError = true;
                        this.visitBarcodeMessage = 'Please enter a barcode';
                        return;
                    }
                    
                    try {
                        const res = await fetch(`/api/remedies/search/barcode?barcode=${encodeURIComponent(this.barcodeInputVisit.trim())}`, {
                            method: 'GET',
                            headers: { 'Authorization': `Bearer ${this.token}` }
                        });
                        
                        if (res.ok) {
                            const remedy = await res.json();
                            // Add to medicines list
                            this.visitMedicines.push({
                                remedy_id: remedy.id,
                                name: remedy.name,
                                potency: remedy.potency,
                                price: remedy.current_unit_price,
                                quantity: 1
                            });
                            this.visitForm.medicines = this.visitMedicines;
                            this.visitBarcodeError = false;
                            this.visitBarcodeMessage = '✅ Medicine added! Scan another or press Save.';
                            this.barcodeInputVisit = '';
                        } else {
                            const data = await res.json();
                            this.visitBarcodeError = true;
                            this.visitBarcodeMessage = data.detail || 'Medicine not found';
                        }
                    } catch (e) {
                        this.visitBarcodeError = true;
                        this.visitBarcodeMessage = 'Error: ' + e.message;
                    }
                },
                addMedicineFromDropdown() {
                    if (!this.selectedMedicineId) {
                        alert('Please select a medicine');
                        return;
                    }
                    
                    const medicine = this.remedies.find(r => r.id == this.selectedMedicineId);
                    if (!medicine) {
                        alert('Medicine not found');
                        return;
                    }
                    
                    // Check if medicine already in list
                    const existing = this.visitMedicines.find(m => m.remedy_id == this.selectedMedicineId);
                    if (existing) {
                        existing.quantity += parseInt(this.medicineQuantity) || 1;
                    } else {
                        this.visitMedicines.push({
                            remedy_id: medicine.id,
                            name: medicine.name,
                            potency: medicine.potency,
                            price: medicine.current_unit_price,
                            quantity: parseInt(this.medicineQuantity) || 1
                        });
                    }
                    
                    this.visitForm.medicines = this.visitMedicines;
                    this.selectedMedicineId = null;
                    this.medicineQuantity = 1;
                },
                async savePatientFromVisit() {
                    if (!this.newPatientInVisitForm.name || !this.newPatientInVisitForm.phone) {
                        alert('Please enter at least Name and Phone');
                        return;
                    }
                    
                    try {
                        const response = await this.api('/api/patients', 'POST', this.newPatientInVisitForm);
                        console.log('New patient created:', response);
                        
                        // Create full patient object with the data we just submitted
                        const fullPatient = {
                            id: response.id,
                            name: this.newPatientInVisitForm.name,
                            age: this.newPatientInVisitForm.age || null,
                            gender: this.newPatientInVisitForm.gender || null,
                            phone: this.newPatientInVisitForm.phone,
                            nid: this.newPatientInVisitForm.nid || null,
                            address: this.newPatientInVisitForm.address || null
                        };
                        
                        // Add to patients list and select it
                        this.patients.push(fullPatient);
                        this.visitForm.patient_id = response.id;
                        
                        // Reset and hide the new patient form
                        this.newPatientInVisitForm = { name: '', age: '', gender: '', phone: '', nid: '', address: '' };
                        this.showNewPatientInVisit = false;
                        
                        alert('✅ Patient created and selected!');
                    } catch (e) {
                        alert('❌ Error creating patient: ' + e.message);
                        console.error(e);
                    }
                },
                removeMedicine(idx) {
                    this.visitMedicines.splice(idx, 1);
                    this.visitForm.medicines = this.visitMedicines;
                },
                async addMedicineToInventory() {
                    if (!this.barcodeInput || this.barcodeInput.trim() === '') {
                        this.barcodeError = true;
                        this.barcodeMessage = 'Please scan or enter a barcode';
                        return;
                    }
                    
                    try {
                        const res = await fetch(`/api/remedies/search/barcode?barcode=${encodeURIComponent(this.barcodeInput.trim())}`, {
                            method: 'GET',
                            headers: { 'Authorization': `Bearer ${this.token}` }
                        });
                        
                        if (res.ok) {
                            // Medicine already exists - just clear and show success
                            const remedy = await res.json();
                            this.barcodeError = false;
                            this.barcodeMessage = `✅ "${remedy.name}" already in inventory (Stock: ${remedy.stock_quantity})`;
                            this.barcodeInput = '';
                        } else {
                            // Medicine not found - show message asking user to create it
                            const data = await res.json();
                            this.barcodeError = true;
                            this.barcodeMessage = 'Medicine not found. Please add it manually or check the barcode.';
                            // Clear after 3 seconds
                            setTimeout(() => {
                                this.barcodeMessage = '';
                            }, 3000);
                        }
                    } catch (e) {
                        this.barcodeError = true;
                        this.barcodeMessage = 'Error: ' + e.message;
                    }
                },

                async saveRemedy() {
                    if (this.editRemedyId) {
                        // Update existing
                        await this.api(`/api/remedies/${this.editRemedyId}`, 'PUT', this.remedyForm);
                        this.editRemedyId = null;
                    } else {
                        // Create new
                        await this.api('/api/remedies', 'POST', this.remedyForm);
                    }
                    this.closeRemedyModal();
                    this.loadAll();
                },
                async deleteRemedy(id) {
                    if (confirm('Are you sure you want to delete this medicine?')) {
                        await this.api(`/api/remedies/${id}`, 'DELETE');
                        this.loadAll();
                    }
                },
                async createVisit() {
                    // Validate required fields
                    if (!this.visitForm.patient_id) {
                        alert('Please select a patient');
                        return;
                    }
                    
                    if (!this.visitForm.chief_complaint) {
                        alert('Please enter chief complaint');
                        return;
                    }
                    
                    // Make sure medicines are included
                    const medicinesData = this.visitMedicines.map(med => ({
                        remedy_id: parseInt(med.remedy_id),
                        quantity: parseInt(med.quantity) || 1
                    }));
                    
                    // Prepare visit data with proper types
                    const visitData = {
                        patient_id: parseInt(this.visitForm.patient_id),
                        visit_date: this.visitForm.visit_date || null,
                        chief_complaint: this.visitForm.chief_complaint,
                        diagnosis: this.visitForm.diagnosis || '',
                        notes: this.visitForm.notes || '',
                        consultation_fee: parseFloat(this.visitForm.consultation_fee) || 0,
                        amount_paid: parseFloat(this.visitForm.amount_paid) || 0,
                        medicines: medicinesData
                    };
                    
                    console.log('Sending visit data:', visitData);
                    
                    try {
                        await this.api('/api/visits', 'POST', visitData);
                        alert('✅ Visit recorded successfully!');
                        this.closeVisitModal();
                        this.loadAll();
                    } catch (e) {
                        alert('❌ Error: ' + e.message);
                        console.error('Visit creation error:', e);
                    }
                },
                async updateVisit() {
                    await this.api(`/api/visits/${this.editVisitId}`, 'PUT', this.visitForm);
                    this.closeVisitModal();
                    this.loadAll();
                },
                openVisitEditModal(visit) {
                    this.editVisitId = visit.id;
                    // Format date for datetime-local input: YYYY-MM-DDTHH:mm
                    let date = new Date(visit.visit_date);
                    let dateStr = date.toISOString().slice(0, 16);
                    this.visitForm = {
                        patient_id: visit.patient_id,
                        visit_date: dateStr,
                        chief_complaint: visit.chief_complaint || '',
                        diagnosis: visit.diagnosis || '',
                        notes: visit.notes || '',
                        consultation_fee: visit.consultation_fee || 500,
                        amount_paid: visit.amount_paid || 0
                    };
                    this.showVisitModal = true;
                },
                closeVisitModal() {
                    this.showVisitModal = false;
                    this.editVisitId = null;
                    this.visitForm = { patient_id: '', visit_date: '', chief_complaint: '', diagnosis: '', notes: '', consultation_fee: 500, amount_paid: 0, medicines: [] };
                    this.visitMedicines = [];
                    this.barcodeInputVisit = '';
                    this.visitBarcodeMessage = '';
                    this.visitBarcodeError = false;
                    this.selectedMedicineId = null;
                    this.medicineQuantity = 1;
                    this.showNewPatientInVisit = false;
                    this.newPatientInVisitForm = { name: '', age: '', gender: '', phone: '', nid: '', address: '' };
                },
                formatDate(str) {
                    if (!str) return '-';
                    return new Date(str).toLocaleDateString();
                }
            }
        }).mount('#app');
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    init_database()
    print("🚀 SERVER STARTED on http://127.0.0.1:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
