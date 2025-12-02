import sqlite3
import os
import uuid
import time
import datetime
import requests
import psutil
import pytz
import docker
from pathlib import Path

# --- Constants ---
DB_FILE = Path("/app/data/metrics.db")
LOOP_INTERVAL_SECONDS = 10
LIMA_TZ = pytz.timezone('America/Lima')
PING_URL = "http://www.google.com"
STATE_CHANGE_THRESHOLD = 3 # Number of consecutive identical statuses to consider a state "stable"

# --- Environment Variables ---
SECRET_KEY = os.getenv('SECRET_KEY')
HEARTBEAT_URL = os.getenv('HEARTBEAT_URL')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

# --- Global State for Alerting ---
last_stable_status = None
transient_status = None
transient_counter = 0

def initialize_database():
    """Initializes the SQLite database and its schema."""
    try:
        # Ensure the data directory exists
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        print("Initializing database...")
        
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()

        # Enable WAL mode for better concurrency
        cur.execute("PRAGMA journal_mode=WAL;")
        print("WAL mode enabled.")

        # Create table with the new schema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id TEXT PRIMARY KEY,
                timestamp_lima TEXT NOT NULL,
                cpu_percent REAL NOT NULL,
                ram_percent REAL NOT NULL,
                ram_used_mb REAL NOT NULL,
                disk_percent REAL NOT NULL,
                container_count INTEGER NOT NULL,
                internet_ok INTEGER NOT NULL,
                ping_ms REAL,
                worker_status INTEGER,
                cycle_duration_ms REAL
            )
        """)
        con.commit()
        con.close()
        print("Database is initialized and ready.")
    except sqlite3.Error as e:
        print(f"Database error during initialization: {e}")
        raise

def get_initial_stable_status():
    """Retrieves the last known worker_status from the DB to set the initial stable state."""
    try:
        if not DB_FILE.exists():
            return None
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()
        cur.execute("SELECT worker_status FROM metrics ORDER BY timestamp_lima DESC LIMIT 1;")
        result = cur.fetchone()
        con.close()
        # The status can be an integer or None, which is what we want
        return result[0] if result else None
    except Exception as e:
        print(f"Could not determine initial state from DB, assuming None. Error: {e}")
        return None

def get_system_metrics():
    """Collects CPU, RAM, and Disk metrics."""
    cpu_percent = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        "cpu_percent": cpu_percent,
        "ram_percent": ram.percent,
        "ram_used_mb": ram.used / (1024 * 1024),
        "disk_percent": disk.percent
    }

def get_container_count():
    """Counts running Docker containers."""
    try:
        client = docker.from_env(timeout=2)
        return len(client.containers.list())
    except Exception as e:
        print(f"Could not connect to Docker socket: {e}")
        return -1

def check_internet_and_ping():
    """Checks for internet connectivity and measures latency to Google."""
    try:
        start_time = time.monotonic()
        # Use HEAD request for efficiency as we don't need the body
        response = requests.head(PING_URL, timeout=2)
        end_time = time.monotonic()
        if response.status_code >= 200 and response.status_code < 400:
            return 1, (end_time - start_time) * 1000
    except requests.exceptions.RequestException:
        pass
    return 0, None

def send_heartbeat():
    """Sends a heartbeat to the Cloudflare worker."""
    if not SECRET_KEY or not HEARTBEAT_URL:
        if not hasattr(send_heartbeat, "warned"):
            print("Warning: Missing SECRET_KEY or HEARTBEAT_URL.")
            send_heartbeat.warned = True
        return None
    headers = {"Authorization": f"Bearer {SECRET_KEY}"}
    try:
        response = requests.post(HEARTBEAT_URL, headers=headers, timeout=3)
        return response.status_code
    except requests.exceptions.RequestException as e:
        print(f"Heartbeat request failed: {e}")
        return None

def save_metrics_to_db(metrics):
    """Saves a dictionary of metrics to the SQLite database."""
    try:
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO metrics (
                id, timestamp_lima, cpu_percent, ram_percent, ram_used_mb, 
                disk_percent, container_count, internet_ok, ping_ms, worker_status, cycle_duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            metrics['timestamp_lima'],
            metrics['cpu_percent'],
            metrics['ram_percent'],
            metrics['ram_used_mb'],
            metrics['disk_percent'],
            metrics['container_count'],
            metrics['internet_ok'],
            metrics['ping_ms'],
            metrics['worker_status'],
            metrics['cycle_duration_ms']
        ))
        con.commit()
        con.close()
    except sqlite3.Error as e:
        print(f"Database error when saving metrics: {e}")

def send_n8n_alert(previous_status, new_status):
    """Sends a formatted alert to the n8n webhook for a confirmed state change."""
    if not N8N_WEBHOOK_URL:
        print("Warning: N8N_WEBHOOK_URL is not set. Could not send alert.")
        return

    title = "⚠️ Cambio de Estado en Heartbeat-Monitor ⚠️"
    message = f"El estado del worker ha cambiado.\n\nNuevo Estado: `{new_status or 'N/A'}`\nEstado Anterior: `{previous_status or 'N/A'}`"
    
    try:
        alert_payload = {"title": title, "message": message}
        requests.post(N8N_WEBHOOK_URL, json=alert_payload, timeout=2)
        print(f"STATE CHANGE ALERT sent to n8n: {previous_status or 'N/A'} -> {new_status or 'N/A'}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send state change alert to n8n: {e}")

def main():
    """Main monitoring loop with detailed state change detection."""
    global last_stable_status, transient_status, transient_counter
    
    initialize_database()
    
    last_stable_status = get_initial_stable_status()
    transient_status = last_stable_status
    transient_counter = 0 # Start counter at 0; first observation will make it 1
    
    print(f"Starting monitoring loop. Initial stable state: {last_stable_status}")
    
    while True:
        try:
            # 1. Clock-Aligned Execution
            current_time = time.time()
            wait_seconds = LOOP_INTERVAL_SECONDS - (current_time % LOOP_INTERVAL_SECONDS)
            time.sleep(wait_seconds)
            
            cycle_start_time = time.monotonic()
            timestamp_lima = datetime.datetime.now(LIMA_TZ).isoformat()

            # 2. Collect Metrics
            internet_ok, ping_ms = check_internet_and_ping()
            worker_status = send_heartbeat() if internet_ok else None
            
            # 3. Handle State Machine Logic
            if worker_status == transient_status:
                transient_counter += 1
            else:
                # The status has changed from the last cycle, reset counter and update transient status
                transient_status = worker_status
                transient_counter = 1

            # Check if the transient state has become stable
            if transient_counter >= STATE_CHANGE_THRESHOLD:
                # A new stable state is confirmed. Check if it's different from the last stable state.
                if transient_status != last_stable_status:
                    send_n8n_alert(last_stable_status, transient_status)
                    last_stable_status = transient_status
            
            # 4. Save Metrics
            cycle_duration_ms = (time.monotonic() - cycle_start_time) * 1000
            all_metrics = {
                "timestamp_lima": timestamp_lima, **get_system_metrics(), "container_count": get_container_count(),
                "internet_ok": internet_ok, "ping_ms": ping_ms, "worker_status": worker_status, "cycle_duration_ms": cycle_duration_ms
            }
            save_metrics_to_db(all_metrics)

            # 5. Log success message
            log_msg = (f"{timestamp_lima} - Metrics saved. "
                       f"Current: {worker_status or 'N/A'}. "
                       f"Transient: {transient_status or 'N/A'} ({transient_counter}/{STATE_CHANGE_THRESHOLD}). "
                       f"Stable: {last_stable_status or 'N/A'}.")
            print(log_msg)

        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(LOOP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()