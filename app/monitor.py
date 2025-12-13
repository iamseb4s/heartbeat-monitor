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
from urllib.parse import urlparse
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
session = requests.Session()
session.mount('https://', IPv4Adapter())
session.mount('http://', IPv4Adapter())


# --- Constants ---
DB_FILE = Path("/app/data/metrics.db")
LOOP_INTERVAL_SECONDS = 10
LIMA_TZ = pytz.timezone('America/Lima')
PING_URL = "http://www.google.com"
STATUS_CHANGE_THRESHOLD = 4 # Number of consecutive identical statuses to consider a state "stable"
SERVICE_TIMEOUT_SECONDS = 2 # Global timeout for service health checks (in seconds)

# --- Environment Variables & Dynamic Config ---
SECRET_KEY = os.getenv('SECRET_KEY')
HEARTBEAT_URL = os.getenv('HEARTBEAT_URL')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
INTERNAL_DNS_OVERRIDE_IP = os.getenv('INTERNAL_DNS_OVERRIDE_IP')

def parse_services_from_env():
    """
    Parses service configuration from environment variables,
    including URLs and optional custom headers.
    Returns a dict like: {'name': {'url': '...', 'headers': {}}}.
    """
    services_config = {}
    service_names_str = os.getenv('SERVICE_NAMES', '')
    if not service_names_str:
        print("Warning: SERVICE_NAMES environment variable not set. No services will be monitored.")
        return services_config
        
    service_names = [name.strip() for name in service_names_str.split(',')]
    
    for name in service_names:
        url = os.getenv(f'SERVICE_URL_{name}')
        if not url:
            print(f"Warning: Missing URL for service '{name}'. Environment variable SERVICE_URL_{name} not found.")
            continue
        
        custom_headers = {}
        headers_str = os.getenv(f'SERVICE_HEADERS_{name}')
        if headers_str:
            try:
                # Expecting format "Key1:Value1,Key2:Value2"
                for header_pair in headers_str.split(','):
                    key, value = header_pair.split(':', 1)
                    custom_headers[key.strip()] = value.strip()
            except ValueError:
                print(f"Warning: Invalid format for SERVICE_HEADERS_{name}. Expected 'Key:Value,Key:Value'. Skipping custom headers for {name}.")

        services_config[name] = {'url': url, 'headers': custom_headers}
            
    return services_config

SERVICES_TO_CHECK = parse_services_from_env()

# --- Unified State Management ---
global_states = {}

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

# --- Helper Functions ---
def smart_request(method, url, **kwargs):
    """
    Executes an HTTP request via the global session. 
    If INTERNAL_DNS_OVERRIDE_IP is set and the host matches a monitored service,
    it forces a direct IP connection (HTTP) with Host header injection.
    """
    if not url:
        return None

    clean_url = url.strip().strip('"').strip("'")
    parsed = urlparse(clean_url)
    hostname = parsed.hostname or ""
    
    target_url = clean_url
    headers = kwargs.pop('headers', {}) or {} # Pop headers from kwargs if passed

    # Check if we should override: IP is set AND host matches a monitored service
    should_override = False
    if INTERNAL_DNS_OVERRIDE_IP and SERVICES_TO_CHECK:
         # Find the original URL for the hostname from SERVICES_TO_CHECK
         # This is needed to ensure the override only happens for configured services
         for svc_data in SERVICES_TO_CHECK.values():
             parsed_svc_url = urlparse(svc_data['url'])
             # Only attempt hostname comparison for http/https schemes and if a hostname exists
             if parsed_svc_url.scheme in ['http', 'https'] and hostname and parsed_svc_url.hostname and hostname in parsed_svc_url.hostname:
                 should_override = True
                 break

    if should_override:
        # Rewrite URL: use IP directly and force HTTP
        target_url = clean_url.replace(hostname, INTERNAL_DNS_OVERRIDE_IP, 1).replace("https://", "http://")
        
        # Set original Host header
        headers['Host'] = hostname
        
        # Direct IP connection settings
        kwargs['verify'] = False
        kwargs['allow_redirects'] = False
    
    return session.request(method, target_url, headers=headers, **kwargs)

