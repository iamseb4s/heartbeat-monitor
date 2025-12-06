import sqlite3
import os
import uuid
import time
import datetime
import requests
import psutil
import pytz
import docker
import json
import socket
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Force IPv4 for requests to avoid IPv6 DNS lookup delays in Docker/Alpine ---
class IPv4Adapter(HTTPAdapter):
    """Forces the connection to use only IPv4 to avoid IPv6 timeouts in Docker/Alpine."""
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = PoolManager(
            num_pools=connections, 
            maxsize=maxsize, 
            block=block, 
            strict=True,
            **pool_kwargs
        )
    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs['socket_options'] = socket.AF_INET
        return super().proxy_manager_for(proxy, **proxy_kwargs)
    def get_connection(self, url, proxies=None):
        conn = super().get_connection(url, proxies)
        # Force the socket family to INET (IPv4)
        if conn.conn_kw.get('socket_options') is None:
             conn.conn_kw['family'] = socket.AF_INET
        return conn

# --- Global Reusable Session ---
# This keeps connections alive (Keep-Alive) and avoids re-negotiating SSL each time.
session = requests.Session()
session.mount('https://', IPv4Adapter())
session.mount('http://', IPv4Adapter())


# --- Constants ---
DB_FILE = Path("/app/data/metrics.db")
LOOP_INTERVAL_SECONDS = 10
LIMA_TZ = pytz.timezone('America/Lima')
PING_URL = "http://www.google.com"
STATE_CHANGE_THRESHOLD = 4 # Number of consecutive identical statuses to consider a state "stable"
SERVICE_TIMEOUT_SECONDS = 2 # Global timeout for service health checks (in seconds)

# --- Environment Variables & Dynamic Config ---
SECRET_KEY = os.getenv('SECRET_KEY')
HEARTBEAT_URL = os.getenv('HEARTBEAT_URL')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

def parse_services_from_env():
    """Parses service configuration from environment variables."""
    services = {}
    service_names_str = os.getenv('SERVICE_NAMES', '')
    if not service_names_str:
        print("Warning: SERVICE_NAMES environment variable not set. No services will be monitored.")
        return services
        
    service_names = [name.strip() for name in service_names_str.split(',')]
    
    for name in service_names:
        url = os.getenv(f'SERVICE_URL_{name}')
        if url:
            services[name] = url
        else:
            print(f"Warning: Missing URL for service '{name}'. Environment variable SERVICE_URL_{name} not found.")
            
    return services

SERVICES_TO_CHECK = parse_services_from_env()

# --- Global State for Alerting ---
last_stable_status = None
transient_status = None
transient_counter = 0

# --- Database Functions ---
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
                cycle_duration_ms INTEGER,
                services_health TEXT
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

def save_metrics_to_db(metrics):
    """Saves a dictionary of metrics to the SQLite database."""
    try:
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO metrics (id, timestamp_lima, cpu_percent, ram_percent, ram_used_mb, 
            disk_percent, container_count, internet_ok, ping_ms, worker_status, cycle_duration_ms, services_health)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
            (str(uuid.uuid4()), metrics['timestamp_lima'], metrics['cpu_percent'], metrics['ram_percent'], metrics['ram_used_mb'], 
            metrics['disk_percent'], metrics['container_count'], metrics['internet_ok'], metrics['ping_ms'], 
            metrics['worker_status'], metrics['cycle_duration_ms'], metrics['services_health']))
        con.commit()
        con.close()
    except sqlite3.Error as e:
        print(f"Database error when saving metrics: {e}")

# --- Metric & Health Check Functions ---
def get_system_metrics():
    """Collects and rounds CPU, RAM, and Disk metrics."""
    # interval=None makes this non-blocking. The first call will be 0.0 but will be accurate in the loop.
    cpu_percent = psutil.cpu_percent(interval=None) 
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        "cpu_percent": round(cpu_percent, 2),
        "ram_percent": round(ram.percent, 2),
        "ram_used_mb": round(ram.used / (1024 * 1024), 2),
        "disk_percent": round(disk.percent, 2)
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
    """Checks for internet connectivity and measures latency."""
    try:
        response = session.head(PING_URL, timeout=2)
        if response.status_code >= 200 and response.status_code < 400:
            return 1, int(response.elapsed.total_seconds() * 1000)
    except requests.exceptions.RequestException:
        pass
    return 0, None

