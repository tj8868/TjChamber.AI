#!/usr/bin/env python3
"""
🏥 CHAMBER AI - COMPLETE MANAGEMENT SYSTEM
FastAPI Application with SQLite Database
Integrated with 'schema.sql' for Patients, Visits, Inventory, and Analytics.
"""

from fastapi import FastAPI, HTTPException, Request, Depends, status
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
from ml_service import ChatService

# ============================================================
# CONFIGURATION
# ============================================================

DB_PATH = "chamber.db"
SECRET_KEY = os.getenv("SECRET_KEY", "chamber-ai-super-secret-key-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Chat Service
# Pass DB Path so chatbot can read inventory
chat_service = ChatService(DB_PATH)

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
# DATABASE UTILS
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
            conn.commit()
            conn.close()
            print("✅ Database tables created successfully!")
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            # Don't return here, attempt to seed anyway to see errors clearly
            
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
def create_patient(patient: dict, user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        # Sanitize inputs for SQLite constraints
        gender = patient.get('gender')
        if not gender: gender = None
        
        nid = patient.get('nid')
        if not nid: nid = None  # Ensure NULL for uniqueness if empty

        cursor = conn.execute("""
            INSERT INTO patients (name, nid, phone, age, gender, address, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            patient.get('name'), 
            nid, 
            patient.get('phone'), 
            patient.get('age'), 
            gender, 
            patient.get('address'),
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
def create_remedy(remedy: dict, user: dict = Depends(get_current_user)):
    if user['role'] not in ['admin', 'doctor']:
        raise HTTPException(status_code=403, detail="Permission denied. Only Doctors and Admins can manage inventory.")
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO remedies (name, potency, description, current_unit_price, stock_quantity)
            VALUES (?, ?, ?, ?, ?)
        """, (
            remedy.get('name'),
            remedy.get('potency'),
            remedy.get('description'),
            remedy.get('current_unit_price'),
            remedy.get('stock_quantity', 0)
        ))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Remedy added"}
    finally:
        conn.close()

@app.put("/api/remedies/{remedy_id}")
def update_remedy(remedy_id: int, remedy: dict, user: dict = Depends(get_current_user)):
    if user['role'] not in ['admin', 'doctor']:
        raise HTTPException(status_code=403, detail="Permission denied. Only Doctors and Admins can update inventory.")
    
    conn = get_db()
    try:
        conn.execute("""
            UPDATE remedies 
            SET name=?, potency=?, description=?, current_unit_price=?, stock_quantity=?
            WHERE id=?
        """, (
            remedy.get('name'),
            remedy.get('potency'),
            remedy.get('description'),
            remedy.get('current_unit_price'),
            remedy.get('stock_quantity'),
            remedy_id
        ))
        conn.commit()
        return {"message": "Remedy updated"}
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
def create_visit(visit: dict, user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        # 1. Calculate Medicine Costs & Prepare Stock Updates
        med_cost = 0.0
        medicines_to_insert = []
        
        if 'medicines' in visit and visit['medicines']:
            for item in visit['medicines']:
                # Get current price from Inventory
                rem = conn.execute("SELECT id, current_unit_price, stock_quantity FROM remedies WHERE id = ?", (item['remedy_id'],)).fetchone()
                if rem:
                    price = float(rem['current_unit_price'])
                    qty = int(item.get('quantity', 1))
                    
                    if rem['stock_quantity'] < qty:
                         raise HTTPException(status_code=400, detail=f"Insufficient stock for remedy ID {item['remedy_id']}")

                    line_total = price * qty
                    med_cost += line_total
                    medicines_to_insert.append({
                        "remedy_id": item['remedy_id'],
                        "quantity": qty,
                        "price": price,
                        "total": line_total
                    })

        # 2. Insert Visit Data
        consult_fee = float(visit.get('consultation_fee', 0))
        
        cursor = conn.execute("""
            INSERT INTO visits (patient_id, chief_complaint, diagnosis, notes, recorded_by)
            VALUES (?, ?, ?, ?, ?)
        """, (
            visit.get('patient_id'),
            visit.get('chief_complaint'),
            visit.get('diagnosis'),
            visit.get('notes'),
            user['id']
        ))
        visit_id = cursor.lastrowid
        
        # 3. Insert Visit Medicines & Update Stock
        for med in medicines_to_insert:
            conn.execute("""
                INSERT INTO visit_medicines (visit_id, remedy_id, quantity, unit_price_snapshot, line_total)
                VALUES (?, ?, ?, ?, ?)
            """, (visit_id, med['remedy_id'], med['quantity'], med['price'], med['total']))
            
            # Reduce Stock
            conn.execute("UPDATE remedies SET stock_quantity = stock_quantity - ? WHERE id = ?", 
                         (med['quantity'], med['remedy_id']))

        # 4. Handle Payments (Business Logic in Python)
        total_bill = consult_fee + med_cost
        amount_paid = float(visit.get('amount_paid', 0))
        due_amount = total_bill - amount_paid
        
        # Status Logic
        if total_bill <= 0:
            status = 'n/a'
        elif due_amount <= 0:
            status = 'paid'
        elif amount_paid > 0:
            status = 'partially paid'
        else:
            status = 'pending'
        
        conn.execute("""
            INSERT INTO payments (visit_id, consultation_fee, medicine_bill, total_bill, amount_paid, due_amount, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            visit_id,
            consult_fee,
            med_cost,
            total_bill,
            amount_paid,
            due_amount,
            status
        ))

        conn.commit()
        return {"id": visit_id, "message": "Visit recorded", "total": total_bill, "due": due_amount, "status": status}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
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

@app.get("/api/stats")
def dashboard_stats(user: dict = Depends(get_current_user)):
    conn = get_db()
    stats = {
        "patients": conn.execute("SELECT COUNT(*) as c FROM patients").fetchone()['c'],
        "visits": conn.execute("SELECT COUNT(*) as c FROM visits").fetchone()['c'],
        "remedies": conn.execute("SELECT COUNT(*) as c FROM remedies").fetchone()['c'],
        "today_visits": conn.execute("SELECT COUNT(*) as c FROM visits WHERE DATE(visit_date) = DATE('now')").fetchone()['c']
    }
    conn.close()
    return stats

# ============================================================
# CHATBOT FEATURE
# ============================================================

class ChatRequest(BaseModel):
    message: str

@app.on_event("startup")
def startup_event():
    print("🧠 Initializing Chatbot Model (Pre-loading)...")
    try:
        ChatService.load_model()
        print("✅ Chatbot Model Loaded & Ready.")
    except Exception as e:
        print(f"❌ Failed to load Chatbot Model on startup: {e}")

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest, user: dict = Depends(get_current_user)):
    """
    General purpose chatbot using local Orca Mini AI.
    """
    print(f"📩 Chat Request: '{req.message}'")
    try:
        response = chat_service.get_response(req.message)
        return {"reply": response}
    except Exception as e:
        print(f"❌ Chat Endpoint Error: {e}")
        return {"reply": "Sorry, I am having trouble thinking right now."}


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
    <title>Chamber AI Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        /* Custom scrollbar for webkit */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #f0fdf4; }
        ::-webkit-scrollbar-thumb { background: #166534; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #14532d; }
        
        /* Background Imprint */
        .watermark-bg::before {
            content: "";
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            /* Placeholder for the herbal image - Replace URL with your base64 or file path */
            background-image: url('https://img.freepik.com/free-photo/spa-concept-with-basil-essential-oil_23-2148206584.jpg'); 
            background-size: cover;
            background-position: center;
            opacity: 0.15; /* Low opacity for 'imprint' effect */
            z-index: -1;
            pointer-events: none;
            mix-blend-mode: multiply;
        }
    </style>
</head>
<body class="bg-green-50 text-gray-800 font-sans">
    <div id="app" class="min-h-screen flex flex-col relative z-0 watermark-bg">
        
        <!-- LOGIN SCREEN -->
        <div v-if="!token" class="flex-grow flex items-center justify-center bg-green-50 relative overflow-hidden">
            <!-- Decorative Background Elements -->
            <div class="absolute top-0 left-0 w-64 h-64 bg-green-200 rounded-full mix-blend-multiply filter blur-xl opacity-70 animate-blob"></div>
            <div class="absolute top-0 right-0 w-64 h-64 bg-emerald-200 rounded-full mix-blend-multiply filter blur-xl opacity-70 animate-blob animation-delay-2000"></div>
            
            <div class="bg-white/80 backdrop-blur-sm p-8 rounded-2xl shadow-2xl w-full max-w-md border border-green-100 relative z-10">
                <div class="text-center mb-6">
                    <div class="inline-flex justify-center items-center w-16 h-16 rounded-full bg-green-100 text-green-600 mb-4">
                        <i class="fas fa-leaf text-2xl"></i>
                    </div>
                    <h1 class="text-3xl font-bold bg-gradient-to-r from-green-700 to-emerald-600 bg-clip-text text-transparent">Chamber AI</h1>
                    <p class="text-gray-500 mt-2">Homeopathic Clinic Management</p>
                </div>
                
                <form @submit.prevent="login" class="space-y-4">
                    <div>
                        <input v-model="loginForm.username" placeholder="Username" class="w-full bg-white border border-green-200 p-3 rounded-lg text-gray-800 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-200 transition shadow-sm">
                    </div>
                    <div>
                        <input v-model="loginForm.password" type="password" placeholder="Password" class="w-full bg-white border border-green-200 p-3 rounded-lg text-gray-800 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-200 transition shadow-sm">
                    </div>
                    <button type="submit" class="w-full bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white font-bold py-3 rounded-lg transition shadow-md transform active:scale-95 duration-200">
                        Login to Dashboard
                    </button>
                    <p class="text-xs text-gray-400 text-center mt-4">System Access Only</p>
                </form>
            </div>
        </div>

        <!-- MAIN APP -->
        <div v-else class="flex-grow flex">
            <!-- Sidebar -->
            <aside class="w-64 bg-emerald-900 text-green-50 border-r border-emerald-800 flex flex-col shadow-2xl z-20">
                <div class="p-6 border-b border-emerald-800/50">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded bg-green-500 flex items-center justify-center text-white">
                            <i class="fas fa-first-aid"></i>
                        </div>
                        <div>
                            <h2 class="text-xl font-bold text-white tracking-wide">Chamber AI</h2>
                            <p class="text-xs text-emerald-300 uppercase tracking-widest font-semibold">Homeopathy</p>
                        </div>
                    </div>
                </div>
                
                <nav class="flex-grow space-y-1 p-4">
                    <template v-for="(item, idx) in [
                        {id: 'dashboard', icon: 'fa-home', label: 'Dashboard'},
                        {id: 'patients', icon: 'fa-user-injured', label: 'Patients'},
                        {id: 'visits', icon: 'fa-user-md', label: 'Visits'},
                        {id: 'inventory', icon: 'fa-leaf', label: 'Inventory'},
                        {id: 'reports', icon: 'fa-chart-pie', label: 'Reports'}
                    ]">
                    <button @click="currentView = item.id" 
                        :class="currentView===item.id ? 'bg-emerald-700 text-white shadow-lg translate-x-1' : 'text-emerald-100 hover:bg-emerald-800 hover:text-white'" 
                        class="w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition-all duration-200 font-medium group">
                        <i :class="['fas', item.icon, 'w-5 text-center group-hover:scale-110 transition-transform']"></i> 
                        {{ item.label }}
                    </button>
                    </template>
                </nav>
                
                <div class="p-4 border-t border-emerald-800/50 bg-emerald-950/30">
                    <div class="flex items-center gap-3 mb-4 px-2">
                        <div class="w-8 h-8 rounded-full bg-emerald-700 flex items-center justify-center text-xs font-bold">{{ userRole.substring(0,2).toUpperCase() }}</div>
                        <div class="text-sm">
                            <p class="font-bold text-white capitalize">{{ userRole }}</p>
                            <p class="text-xs text-emerald-400">Logged in</p>
                        </div>
                    </div>
                    <button @click="logout" class="text-red-300 hover:text-red-200 hover:bg-red-900/30 w-full text-left flex items-center gap-3 px-4 py-2 rounded transition">
                        <i class="fas fa-sign-out-alt"></i> Logout
                    </button>
                </div>
            </aside>

            <!-- Content Area -->
            <main class="flex-grow p-8 bg-green-50 overflow-y-auto">
                
                <!-- DASHBOARD VIEW -->
                <div v-if="currentView === 'dashboard'" class="max-w-7xl mx-auto animate-fade-in">
                    <h2 class="text-3xl font-bold mb-8 text-emerald-900 flex items-center gap-3">
                        <i class="fas fa-columns text-emerald-600"></i> Dashboard Overview
                    </h2>
                    
                    <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm hover:shadow-md transition duration-300 group">
                            <div class="flex justify-between items-start mb-4">
                                <div class="bg-lime-50 text-lime-600 p-3 rounded-lg group-hover:bg-lime-600 group-hover:text-white transition">
                                    <i class="fas fa-users text-xl"></i>
                                </div>
                                <span class="bg-lime-50 text-lime-700 text-xs font-bold px-2 py-1 rounded-full">Total</span>
                            </div>
                            <p class="text-gray-500 text-sm font-medium">Patients</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.patients }}</p>
                        </div>
                        
                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm hover:shadow-md transition duration-300 group">
                            <div class="flex justify-between items-start mb-4">
                                <div class="bg-emerald-50 text-emerald-600 p-3 rounded-lg group-hover:bg-emerald-600 group-hover:text-white transition">
                                    <i class="fas fa-file-medical text-xl"></i>
                                </div>
                                <span class="bg-emerald-50 text-emerald-700 text-xs font-bold px-2 py-1 rounded-full">Total</span>
                            </div>
                            <p class="text-gray-500 text-sm font-medium">Visits</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.visits }}</p>
                        </div>

                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm hover:shadow-md transition duration-300 group">
                            <div class="flex justify-between items-start mb-4">
                                <div class="bg-purple-50 text-purple-600 p-3 rounded-lg group-hover:bg-purple-600 group-hover:text-white transition">
                                    <i class="fas fa-calendar-day text-xl"></i>
                                </div>
                                <span class="bg-purple-50 text-purple-700 text-xs font-bold px-2 py-1 rounded-full">Today</span>
                            </div>
                            <p class="text-gray-500 text-sm font-medium">New Visits</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.today_visits }}</p>
                        </div>

                        <div class="bg-white p-6 rounded-xl border border-green-100 shadow-sm hover:shadow-md transition duration-300 group">
                            <div class="flex justify-between items-start mb-4">
                                <div class="bg-amber-50 text-amber-600 p-3 rounded-lg group-hover:bg-amber-600 group-hover:text-white transition">
                                    <i class="fas fa-cubes text-xl"></i>
                                </div>
                                <span class="bg-amber-50 text-amber-700 text-xs font-bold px-2 py-1 rounded-full">Stock</span>
                            </div>
                            <p class="text-gray-500 text-sm font-medium">Remedies</p>
                            <p class="text-3xl font-bold text-gray-800 mt-1">{{ stats.remedies }}</p>
                        </div>
                    </div>

                    <!-- Recent Activity / Welcome Banner -->
                    <div class="bg-gradient-to-r from-emerald-600 to-green-500 rounded-2xl p-8 text-white shadow-lg relative overflow-hidden">
                        <div class="absolute right-0 top-0 h-full w-1/2 bg-white/10 transform skew-x-12"></div>
                        <div class="relative z-10">
                            <h3 class="text-2xl font-bold mb-2">Welcome Back, {{ userRole }}!</h3>
                            <p class="text-emerald-100 max-w-xl">
                                Manage your homeopathic clinic efficiently. Track patient history, manage remedy inventory, and generate billing reports all in one place.
                            </p>
                            <button @click="currentView = 'visits'" class="mt-6 bg-white text-emerald-700 px-6 py-2 rounded-lg font-bold shadow hover:bg-emerald-50 transition">
                                Start Consultation
                            </button>
                        </div>
                    </div>
                </div>

                <!-- PATIENTS VIEW -->
                <div v-if="currentView === 'patients'" class="max-w-7xl mx-auto">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-3xl font-bold text-emerald-900">Patient Management</h2>
                        <button @click="openPatientModal()" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-semibold shadow-md transition flex items-center gap-2">
                            <i class="fas fa-plus"></i> New Patient
                        </button>
                    </div>

                    <!-- New Patient Modal -->
                    <div v-if="showPatientModal" class="fixed inset-0 bg-emerald-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-lg shadow-2xl border border-green-100 animate-slide-up">
                            <div class="flex justify-between items-center mb-6">
                                <h3 class="text-xl font-bold text-gray-800">{{ isEditingPatient ? 'Edit Patient' : 'Register New Patient' }}</h3>
                                <button @click="showPatientModal = false" class="text-gray-400 hover:text-red-500 transition"><i class="fas fa-times text-xl"></i></button>
                            </div>
                            
                            <form @submit.prevent="savePatient" class="space-y-4">
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                                    <input v-model="patientForm.name" placeholder="Name" required class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                </div>
                                <div class="grid grid-cols-2 gap-4">
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700 mb-1">Age</label>
                                        <input v-model="patientForm.age" type="number" placeholder="Years" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700 mb-1">Gender</label>
                                        <select v-model="patientForm.gender" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                            <option value="">Select</option>
                                            <option value="Male">Male</option>
                                            <option value="Female">Female</option>
                                            <option value="Third-Gender">Other</option>
                                        </select>
                                    </div>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Phone</label>
                                    <input v-model="patientForm.phone" placeholder="Contact Number" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">NID</label>
                                    <input v-model="patientForm.nid" placeholder="National ID (Optional)" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Address</label>
                                    <textarea v-model="patientForm.address" placeholder="Residential Address" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition h-24"></textarea>
                                </div>
                                <div class="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100">
                                    <button type="button" @click="showPatientModal = false" class="px-5 py-2 text-gray-500 hover:text-gray-700 font-medium">Cancel</button>
                                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-bold shadow transition">{{ isEditingPatient ? 'Update Profile' : 'Save Patient' }}</button>
                                </div>
                            </form>
                        </div>
                    </div>

                    <!-- Patients Table -->
                    <div class="bg-white rounded-xl shadow-lg border border-green-100 overflow-x-auto">
                        <table class="w-full text-left">
                            <thead class="bg-green-50 text-emerald-900 border-b border-green-100">
                                <tr>
                                    <th class="p-5 font-bold">Name</th>
                                    <th class="p-5 font-bold">Age / Gender</th>
                                    <th class="p-5 font-bold">Contact</th>
                                    <th class="p-5 font-bold">NID</th>
                                    <th class="p-5 font-bold text-center">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100">
                                <!-- QUICK ADD ROW -->
                                <tr class="bg-green-50/50">
                                    <td class="p-3">
                                        <input ref="quickName" v-model="quickPatient.name" @keyup.enter="quickCreatePatient" placeholder="+ Quick Add Name..." class="w-full bg-white border border-green-200 p-2 pl-3 rounded-lg text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none shadow-sm">
                                    </td>
                                    <td class="p-2">
                                        <div class="flex gap-2">
                                            <input v-model="quickPatient.age" @keyup.enter="quickCreatePatient" type="number" placeholder="Age" class="w-16 bg-white border border-green-200 p-2 rounded-lg text-sm text-center outline-none">
                                            <select v-model="quickPatient.gender" class="flex-1 bg-white border border-green-200 p-2 rounded-lg text-sm outline-none">
                                                <option value="" disabled selected>Gen</option>
                                                <option value="Male">M</option>
                                                <option value="Female">F</option>
                                                <option value="Third-Gender">O</option>
                                            </select>
                                        </div>
                                    </td>
                                    <td class="p-2">
                                        <input v-model="quickPatient.phone" @keyup.enter="quickCreatePatient" placeholder="Phone" class="w-full bg-white border border-green-200 p-2 rounded-lg text-sm outline-none">
                                    </td>
                                    <td class="p-2 flex gap-2">
                                        <input v-model="quickPatient.nid" @keyup.enter="quickCreatePatient" placeholder="NID" class="flex-1 bg-white border border-green-200 p-2 rounded-lg text-sm outline-none">
                                        <button @click="quickCreatePatient" class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 rounded-lg font-bold shadow-sm transition">
                                            <i class="fas fa-plus"></i>
                                        </button>
                                    </td>
                                    <td></td>
                                </tr>

                                <!-- Existing Rows -->
                                <tr v-for="p in patients" :key="p.id" class="hover:bg-green-50/30 transition group relative">
                                    <td class="p-5">
                                        <div class="font-bold text-gray-800">{{ p.name }}</div>
                                        <div class="text-xs text-gray-400 group-hover:text-emerald-600 transition">ID: {{p.id}}</div>
                                    </td>
                                    <td class="p-5">
                                        <span class="inline-block bg-gray-100 text-gray-600 px-2 py-1 rounded text-xs font-bold mr-2">{{ p.age || '?' }}</span> 
                                        <span class="text-gray-600 text-sm">{{ p.gender }}</span>
                                    </td>
                                    <td class="p-5 text-gray-600">{{ p.phone }}</td>
                                    <td class="p-5 font-mono text-sm text-gray-400">
                                        {{ p.nid }}
                                    </td>
                                    <td class="p-5 text-center">
                                        <button @click="openPatientModal(p)" class="bg-white text-emerald-600 hover:bg-emerald-600 hover:text-white border border-emerald-200 px-3 py-1 rounded-lg text-sm font-bold shadow-sm transition flex items-center gap-2 mx-auto">
                                            <i class="fas fa-edit"></i> Update
                                        </button>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- INVENTORY VIEW -->
                <div v-if="currentView === 'inventory'" class="max-w-7xl mx-auto">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-3xl font-bold text-emerald-900">Medicine Inventory</h2>
                        <button v-if="['admin','doctor'].includes(userRole)" @click="openRemedyModal()" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-bold shadow-md transition flex items-center gap-2">
                            <i class="fas fa-leaf"></i> Add Remedy
                        </button>
                    </div>

                    <!-- Add/Edit Remedy Modal -->
                    <div v-if="showRemedyModal" class="fixed inset-0 bg-emerald-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-lg shadow-2xl border border-green-100">
                            <h3 class="text-xl font-bold mb-6 text-gray-800 border-b border-gray-100 pb-2">
                                {{ isEditingRemedy ? 'Edit Remedy' : 'Add To Inventory' }}
                            </h3>
                            <form @submit.prevent="saveRemedy" class="space-y-4">
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Medicine Name</label>
                                    <input v-model="remedyForm.name" placeholder="E.g. Arnica Mont" required class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                </div>
                                <div class="grid grid-cols-2 gap-4">
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700 mb-1">Potency</label>
                                        <select v-model="remedyForm.potency" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                            <option value="30">30</option>
                                            <option value="200">200</option>
                                            <option value="1X">1X</option>
                                            <option value="6X">6X</option>
                                            <option value="12X">12X</option>
                                            <option value="60">60</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700 mb-1">Stock Qty</label>
                                        <input v-model="remedyForm.stock_quantity" type="number" placeholder="0" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                    </div>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Unit Price (BDT)</label>
                                    <input v-model="remedyForm.current_unit_price" type="number" step="0.01" class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition">
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Description / Indications</label>
                                    <textarea v-model="remedyForm.description" placeholder="Usage instructions..." class="w-full bg-gray-50 border border-gray-200 p-3 rounded-lg focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition h-24"></textarea>
                                </div>
                                <div class="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100">
                                    <button type="button" @click="showRemedyModal = false" class="px-5 py-2 text-gray-500 hover:text-gray-700 font-medium">Cancel</button>
                                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-bold shadow transition">{{ isEditingRemedy ? 'Update' : 'Add Item' }}</button>
                                </div>
                            </form>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        <div v-for="r in remedies" :key="r.id" class="bg-white p-5 rounded-xl border border-green-100 shadow-sm hover:shadow-lg hover:border-green-300 transition relative group flex flex-col h-full">
                            <button v-if="['admin','doctor'].includes(userRole)" @click="openRemedyModal(r)" class="absolute top-3 right-3 bg-gray-100 text-gray-500 hover:bg-emerald-600 hover:text-white p-2 w-8 h-8 flex items-center justify-center rounded-full transition opacity-0 group-hover:opacity-100 shadow-sm z-10">
                                <i class="fas fa-edit text-xs"></i>
                            </button>
                            
                            <div class="flex items-center gap-3 mb-3">
                                <div class="w-10 h-10 rounded-full bg-green-50 text-green-600 flex items-center justify-center border border-green-100">
                                    <i class="fas fa-flask"></i>
                                </div>
                                <div>
                                    <h4 class="font-bold text-lg text-gray-800 leading-tight">{{ r.name }}</h4>
                                    <span class="bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider">{{ r.potency }}</span>
                                </div>
                            </div>
                            
                            <p class="text-sm text-gray-500 mb-4 h-12 overflow-hidden line-clamp-2 leading-relaxed">{{ r.description }}</p>
                            
                            <div class="mt-auto flex justify-between items-center text-sm pt-4 border-t border-gray-50">
                                <span :class="r.stock_quantity < 10 ? 'text-red-500 font-bold bg-red-50 px-2 py-1 rounded' : 'text-gray-500 bg-gray-50 px-2 py-1 rounded'">
                                    Stock: {{ r.stock_quantity }}
                                </span>
                                <span class="font-bold text-emerald-700 text-base">BDT {{ r.current_unit_price }}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- VISITS VIEW -->
                <div v-if="currentView === 'visits'" class="max-w-7xl mx-auto">
                    <div class="flex justify-between items-center mb-6">
                        <h2 class="text-3xl font-bold text-emerald-900">Medical Visits</h2>
                        <button @click="showVisitModal = true" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-bold shadow-md transition flex items-center gap-2">
                            <i class="fas fa-stethoscope"></i> New Visit
                        </button>
                    </div>

                    <!-- New Visit Modal -->
                    <div v-if="showVisitModal" class="fixed inset-0 bg-emerald-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-4xl border border-green-100 max-h-[90vh] overflow-y-auto shadow-2xl">
                            <h3 class="text-xl font-bold mb-6 text-gray-800 border-b border-gray-100 pb-2">Record Visit & Billing</h3>
                            <form @submit.prevent="createVisit" class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                                <!-- LEFT COLUMN: MEDICAL -->
                                <div class="lg:col-span-2 space-y-4">
                                    <!-- Patient Selector -->
                                    <div class="bg-gray-50 p-4 rounded-xl border border-gray-200">
                                        <div class="flex justify-between items-center mb-3">
                                            <label class="block text-sm font-bold text-gray-700">Patient Details</label>
                                            <label class="flex items-center gap-2 cursor-pointer bg-white px-3 py-1 rounded-full border border-gray-200 shadow-sm hover:border-blue-400 transition">
                                                <input type="checkbox" v-model="isNewPatientForVisit" class="form-checkbox h-4 w-4 text-emerald-600 rounded">
                                                <span class="text-xs text-emerald-700 font-bold">New Patient?</span>
                                            </label>
                                        </div>
                                        
                                        <div v-if="!isNewPatientForVisit">
                                            <select v-model="visitForm.patient_id" class="w-full bg-white border border-gray-300 p-3 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition">
                                                <option value="">-- Select Existing Patient --</option>
                                                <option v-for="p in patients" :value="p.id">{{ p.name }} ({{ p.phone }})</option>
                                            </select>
                                        </div>
                                        
                                        <div v-else class="space-y-3 animate-fade-in">
                                            <input v-model="visitNewPatient.name" placeholder="Full Name" class="w-full bg-white border border-gray-300 p-2 rounded-lg focus:ring-2 focus:ring-emerald-500">
                                            <div class="flex gap-3">
                                                <input v-model="visitNewPatient.phone" placeholder="Phone" class="w-1/2 bg-white border border-gray-300 p-2 rounded-lg focus:ring-2 focus:ring-emerald-500">
                                                <input v-model="visitNewPatient.age" type="number" placeholder="Age" class="w-1/4 bg-white border border-gray-300 p-2 rounded-lg focus:ring-2 focus:ring-emerald-500">
                                                <select v-model="visitNewPatient.gender" class="w-1/4 bg-white border border-gray-300 p-2 rounded-lg focus:ring-2 focus:ring-emerald-500">
                                                    <option value="">Sex</option>
                                                    <option value="Male">M</option>
                                                    <option value="Female">F</option>
                                                </select>
                                            </div>
                                        </div>
                                    </div>
                                    
                                    <!-- Diagnosis Inputs -->
                                    <div class="grid grid-cols-2 gap-4">
                                        <div>
                                            <label class="block text-xs font-bold text-gray-500 mb-1 uppercase">Chief Complaint</label>
                                            <textarea v-model="visitForm.chief_complaint" required class="w-full bg-white border border-gray-200 p-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 h-32 resize-none"></textarea>
                                        </div>
                                        <div>
                                            <label class="block text-xs font-bold text-gray-500 mb-1 uppercase">Diagnosis</label>
                                            <textarea v-model="visitForm.diagnosis" class="w-full bg-white border border-gray-200 p-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 h-32 resize-none"></textarea>
                                        </div>
                                    </div>
                                    <div>
                                        <label class="block text-xs font-bold text-gray-500 mb-1 uppercase">Notes / Prescription</label>
                                        <textarea v-model="visitForm.notes" class="w-full bg-white border border-gray-200 p-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 h-20 resize-none"></textarea>
                                    </div>
                                </div>

                                <!-- RIGHT COLUMN: BILLING -->
                                <div class="bg-gray-50 p-6 rounded-xl border border-gray-200 flex flex-col h-full">
                                    <h4 class="font-bold text-emerald-800 mb-4 flex items-center gap-2 border-b border-gray-200 pb-2">
                                        <i class="fas fa-file-invoice-dollar"></i> Billing
                                    </h4>
                                    
                                    <div class="space-y-4 flex-grow">
                                        <!-- Doctor Fee -->
                                        <div>
                                            <label class="block text-xs font-bold text-gray-500 mb-1">Consultation Fee (BDT)</label>
                                            <input v-model="visitForm.consultation_fee" type="number" class="w-full bg-white border border-gray-300 p-2 rounded-lg font-mono text-right">
                                        </div>

                                        <!-- Medicines Picker -->
                                        <div>
                                            <label class="block text-xs font-bold text-gray-500 mb-1">Prescribe Medicine</label>
                                            <div class="flex gap-2">
                                                <select v-model="selectedRemedyId" class="flex-grow bg-white border border-gray-300 p-2 rounded-lg text-sm">
                                                    <option value="">Select Remedy...</option>
                                                    <option v-for="r in remedies" :value="r.id">{{ r.name }} {{ r.potency }} ({{ r.stock_quantity }})</option>
                                                </select>
                                                <button type="button" @click="addMedicine" class="bg-emerald-600 text-white px-3 rounded-lg hover:bg-emerald-700 transition">
                                                    <i class="fas fa-plus"></i>
                                                </button>
                                            </div>
                                        </div>

                                        <!-- Selected Medicines List -->
                                        <div v-if="visitForm.medicines.length > 0" class="bg-white rounded-lg border border-gray-200 p-2 max-h-32 overflow-y-auto custom-scrollbar">
                                            <div v-for="(m, idx) in visitForm.medicines" class="flex justify-between items-center text-sm p-2 border-b border-gray-100 last:border-0 hover:bg-gray-50">
                                                <div class="flex items-center gap-2">
                                                    <i class="fas fa-pills text-emerald-500 text-xs"></i>
                                                    <span class="font-medium text-gray-700">Item #{{ m.remedy_id }}</span>
                                                    <span class="text-xs bg-gray-100 px-2 rounded-full">x{{ m.quantity }}</span>
                                                </div>
                                                <button type="button" @click="visitForm.medicines.splice(idx, 1)" class="text-gray-400 hover:text-red-500 transition"><i class="fas fa-times"></i></button>
                                            </div>
                                        </div>

                                        <!-- Payment & Totals -->
                                        <div class="border-t-2 border-dashed border-gray-300 pt-4 mt-auto">
                                            <div class="flex justify-between items-center mb-2">
                                                <span class="text-sm text-gray-600">Total Bill</span>
                                                <span class="text-lg font-bold text-emerald-700">BDT {{ calculateTotal }}</span>
                                            </div>
                                            
                                            <label class="block text-xs font-bold text-gray-500 mb-1">Amount Paid Now</label>
                                            <input v-model="visitForm.amount_paid" type="number" class="w-full bg-white border-2 border-emerald-100 p-2 rounded-lg font-mono text-right focus:border-emerald-500 focus:outline-none transition">
                                        </div>
                                    </div>
                                    
                                    <div class="flex gap-3 mt-6">
                                        <button type="button" @click="showVisitModal = false" class="px-4 py-2 text-gray-500 hover:text-gray-700 font-medium">Cancel</button>
                                        <button type="submit" class="flex-grow bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg font-bold shadow-md transition">Save & Print</button>
                                    </div>
                                </div>
                            </form>
                        </div>
                    </div>

                    <!-- Visits List -->
                    <div class="space-y-4">
                        <div v-for="v in visits" :key="v.id" class="bg-white p-0 rounded-xl border border-green-100 shadow-sm relative overflow-hidden group hover:shadow-md transition">
                            <!-- Header Bar -->
                            <div class="bg-gray-50 p-4 border-b border-gray-100 flex justify-between items-center">
                                <div>
                                    <h4 class="font-bold text-lg text-emerald-900">{{ v.patient_name }}</h4>
                                    <p class="text-xs text-gray-500 flex items-center gap-2">
                                        <i class="far fa-clock"></i> {{ formatDate(v.visit_date) }}
                                    </p>
                                </div>
                                <div class="px-3 py-1 text-xs font-bold uppercase rounded-full border"
                                     :class="{
                                        'bg-green-100 text-green-700 border-green-200': v.payment_status === 'paid',
                                        'bg-amber-100 text-amber-800 border-amber-200': v.payment_status === 'partially paid',
                                        'bg-red-100 text-red-700 border-red-200': v.payment_status === 'pending',
                                        'bg-gray-100 text-gray-600 border-gray-200': v.payment_status === 'n/a'
                                     }">
                                    {{ v.payment_status }}
                                </div>
                            </div>
                            
                            <div class="p-6 grid grid-cols-1 md:grid-cols-2 gap-8">
                                <!-- Medical Data -->
                                <div class="space-y-4">
                                    <div>
                                        <p class="text-xs text-gray-400 uppercase font-bold mb-1 tracking-wider">Chief Complaint</p>
                                        <p class="text-sm text-gray-700 bg-gray-50 p-3 rounded-lg border border-gray-100">{{ v.chief_complaint }}</p>
                                    </div>
                                    <div v-if="v.diagnosis">
                                        <p class="text-xs text-gray-400 uppercase font-bold mb-1 tracking-wider">Diagnosis</p>
                                        <p class="text-sm text-gray-700">{{ v.diagnosis }}</p>
                                    </div>
                                    <div v-if="v.notes">
                                         <p class="text-xs text-gray-400 uppercase font-bold mb-1 tracking-wider">Notes</p>
                                         <p class="text-sm text-gray-500 italic">{{ v.notes }}</p>
                                    </div>
                                </div>

                                <!-- Financial Data -->
                                <div class="bg-emerald-50/50 p-5 rounded-xl border border-emerald-100 h-fit">
                                    <div class="flex justify-between text-sm mb-2 pb-2 border-b border-emerald-100/50">
                                        <span class="text-gray-500">Consultation</span>
                                        <span class="text-gray-700 font-mono">BDT {{ v.consultation_fee }}</span>
                                    </div>
                                    <div class="flex justify-between text-sm mb-2 pb-2 border-b border-emerald-100/50">
                                        <span class="text-gray-500">Medicine Bill</span>
                                        <span class="text-gray-700 font-mono">BDT {{ v.medicine_bill || 0 }}</span>
                                    </div>
                                    <div class="flex justify-between font-bold mb-1 text-emerald-900 text-lg mt-2">
                                        <span>Total</span>
                                        <span>BDT {{ v.total_bill }}</span>
                                    </div>
                                    <div class="flex justify-between text-sm items-center mt-2">
                                        <span class="text-gray-500">Paid:</span>
                                        <span class="font-bold text-emerald-600 bg-white px-2 py-0.5 rounded shadow-sm">BDT {{ v.amount_paid }}</span>
                                    </div>
                                    <div class="flex justify-between font-bold mt-3 pt-3 border-t border-emerald-200">
                                        <span class="text-red-500">DUE</span>
                                        <div class="flex items-center gap-2">
                                            <span class="text-red-500">BDT {{ v.due_amount }}</span>
                                            <button v-if="userRole === 'admin'" @click="openPaymentModal(v)" class="text-xs bg-white border border-gray-200 hover:border-emerald-500 text-gray-500 hover:text-emerald-600 w-6 h-6 rounded-full flex items-center justify-center transition shadow-sm" title="Edit Bill">
                                                <i class="fas fa-pencil-alt text-[10px]"></i>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Admin Payment Modal -->
                    <div v-if="showPaymentModal" class="fixed inset-0 bg-emerald-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                        <div class="bg-white p-8 rounded-2xl w-full max-w-sm border border-green-100 shadow-2xl animate-fade-in">
                            <h3 class="text-xl font-bold mb-6 text-emerald-900 border-b border-green-100 pb-2">Edit Payment / Bill</h3>
                            <form @submit.prevent="savePayment" class="space-y-4">
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Consultation Fee</label>
                                    <input v-model="paymentForm.consultation_fee" type="number" class="w-full bg-gray-50 border border-green-200 p-3 rounded-lg font-mono text-gray-800 outline-none focus:ring-1 focus:ring-emerald-500">
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Medicine Bill (Override)</label>
                                    <input v-model="paymentForm.medicine_bill" type="number" class="w-full bg-gray-50 border border-green-200 p-3 rounded-lg font-mono text-gray-800 outline-none focus:ring-1 focus:ring-emerald-500">
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-gray-700 mb-1">Total Paid</label>
                                    <input v-model="paymentForm.amount_paid" type="number" class="w-full bg-gray-50 border border-green-200 p-3 rounded-lg font-mono text-gray-800 outline-none focus:ring-1 focus:ring-emerald-500">
                                </div>
                                
                                <div class="p-4 bg-emerald-50 rounded-xl text-center border border-emerald-100">
                                    <p class="text-xs text-emerald-600 font-bold uppercase tracking-wider">New Due Amount</p>
                                    <p class="text-2xl font-bold text-red-500 mt-1">
                                        {{ paymentDue }}
                                    </p>
                                </div>

                                <div class="flex justify-end gap-3 mt-6">
                                    <button type="button" @click="showPaymentModal = false" class="px-5 py-2 text-gray-500 hover:text-gray-700 font-medium">Cancel</button>
                                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-2 rounded-lg font-bold shadow-md transition">Update</button>
                                </div>
                            </form>
                        </div>
                    </div>

                </div>

                <!-- REPORTS VIEW (SQL VIEWS) -->
                <div v-if="currentView === 'reports'" class="max-w-7xl mx-auto">
                    <h2 class="text-3xl font-bold mb-8 text-emerald-900">System Reports</h2>
                    
                    <div class="bg-white rounded-xl shadow-lg border border-green-100 overflow-hidden mb-8">
                        <div class="p-6 bg-gray-50 border-b border-gray-100">
                            <h3 class="text-lg font-bold text-gray-800">Patient History Log</h3>
                        </div>
                        <div class="overflow-x-auto">
                            <table class="w-full text-sm">
                                <thead class="bg-emerald-50 text-emerald-900">
                                    <tr>
                                        <th class="p-4 text-left font-bold">Date</th>
                                        <th class="p-4 text-left font-bold">Patient</th>
                                        <th class="p-4 text-left font-bold">Complaint</th>
                                        <th class="p-4 text-left font-bold">Diagnosis</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-gray-100">
                                    <tr v-for="r in reports.history" class="hover:bg-green-50/50 transition">
                                        <td class="p-4 text-gray-600 whitespace-nowrap">{{ formatDate(r.visit_date) }}</td>
                                        <td class="p-4 font-bold text-emerald-700">{{ r.patient_name }}</td>
                                        <td class="p-4 text-gray-600">{{ r.chief_complaint }}</td>
                                        <td class="p-4 text-gray-600">{{ r.diagnosis }}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                </div>

            </main>
        </div>
        
        <!-- CHAT WIDGET -->
        <div v-if="token" class="fixed bottom-6 right-6 z-[9999]">
            <!-- Chat Window -->
            <div v-if="isChatOpen" class="bg-white rounded-2xl shadow-2xl border border-gray-200 w-80 mb-4 overflow-hidden flex flex-col animate-slide-up" style="height: 480px;">
                <div class="bg-gradient-to-r from-emerald-600 to-teal-600 p-4 flex justify-between items-center text-white">
                    <h4 class="font-bold flex items-center gap-2"><i class="fas fa-robot"></i> Clinic Assistant</h4>
                    <button @click="isChatOpen = false" class="hover:text-gray-200"><i class="fas fa-times"></i></button>
                </div>
                <div id="chat-container" class="flex-grow p-4 overflow-y-auto space-y-3 bg-gray-50">
                    <div v-for="msg in chatMessages" :class="msg.sender === 'user' ? 'text-right' : 'text-left'">
                        <div class="inline-block px-3 py-2 rounded-lg text-sm max-w-[85%]" 
                             :class="msg.sender === 'user' ? 'bg-emerald-600 text-white rounded-br-none' : 'bg-white text-gray-800 border border-gray-200 rounded-bl-none shadow-sm'">
                            {{ msg.text }}
                        </div>
                    </div>
                    <div v-if="isChatThinking" class="text-xs text-gray-400 italic text-center animate-pulse">Thinking...</div>
                </div>
                <div class="p-3 bg-white border-t border-gray-100 flex gap-2">
                    <input v-model="chatInput" @keyup.enter="sendMessage" placeholder="Ask about inventory, patients, revenue..." class="flex-grow text-sm border border-gray-200 rounded-full px-4 py-2 focus:outline-none focus:border-emerald-500">
                    <button @click="sendMessage" class="w-8 h-8 rounded-full bg-emerald-600 text-white flex items-center justify-center hover:bg-emerald-700 transition">
                        <i class="fas fa-paper-plane text-xs"></i>
                    </button>
                </div>
            </div>
            
            <!-- Floating Button -->
            <button @click="isChatOpen = !isChatOpen" class="w-14 h-14 rounded-full bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-xl hover:shadow-2xl hover:scale-110 transition flex items-center justify-center text-2xl z-[9999]">
                <i class="fas" :class="isChatOpen ? 'fa-comment-slash' : 'fa-comment-alt'"></i>
            </button>
        </div>

    </div>

    <script>
        const { createApp } = Vue;

        createApp({
            data() {
                return {
                    token: localStorage.getItem('token') || null,
                    userRole: localStorage.getItem('userRole') || 'staff',
                    currentView: 'dashboard',
                    loginForm: { username: '', password: '' },
                    
                    stats: { patients: 0, visits: 0, remedies: 0, today_visits: 0 },
                    
                    patients: [],
                    remedies: [],
                    visits: [],
                    reports: { history: [], revenue: [] },
                    
                    // Chatbot State
                    isChatOpen: false,
                    chatInput: '',
                    chatMessages: [
                        {sender: 'bot', text: 'Hello! I am your clinic assistant. Ask me anything.'}
                    ],
                    isChatThinking: false,

                    showPatientModal: false,
                    isEditingPatient: false,
                    patientForm: { id: null, name: '', nid: '', phone: '', age: '', gender: '', address: '' },
                    quickPatient: { name: '', nid: '', phone: '', age: '', gender: '' },
                    
                    showRemedyModal: false,
                    isEditingRemedy: false,
                    remedyForm: { id: null, name: '', potency: '30', description: '', current_unit_price: '', stock_quantity: 0 },
                    
                    showVisitModal: false,
                    selectedRemedyId: '',
                    isNewPatientForVisit: false,
                    visitNewPatient: { name: '', phone: '', age: '', gender: '' },
                    visitForm: { 
                        patient_id: '', 
                        chief_complaint: '', 
                        diagnosis: '', 
                        notes: '', 
                        consultation_fee: 500,
                        medicines: [],
                        amount_paid: 0
                    },
                    
                    showPaymentModal: false,
                    paymentForm: { visit_id: null, consultation_fee: 0, medicine_bill: 0, amount_paid: 0 }
                }
            },
            async mounted() {
                if (this.token) {
                    await this.loadAll();
                }
            },
            computed: {
                paymentDue() {
                    const c = parseFloat(this.paymentForm.consultation_fee || 0);
                    const m = parseFloat(this.paymentForm.medicine_bill || 0);
                    const p = parseFloat(this.paymentForm.amount_paid || 0);
                    return (c + m - p).toFixed(2);
                },
                calculateTotal() {
                    let fee = parseFloat(this.visitForm.consultation_fee || 0);
                    let meds = this.visitForm.medicines.reduce((sum, item) => {
                         let r = this.remedies.find(r => r.id == item.remedy_id);
                         let price = r ? parseFloat(r.current_unit_price || 0) : 0;
                         return sum + (price * item.quantity);
                    }, 0);
                    return fee + meds;
                }
            },
            methods: {
                async sendMessage() {
                    const txt = this.chatInput.trim();
                    if (!txt) return;
                    
                    this.chatMessages.push({sender: 'user', text: txt});
                    this.chatInput = '';
                    this.isChatThinking = true;
                    
                    try {
                        const res = await this.api('/api/chat', 'POST', { message: txt });
                        this.chatMessages.push({sender: 'bot', text: res.reply});
                    } catch (e) {
                         console.error(e);
                         this.chatMessages.push({sender: 'bot', text: 'Connection timeout. Database might be busy.'});
                    } finally {
                        this.isChatThinking = false;
                        this.$nextTick(() => {
                            const container = document.getElementById('chat-container');
                            if(container) container.scrollTop = container.scrollHeight;
                        });
                    }
                },
                addMedicine() {
                    if (!this.selectedRemedyId) return;
                    // Check if already added
                    let existing = this.visitForm.medicines.find(m => m.remedy_id == this.selectedRemedyId);
                    if (existing) {
                        existing.quantity++;
                    } else {
                        this.visitForm.medicines.push({ remedy_id: this.selectedRemedyId, quantity: 1 });
                    }
                    this.selectedRemedyId = '';
                },
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
                            this.userRole = data.role;
                            localStorage.setItem('token', this.token);
                            localStorage.setItem('userRole', this.userRole);
                            await this.loadAll();
                        } else {
                            alert(data.detail);
                        }
                    } catch (e) { alert('Login failed'); }
                },
                logout() {
                    this.token = null;
                    this.userRole = 'staff';
                    localStorage.removeItem('token');
                    localStorage.removeItem('userRole');
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
                    const res = await fetch(url, opts);
                    
                    if (res.status === 401) {
                        this.logout();
                        alert("Your session has expired. Please login again.");
                        return null;
                    }
                    
                    return await res.json();
                },
                async loadAll() {
                    this.stats = await this.api('/api/stats');
                    this.patients = await this.api('/api/patients');
                    this.remedies = await this.api('/api/remedies');
                    this.visits = await this.api('/api/visits');
                    this.reports.history = await this.api('/api/reports/history');
                },
                openPatientModal(patient = null) {
                    if (patient) {
                        this.isEditingPatient = true;
                        this.patientForm = { ...patient };
                    } else {
                        this.isEditingPatient = false;
                        this.patientForm = { id: null, name: '', nid: '', phone: '', age: '', gender: '', address: '' };
                    }
                    this.showPatientModal = true;
                },
                async savePatient() {
                    const method = this.isEditingPatient ? 'PUT' : 'POST';
                    const url = this.isEditingPatient ? `/api/patients/${this.patientForm.id}` : '/api/patients';
                    await this.api(url, method, this.patientForm);
                    this.showPatientModal = false;
                    this.loadAll();
                },
                async quickCreatePatient() {
                    if (!this.quickPatient.name) return alert("Name is required");
                    await this.api('/api/patients', 'POST', this.quickPatient);
                    this.quickPatient = { name: '', nid: '', phone: '', age: '', gender: '' };
                    this.loadAll();
                    // Refocus name field for rapid entry
                    this.$nextTick(() => this.$refs.quickName.focus());
                },
                openRemedyModal(rem = null) {
                    if (rem) {
                        this.isEditingRemedy = true;
                        this.remedyForm = { ...rem }; // Copy data
                    } else {
                        this.isEditingRemedy = false;
                        this.remedyForm = { name: '', potency: '30', description: '', current_unit_price: '', stock_quantity: 0 };
                    }
                    this.showRemedyModal = true;
                },
                async saveRemedy() {
                    const method = this.isEditingRemedy ? 'PUT' : 'POST';
                    const url = this.isEditingRemedy ? `/api/remedies/${this.remedyForm.id}` : '/api/remedies';
                    
                    await this.api(url, method, this.remedyForm);
                    this.showRemedyModal = false;
                    this.loadAll();
                },
                // Alias for old call if needed, or remove createRemedy entirely
                async createRemedy() { await this.saveRemedy(); },

                openPaymentModal(visit) {
                    this.paymentForm = {
                        visit_id: visit.id,
                        consultation_fee: visit.consultation_fee,
                        medicine_bill: visit.medicine_bill,
                        amount_paid: visit.amount_paid
                    };
                    this.showPaymentModal = true;
                },
                async savePayment() {
                    await this.api(`/api/visits/${this.paymentForm.visit_id}/payment`, 'PUT', this.paymentForm);
                    this.showPaymentModal = false;
                    this.loadAll();
                },

                async createVisit() {
                    if (this.isNewPatientForVisit) {
                         if (!this.visitNewPatient.name) return alert("Patient Name is required");
                         const patientRes = await this.api('/api/patients', 'POST', this.visitNewPatient);
                         if (!patientRes.id) return alert("Failed to create patient");
                         this.visitForm.patient_id = patientRes.id;
                    }
                    
                    if (!this.visitForm.patient_id) return alert("Please select or create a patient");

                    await this.api('/api/visits', 'POST', this.visitForm);
                    this.showVisitModal = false;
                    this.visitForm = { 
                        patient_id: '', 
                        chief_complaint: '', 
                        diagnosis: '', 
                        notes: '', 
                        consultation_fee: 500, 
                        medicines: [], 
                        amount_paid: 0 
                    };
                    this.isNewPatientForVisit = false;
                    this.visitNewPatient = { name: '', phone: '', age: '', gender: '' };
                    this.loadAll();
                },
                formatDate(str) {
                    if (!str) return '-';
                    return new Date(str).toLocaleDateString() + ' ' + new Date(str).toLocaleTimeString();
                }
            }
        }).mount('#app');
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    # Initialize DB every time app starts
    init_database()
    print("="*60)
    print("🚀 SERVER STARTED")
    print("👉 Local Link: http://127.0.0.1:8002")
    print(f"👉 Network Link: http://192.168.0.100:8002")
    print("="*60)
    # Ensure host is 0.0.0.0 to accept external connections
    uvicorn.run(app, host="0.0.0.0", port=8002)