# --- Metric & Health Check Functions ---
def get_system_metrics():
    """Collects and rounds CPU, RAM, and Disk metrics."""
    cpu_percent = psutil.cpu_percent(interval=None) 
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        "cpu_percent": round(cpu_percent, 2),
        "ram_percent": round(ram.percent, 2),
        "ram_used_mb": round(ram.used / (1024 * 1024), 2),
        "disk_percent": round(disk.percent, 2)
    }

# Docker client setup
try:
    docker_client = docker.from_env(timeout=2)
except Exception as e:
    print(f"WARNING: Could not connect to Docker socket: {e}. Docker container checks will fail.")
    docker_client = None


def get_container_count():
    """Counts running Docker containers."""
    if not docker_client:
        return -1
    try:
        return len(docker_client.containers.list())
    except Exception as e:
        print(f"Error counting Docker containers: {e}")
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

def _check_one_service(name, service_config):
    """
    Helper function to check a single service, capturing latency.
    Handles both HTTP/HTTPS and 'docker:' protocol checks.
    """
    url = service_config['url']
    headers = service_config.get('headers', {}) # Get custom headers for the service
    
    if url.startswith("docker:"):
        if not docker_client:
            print(f"Error: Docker client not available for service '{name}'.")
            return name, {"status": "unhealthy", "latency_ms": None, "error": "Docker client unavailable"}
        
        container_name = url.split(":", 1)[1].strip()
        start_time = time.monotonic()
        try:
            container = docker_client.containers.get(container_name)
            if container.status == 'running':
                latency_ms = int((time.monotonic() - start_time) * 1000)
                return name, {"status": "healthy", "latency_ms": latency_ms, "error": None}
            else:
                print(f"Health check for '{name}' (container:{container_name}) FAILED. Status: {container.status}")
                return name, {"status": "unhealthy", "latency_ms": None, "error": f"Container state: {container.status}"}
        except docker.errors.NotFound:
            print(f"Health check for '{name}' FAILED. Container '{container_name}' not found.")
            return name, {"status": "unhealthy", "latency_ms": None, "error": "Container not found"}
        except Exception as e:
            print(f"Error checking Docker container '{container_name}' for service '{name}': {e}")
            return name, {"status": "unhealthy", "latency_ms": None, "error": str(e)}
    else:
        try:
            # Pass custom headers to smart_request
            response = smart_request('HEAD', url, headers=headers, timeout=SERVICE_TIMEOUT_SECONDS)
            
            # Consider 2xx (OK) and 3xx (Redirects) as healthy
            if 200 <= response.status_code < 400:
                latency_ms = int(response.elapsed.total_seconds() * 1000)
                return name, {"status": "healthy", "latency_ms": latency_ms, "error": None}
            else:
                return name, {"status": "unhealthy", "latency_ms": None, "error": f"HTTP {response.status_code}"}
        except requests.exceptions.Timeout:
             return name, {"status": "unhealthy", "latency_ms": None, "error": "Timeout"}
        except requests.exceptions.ConnectionError:
             return name, {"status": "unhealthy", "latency_ms": None, "error": "Connection Error"}
        except requests.exceptions.RequestException as e:
            return name, {"status": "unhealthy", "latency_ms": None, "error": str(e)}
        except Exception as e:
            return name, {"status": "unhealthy", "latency_ms": None, "error": str(e)}

def check_services_health(executor):
    """Checks the health of configured services in parallel."""
    if not SERVICES_TO_CHECK:
        return {"services": {}}
        
    futures = {executor.submit(_check_one_service, name, config): name for name, config in SERVICES_TO_CHECK.items()}
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
        response = smart_request('POST', HEARTBEAT_URL, headers=headers, json=services_payload, timeout=6)
        return response.status_code
    except requests.exceptions.RequestException as e:
        print(f"Heartbeat request failed: {e}")
        return None