def _check_one_service(name, url):
    """Helper function to check a single service, capturing latency."""
    try:
        # Use the global session object for IPv4 forcing and Keep-Alive
        response = session.head(url, timeout=SERVICE_TIMEOUT_SECONDS)
        if response.status_code >= 200 and response.status_code < 400:
            latency_ms = response.elapsed.total_seconds() * 1000
            return name, {"status": "healthy", "latency_ms": int(latency_ms)}
    except requests.exceptions.RequestException as e:
        # Detailed logging for diagnostics when a service check fails
        print(f"Health check for '{name}' ({url}) FAILED. Error: {e}")
    return name, {"status": "unhealthy", "latency_ms": None}

def check_services_health(executor):
    """Checks the health of configured services in parallel."""
    if not SERVICES_TO_CHECK:
        return {"services": {}}
        
    futures = {executor.submit(_check_one_service, name, url): name for name, url in SERVICES_TO_CHECK.items()}
    services_status = {}
    for future in as_completed(futures):
        name, status = future.result()
        services_status[name] = status
        
    return {"services": services_status}

# --- Heartbeat & Alerting ---
def send_heartbeat(services_payload):
    """Sends a heartbeat with services status to the Cloudflare worker."""
    if not SECRET_KEY or not HEARTBEAT_URL:
        if not hasattr(send_heartbeat, "warned"):
            print("Warning: Missing SECRET_KEY or HEARTBEAT_URL.")
            send_heartbeat.warned = True
        return None
    
    headers = {"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"}
    try:
        # Use the global session object
        response = session.post(HEARTBEAT_URL, headers=headers, json=services_payload, timeout=6)
        return response.status_code
    except requests.exceptions.RequestException as e:
        print(f"Heartbeat request failed: {e}")
        return None

def send_n8n_alert(previous_status, new_status, internet_ok):
    """Sends a formatted, customized alert to the n8n webhook for a confirmed state change."""
    if not N8N_WEBHOOK_URL:
        print("Warning: N8N_WEBHOOK_URL is not set. Could not send alert.")
        return

    # Handle NULL status with more context first
    if new_status is None:
        if not internet_ok:
            title = "🔥 Error Crítico (Sin Internet): Heartbeat-Monitor"
            message = f"No se pudo contactar la API del worker porque no hay conexión a internet en el servidor.\n\n- **Estado Anterior:** `{previous_status or 'N/A'}`"
        else:
            title = "🔥 Error Crítico (API Inaccesible): Heartbeat-Monitor"
            message = f"No se pudo contactar la API del worker, a pesar de tener conexión a internet. La API del worker podría estar caída.\n\n- **Estado Anterior:** `{previous_status or 'N/A'}`"
        
        alert_payload = {"title": title, "message": message}
    else:
        # Define titles and messages for numeric statuses
        status_map = {
            200: {
                "title": "✅ Recuperación: Heartbeat-Monitor",
                "message": f"El servicio se ha recuperado y funciona correctamente.\n\n- **Estado Anterior:** `{previous_status or 'N/A'}`\n- **Nuevo Estado:** `{new_status}` (Éxito)"
            },
            220: {
                "title": "⚠️ Advertencia (Ciego): Heartbeat-Monitor",
                "message": f"El latido fue recibido, pero la API no pudo leer su estado anterior. No se pueden detectar recuperaciones.\n\n- **Estado Anterior:** `{previous_status or 'N/A'}`\n- **Nuevo Estado:** `{new_status}` (Advertencia)"
            },
            221: {
                "title": "⚠️ Advertencia (Fallo en Actualización): Heartbeat-Monitor",
                "message": f"Se detectó una recuperación, pero la API falló al actualizar su estado o enviar la notificación de recuperación.\n\n- **Estado Anterior:** `{previous_status or 'N/A'}`\n- **Nuevo Estado:** `{new_status}` (Advertencia)"
            },
            500: {
                "title": "🔥 Error Crítico (Worker): Heartbeat-Monitor",
                "message": f"La API del worker encontró un error interno crítico y no pudo procesar el latido.\n\n- **Estado Anterior:** `{previous_status or 'N/A'}`\n- **Nuevo Estado:** `{new_status}` (Error de Worker)"
            }
        }
        
        # Default message for any other status code
        default_info = {
            "title": f"ℹ️ Cambio de Estado: Heartbeat-Monitor",
            "message": f"El estado del worker ha cambiado de forma estable.\n\n- **Nuevo Estado:** `{new_status or 'N/A'}`\n- **Estado Anterior:** `{previous_status or 'N/A'}`"
        }

        alert_info = status_map.get(new_status, default_info)
        alert_payload = {"title": alert_info["title"], "message": alert_info["message"]}

    try:
        # Use the global session object
        session.post(N8N_WEBHOOK_URL, json=alert_payload, timeout=2)
        print(f"STATE CHANGE ALERT sent to n8n: {previous_status or 'N/A'} -> {new_status or 'N/A'}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send state change alert to n8n: {e}")

