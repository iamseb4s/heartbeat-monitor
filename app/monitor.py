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
PING_URL = "http://www.google.com" # Use Google to avoid Cloudflare single point of failure

# --- Environment Variables ---
SECRET_KEY = os.getenv('SECRET_KEY')
HEARTBEAT_URL = os.getenv('HEARTBEAT_URL')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

# --- Global State for Alerting ---
last_worker_status = None

def initialize_database():
    """
    Initializes the SQLite database and creates the 'metrics' table if it doesn't exist.
    Enables Write-Ahead Logging (WAL) mode for better concurrency.
    """
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

def get_last_known_status():
    """Retrieves the last known worker_status from the database."""
    try:
        if not DB_FILE.exists():
            return None
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()
        cur.execute("SELECT worker_status FROM metrics ORDER BY timestamp_lima DESC LIMIT 1;")
        result = cur.fetchone()
        con.close()
        if result and result[0] is not None:
            return int(result[0]) # Convert to int as worker_status is INTEGER
        return None
    except sqlite3.Error as e:
        print(f"Database error when retrieving last status: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while getting last known status: {e}")
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
        print(f"Could not connect to Docker socket to count containers: {e}")
        return -1

def check_internet_and_ping():
    """Checks for internet connectivity and measures latency to Google."""
    try:
        start_time = time.monotonic()
        # Use HEAD request for efficiency as we don't need the body
        response = requests.head(PING_URL, timeout=2)
        end_time = time.monotonic()
        if response.status_code >= 200 and response.status_code < 400:
            ping_ms = (end_time - start_time) * 1000
            return 1, ping_ms
    except requests.exceptions.RequestException:
        pass
    return 0, None

def send_heartbeat():
    """Sends a heartbeat to the Cloudflare worker."""
    if not SECRET_KEY or not HEARTBEAT_URL:
        if not hasattr(send_heartbeat, "warned"):
            print("Warning: Missing SECRET_KEY or HEARTBEAT_URL. Cannot send heartbeat.")
            send_heartbeat.warned = True # Print warning only once
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

def main():
    """Main monitoring loop with clock-aligned execution."""
    global last_worker_status
    
    initialize_database()
    
    last_worker_status = get_last_known_status()
    is_initial_run = (last_worker_status is None)
    
    print(f"Starting monitoring loop. Initial last_worker_status: {last_worker_status}, Is initial run: {is_initial_run}")
    
    while True:
        try:
            # 1. Clock-Aligned Execution Calculation
            current_time = time.time()
            wait_seconds = LOOP_INTERVAL_SECONDS - (current_time % LOOP_INTERVAL_SECONDS)
            time.sleep(wait_seconds)
            
            cycle_start_time = time.monotonic()
            timestamp_lima = datetime.datetime.now(LIMA_TZ).isoformat()

            # 2. Collect all metrics
            internet_ok, ping_ms = check_internet_and_ping()
            worker_status = send_heartbeat() if internet_ok else None
            
            all_metrics = {
                "timestamp_lima": timestamp_lima,
                **get_system_metrics(),
                "container_count": get_container_count(),
                "internet_ok": internet_ok,
                "ping_ms": ping_ms,
                "worker_status": worker_status
            }
            
            # Calculate cycle duration before saving
            cycle_duration_ms = (time.monotonic() - cycle_start_time) * 1000
            all_metrics["cycle_duration_ms"] = cycle_duration_ms

            # 3. Save metrics to the database
            save_metrics_to_db(all_metrics)

            # 4. Handle worker status change alert (to n8n)
            if worker_status != last_worker_status:
                should_alert = True
                # Suppress alert only on the very first successful run from a clean DB
                if is_initial_run and worker_status is not None:
                    should_alert = False
                
                if should_alert:
                    if N8N_WEBHOOK_URL:
                        try:
                            alert_payload = {
                                "title": f"🚨 Alerta de Heartbeat-Monitor 🚨",
                                "message": f"El estado del worker de Cloudflare ha cambiado.\nAnterior: `{last_worker_status or 'N/A'}`\nActual: `{worker_status or 'N/A'}`",
                                "details": {
                                    "timestamp_lima": timestamp_lima,
                                    "heartbeat_url": HEARTBEAT_URL
                                }
                            }
                            requests.post(N8N_WEBHOOK_URL, json=alert_payload, timeout=2)
                            print(f"Alert successfully sent to n8n for status change: {last_worker_status or 'N/A'} -> {worker_status or 'N/A'}")
                        except requests.exceptions.RequestException as e:
                            print(f"Failed to send alert to n8n: {e}")
                    else:
                        print("Warning: N8N_WEBHOOK_URL is not set. Could not send alert.")
                
                last_worker_status = worker_status
            
            # This is no longer the initial run after the first cycle
            is_initial_run = False
            
            # 5. Log success message 
            print(f"{timestamp_lima} - Metrics saved. Cycle duration: {all_metrics['cycle_duration_ms']:.2f}ms")

        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()