def send_notification(item_name, new_status, old_status, extra_info=None, internet_ok=True):
    """
    Sends a formatted, customized alert to the n8n webhook for any state change.
    Includes robust error handling and retries.
    """
    if not N8N_WEBHOOK_URL:
        # Warning already logged at startup
        return

    timestamp = datetime.datetime.now(LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    title = ""
    message = ""
    old_status_str = f"`{old_status or 'N/A'}`"
    new_status_str = f"`{new_status or 'N/A'}`"

    if item_name == 'worker':
        if new_status is None:
            cause = "sin conexión a internet" if not internet_ok else "API del worker inaccesible"
            title = f"📡 Sin Conexión con Worker | Heartbeat-Monitor"
            message = f"No se pudo contactar la API del worker.\n\n- **Causa probable**: {cause}.\n- **Último estado conocido**: {old_status_str}\n- **Hora**: {timestamp}"
        else:
            status_map = {
                200: {
                    "title": "✅ Worker Recuperado | Heartbeat-Monitor",
                    "message": f"La comunicación con el worker se ha restablecido.\n\n**Transición**: {old_status_str} -> {new_status_str}\n**Hora**: {timestamp}"
                },
                220: {
                    "title": "⚠️ Advertencia (Ciego) | Heartbeat-Monitor",
                    "message": f"El worker recibió el latido, pero no pudo leer su estado anterior.\n\n**Transición**: {old_status_str} -> {new_status_str}\n**Hora**: {timestamp}"
                },
                221: {
                    "title": "⚠️ Advertencia (Fallo en Actualización) | Heartbeat-Monitor",
                    "message": f"Se detectó recuperación, pero el worker falló al actualizar su estado.\n\n**Transición**: {old_status_str} -> {new_status_str}\n**Hora**: {timestamp}"
                },
                500: {
                    "title": "🔥 Error de Worker | Heartbeat-Monitor",
                    "message": f"La API del worker reporta un error interno.\n\n**Transición**: {old_status_str} -> {new_status_str}\n**Hora**: {timestamp}"
                }
            }
            default_info = {
                "title": f"ℹ️ Cambio de Estado | Heartbeat-Monitor",
                "message": f"El estado del worker ha cambiado de forma inesperada.\n\n**Transición**: {old_status_str} -> {new_status_str}\n**Hora**: {timestamp}"
            }
            alert_info = status_map.get(new_status, default_info)
            title = alert_info["title"]
            message = alert_info["message"]
    else:  # It's a service
        extra_detail = ""
        if new_status == 'healthy':
            latency_msg = f" ({extra_info}ms)" if extra_info is not None else ""
            title = f"✅ Servicio Recuperado: {item_name}"
            message = f"El servicio **{item_name}** vuelve a estar operativo{latency_msg}.\n\n**Transición**: `{old_status}` -> `{new_status}`\n**Hora**: {timestamp}"
        else:  # Unhealthy or other
            error_msg = f"\n**Error**: `{extra_info}`" if extra_info else ""
            title = f"❌ Servicio Caído: {item_name}"
            message = f"El servicio **{item_name}** ha dejado de responder.{error_msg}\n\n**Transición**: `{old_status}` -> `{new_status}`\n**Hora**: {timestamp}"

    # Retry logic
    for attempt in range(3):
        try:
            smart_request('POST', N8N_WEBHOOK_URL, json={"title": title, "message": message}, timeout=5)
            print(f"STATE CHANGE ALERT sent for '{item_name}': {old_status or 'N/A'} -> {new_status or 'N/A'}")
            break
        except requests.exceptions.RequestException as e:
            print(f"Failed to send state change alert for '{item_name}' (Attempt {attempt + 1}/3): {e}")
            time.sleep(2)


def check_state_change(item_name, current_status, immediate_notify_statuses, extra_info=None):
    """
    Generic state change processor. Returns an action, the old status, and relevant extra info if a notification is needed.
    Actions: 'NOTIFY_RECOVERY', 'NOTIFY_DOWN', or None
    """
    # Initialize state for new items
    if item_name not in global_states:
        global_states[item_name] = {
            'last_stable_status': current_status,
            'transient_status': current_status,
            'transient_counter': 1
        }
        return None, None, None

    state = global_states[item_name]
    old_stable_status = state['last_stable_status']

    # Update transient state
    if current_status == state['transient_status']:
        state['transient_counter'] += 1
    else:
        state['transient_status'] = current_status
        state['transient_counter'] = 1

    # Check for state changes that require notification
    action = None
    if state['transient_status'] != old_stable_status:
        # Recovery condition
        if state['transient_status'] in immediate_notify_statuses:
            action = 'NOTIFY_RECOVERY'
        # "Down" condition
        elif state['transient_counter'] >= STATUS_CHANGE_THRESHOLD:
            action = 'NOTIFY_DOWN'
        
        if action:
            state['last_stable_status'] = state['transient_status']
            return action, old_stable_status, extra_info
            
    return None, None, None

# --- Main Execution ---
def main():
    """Main monitoring loop with parallel data collection."""
    initialize_database()
    
    if not N8N_WEBHOOK_URL:
        print("WARNING: N8N_WEBHOOK_URL is not set. Alerts will NOT be sent.")

    if not SERVICES_TO_CHECK:
        print("CRITICAL: No services configured. Please set SERVICE_NAMES and SERVICE_URL_* environment variables.")
        return

    # Initialize psutil.cpu_percent() before the loop to get a meaningful first reading
    psutil.cpu_percent(interval=None)
    
    print(f"Starting monitoring loop. Monitoring services: {list(SERVICES_TO_CHECK.keys())}")
    
    while True:
        try:
            # --- Align with Main Loop Grid ---
            current_time = time.time()
            wait_seconds = LOOP_INTERVAL_SECONDS - (current_time % LOOP_INTERVAL_SECONDS)
            time.sleep(wait_seconds)
            
            cycle_start_time = time.monotonic()
            timestamp_lima = datetime.datetime.now(LIMA_TZ).isoformat()

            # --- Collect System-Level Metrics ---
            sys_metrics = get_system_metrics()
            
            # --- Run I/O-Bound Checks in Parallel ---
            with ThreadPoolExecutor(max_workers=4) as executor: 
                future_services = {executor.submit(_check_one_service, name, config): name for name, config in SERVICES_TO_CHECK.items()}
                future_internet = executor.submit(check_internet_and_ping)
                future_containers = executor.submit(get_container_count)

                services_health_full = {"services": {}}
                for future in as_completed(future_services):
                    name, status = future.result()
                    services_health_full["services"][name] = status

                internet_ok, ping_ms = future_internet.result()
                container_count = future_containers.result()
            
            # --- Send Heartbeat to Worker ---
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

            # --- Unified State Processing ---
            # Process Worker Status
            action, old_status, _ = check_state_change('worker', worker_status, [200])
            if action:
                send_notification('worker', worker_status, old_status, internet_ok=internet_ok)
            
            # Process Individual Service Statuses
            for name, health_data in services_health_full.get("services", {}).items():
                service_status = health_data['status']
                # Extract extra info based on status: latency for healthy, error for unhealthy
                extra_info = health_data.get('latency_ms') if service_status == 'healthy' else health_data.get('error')
                
                action, old_status, info_to_send = check_state_change(name, service_status, ['healthy'], extra_info)
                if action:
                    send_notification(name, service_status, old_status, extra_info=info_to_send)

            # --- Save & Log ---
            cycle_duration_ms = int((time.monotonic() - cycle_start_time) * 1000)
            services_health_db_log_str = json.dumps(services_health_full.get("services", {}))
            all_metrics = {
                "timestamp_lima": timestamp_lima, **sys_metrics, "container_count": container_count,
                "internet_ok": internet_ok, "ping_ms": ping_ms, "worker_status": worker_status, 
                "cycle_duration_ms": cycle_duration_ms,
                "services_health": services_health_db_log_str
            }
            save_metrics_to_db(all_metrics)

            # --- Log Cycle Summary ---
            services_log_str = ", ".join([f'"{name}": {json.dumps({k: v for k, v in data.items() if v is not None and not (k=="error" and data.get("status")=="healthy")})}' for name, data in services_health_full.get("services", {}).items()])
            worker_log = global_states.get('worker', {})
            log_msg = (
                f"{timestamp_lima} - Metrics saved.\n"
                f"  Services: {services_log_str}\n"
                f"  Worker Status: Current: {worker_status or 'N/A'}. Stable: {worker_log.get('last_stable_status', 'N/A')}. "
                f"Transient: {worker_log.get('transient_status', 'N/A')} ({worker_log.get('transient_counter', 0)}/{STATUS_CHANGE_THRESHOLD})."
            )
            print(log_msg)

        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(LOOP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()