# --- Main Execution ---
def main():
    """Main monitoring loop with parallel data collection."""
    global last_stable_status, transient_status, transient_counter
    
    initialize_database()
    
    if not SERVICES_TO_CHECK:
        print("CRITICAL: No services configured. Please set SERVICE_NAMES and SERVICE_URL_* environment variables.")
        return

    last_stable_status = get_initial_stable_status()
    transient_status = last_stable_status
    transient_counter = 0
    
    # Initialize psutil.cpu_percent() before the loop to get a meaningful first reading
    psutil.cpu_percent(interval=None)
    
    print(f"Starting monitoring loop. Initial stable state: {last_stable_status}. Monitoring services: {list(SERVICES_TO_CHECK.keys())}")
    
    while True:
        try:
            # 1. Clock-Aligned Execution
            current_time = time.time()
            wait_seconds = LOOP_INTERVAL_SECONDS - (current_time % LOOP_INTERVAL_SECONDS)
            time.sleep(wait_seconds)
            
            cycle_start_time = time.monotonic()
            timestamp_lima = datetime.datetime.now(LIMA_TZ).isoformat()

            # 2. Sequential CPU-bound task: Collect system metrics
            # psutil.cpu_percent(interval=1) is blocking for 1 second. 
            # Executing it sequentially prevents it from starving the ThreadPoolExecutor.
            sys_metrics = get_system_metrics()
            
            # 3. Submit all I/O-bound tasks to run in parallel
            # max_workers=4 because one conceptual worker is 'used' by the sequential CPU task.
            # This ensures network tasks can proceed without being blocked by psutil.
            with ThreadPoolExecutor(max_workers=4) as executor: 
                future_services = executor.submit(check_services_health, executor)
                future_internet = executor.submit(check_internet_and_ping)
                future_containers = executor.submit(get_container_count)

                # 4. Collect results from parallel tasks
                services_health_full = future_services.result()
                internet_ok, ping_ms = future_internet.result()
                container_count = future_containers.result()
            
            # 5. Conditional Sequential Step: Send Heartbeat
            worker_status = None
            if internet_ok:
                # Create a clean payload for the worker, containing only the status
                services_payload_clean = {
                    "services": {
                        name: {"status": data["status"]} 
                        for name, data in services_health_full.get("services", {}).items()
                    }
                }
                worker_status = send_heartbeat(services_payload_clean)
            
            # 6. Handle State Machine Logic for n8n alerts
            if worker_status == transient_status:
                transient_counter += 1
            else:
                # The status has changed from the last cycle, reset counter and update transient status
                transient_status = worker_status
                transient_counter = 1

            if transient_counter >= STATE_CHANGE_THRESHOLD:
                if transient_status != last_stable_status:
                    send_n8n_alert(last_stable_status, transient_status)
                    last_stable_status = transient_status
            
            # 7. Save Core Metrics
            cycle_duration_ms = int((time.monotonic() - cycle_start_time) * 1000)
            
            # Format services data for DB and log
            services_health_db_log_str = json.dumps(services_health_full.get("services", {}))

            all_metrics = {
                "timestamp_lima": timestamp_lima, **sys_metrics, "container_count": container_count,
                "internet_ok": internet_ok, "ping_ms": ping_ms, "worker_status": worker_status, 
                "cycle_duration_ms": cycle_duration_ms,
                "services_health": services_health_db_log_str
            }
            save_metrics_to_db(all_metrics)

            # 8. Log cycle completion
            services_for_log = services_health_full.get("services", {})
            services_log_str = ", ".join([f'\"{name}\": {json.dumps(data)}' for name, data in services_for_log.items()])
            
            log_msg = (
                f"{timestamp_lima} - Metrics saved.\n"
                f"  Services: {services_log_str}\n"
                f"  Worker Status: Current: {worker_status or 'N/A'}. Transient: {transient_status or 'N/A'} ({transient_counter}/{STATE_CHANGE_THRESHOLD}). Stable: {last_stable_status or 'N/A'}."
            )
            print(log_msg)

        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(LOOP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()