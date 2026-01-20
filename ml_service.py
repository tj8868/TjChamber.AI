import sqlite3
import re
import os
import sys
from gpt4all import GPT4All

# ============================================================
# CONFIGURATION
# ============================================================
# Priority 1: TinyLlama (Fast, Small)
# Priority 2: Orca Mini (Present in folder, Backup)
MODELS = [
    "tinyllama-1.1b-chat-v1.0.Q4_0.gguf",
    "orca-mini-3b-gguf2-q4_0.gguf"
]

class ChatService:
    _model = None
    _model_name = None

    def __init__(self, db_path="chamber.db"):
        self.db_path = db_path

    @classmethod
    def load_model(cls):
        """Robust Model Loader with Fallbacks."""
        if cls._model is not None:
            return

        print("\n" + "="*50)
        print("🧠 CHATBOT INITIALIZATION SEQUENCE")
        print("="*50)

        for model_name in MODELS:
            cls._model_name = model_name
            model_path = os.path.join(os.getcwd(), model_name)
            
            # Helper: Check if file exists locally
            file_exists = os.path.exists(model_path)
            
            # If it's the second option (Orca) and it doesn't exist, skip it to avoid huge download
            if model_name != MODELS[0] and not file_exists:
                continue

            print(f"👉 Trying Model: {model_name}")
            if file_exists:
                print(f"   [File Found locally: {os.path.getsize(model_path) / (1024*1024):.1f} MB]")
            else:
                print("   [File Not Found - Will Attempt Download]")

            # 1. Try GPU
            try:
                print("   🚀 Attempting GPU Load (Vulkan)...")
                cls._model = GPT4All(model_name, model_path=os.getcwd(), allow_download=True, device='gpu')
                print(f"   ✅ SUCCESS: Loaded {model_name} on GPU!")
                break
            except Exception as e_gpu:
                print(f"   ⚠️ GPU Failed: {e_gpu}")

            # 2. Try CPU Fallback
            try:
                print("   🐢 Falling back to CPU Load...")
                cls._model = GPT4All(model_name, model_path=os.getcwd(), allow_download=True, device='cpu')
                print(f"   ✅ SUCCESS: Loaded {model_name} on CPU!")
                break
            except Exception as e_cpu:
                print(f"   ❌ CPU Failed: {e_cpu}")
                print("   ❌ Checks next model...")
        
        if cls._model is None:
            print("\n❌ ALL MODELS FAILED TO LOAD.")
            print("⚠️ Chatbot will operate in 'Basic Mode' (Regex only - Inventory/Revenue checks).")
        else:
            print(f"✅ FINAL STATUS: Active Model is {cls._model_name}\n")


    def get_db_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_inventory_status(self, medicine_name):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, stock, type FROM medicines WHERE name LIKE ?", (f"%{medicine_name}%",))
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return None
        
        response = "Here is what I found in inventory:\n"
        for row in results:
            response += f"- {row['name']} ({row['type']}): {row['stock']} units\n"
        return response

    def get_total_revenue(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
           cursor.execute("SELECT SUM(amount) as total FROM sales")
           result = cursor.fetchone()
           total = result['total'] if result and result['total'] else 0
           conn.close()
           return f"Total Revenue: ${total:.2f}"
        except sqlite3.OperationalError:
            conn.close()
            return "Revenue data unavailable."

    def get_patient_count(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM patients")
        result = cursor.fetchone()
        conn.close()
        return f"Total Patients: {result['count']}"

    def get_response(self, user_message: str) -> str:
        """
        Hybrid Approach: Regex (Fast) -> AI (Smart)
        """
        if not user_message: return ""
        msg_lower = user_message.lower().strip()

        # 1. FAST PATH (Regex)
        stock_match = re.search(r"(?:do we have|check stock|inventory)\s+(.+)", msg_lower)
        if stock_match:
            medicine_name = stock_match.group(1).replace("?", "").replace("for", "").strip()
            result = self.get_inventory_status(medicine_name)
            if result: return result
            return f"I couldn't find '{medicine_name}' in the inventory."

        if "revenue" in msg_lower or "sales" in msg_lower:
            return self.get_total_revenue()

        if "patient" in msg_lower and ("count" in msg_lower or "how many" in msg_lower):
            return self.get_patient_count()

        # 2. SLOW PATH (AI)
        if self.__class__._model:
            system_prompt = "You are a helpful assistant for a Homeopathic Clinic. Be brief."
            full_prompt = f"{system_prompt}\nUser: {user_message}\nAssistant:"
            try:
                return self.__class__._model.generate(full_prompt, max_tokens=128)
            except Exception as e:
                print(f"AI Error: {e}")
                return "I'm having trouble thinking. Please try again."
        else:
            return "The AI model is unavailable. I can only answer questions about Inventory, Revenue, and Patient Counts."
