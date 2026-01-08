import os
import psutil
import docker
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from network import smart_request # Import smart_request from network.py

# --- Constants & Environment Variables (placeholders for now, will come from config) ---
PING_URL = "http://www.google.com"
SERVICE_TIMEOUT_SECONDS = int(os.getenv('SERVICE_TIMEOUT_SECONDS', 2))

# Docker client setup
_client_cache = None

def get_docker_client():
    """
    Retrieves a cached Docker client or attempts to create a new one.
    Resilient to socket availability issues during startup or runtime.
    Logs errors on every failure to ensure visibility.
    """
    global _client_cache
    
    # 1. Try to use existing client
    if _client_cache:
        try:
            # Simple ping to verify connection is still alive
            _client_cache.ping()
            return _client_cache
        except Exception as e:
            print(f"ERROR: Docker client connection lost: {e}")
            # If ping fails, invalidate cache and try to recreate
            _client_cache = None

    # 2. Try to create new client
    try:
        client = docker.from_env(timeout=2)
        client.ping() # Verify immediate connectivity
        _client_cache = client
        print("INFO: Docker connection established/restored.")
        return _client_cache
    except Exception as e:
        # Docker socket not ready yet or unavailable - Log on every cycle
        print(f"ERROR: Cannot connect to Docker socket: {e}")
        return None

def get_system_metrics():
    """Collects and rounds CPU, RAM, Disk metrics, and calculates Uptime."""
    cpu_percent = psutil.cpu_percent(interval=None) 
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Calculate uptime in seconds
    uptime_seconds = time.time() - psutil.boot_time()

    return {
        "cpu_percent": round(cpu_percent, 2),
        "ram_percent": round(ram.percent, 2),
        "ram_used_mb": round(ram.used / (1024 * 1024), 2),
        "disk_percent": round(disk.percent, 2),
        "uptime_seconds": int(uptime_seconds)
    }

def get_container_count():
    """Counts running Docker containers."""
    client = get_docker_client()
    if not client:
        return -1
    try:
        return len(client.containers.list())
    except Exception as e:
        print(f"Error counting Docker containers: {e}")
        return -1

def check_internet_and_ping():
    """Checks for internet connectivity and measures latency."""
    try:
        # Use the global session from network.py
        response = smart_request('HEAD', PING_URL, {}, timeout=SERVICE_TIMEOUT_SECONDS) # Empty services_to_check as it's not a configured service
        if response and 200 <= response.status_code < 400:
            return 1, int(response.elapsed.total_seconds() * 1000)
    except requests.exceptions.RequestException:
        pass
    return 0, None

def _check_one_service(name, service_config, services_to_check_global):
    """
    Helper function to check a single service with rich status classification.
    """
    url = service_config['url']
    headers = service_config.get('headers', {})
    
    result = {
        "url": url,
        "status": "unknown",     # Default to unknown if unhandled logic occurs
        "status_code": None,
        "latency_ms": None,
        "error": None
    }
    
    if url.startswith("docker:"):
        client = get_docker_client()
        if not client:
            result.update({"status": "unknown", "error": "Docker client unavailable"})
            return name, result
        
        container_name = url.split(":", 1)[1].strip()
        start_time = time.monotonic()
        try:
            container = client.containers.get(container_name)
            if container.status == 'running':
                latency_ms = int((time.monotonic() - start_time) * 1000)
                result.update({
                    "status": "healthy",
                    "latency_ms": latency_ms,
                    "error": None
                })
            else:
                # Container exists but is not running (exited, paused, dead)
                result.update({"status": "down", "error": f"Container state: {container.status}"})
        except docker.errors.NotFound:
            result.update({"status": "down", "error": "Container not found"})
        except Exception as e:
            result.update({"status": "unknown", "error": str(e)})
        return name, result
    else:
        try:
            # Pass custom headers to smart_request
            response = smart_request('HEAD', url, services_to_check_global, headers=headers, timeout=SERVICE_TIMEOUT_SECONDS)
            
            if response:
                result["status_code"] = response.status_code

            # Consider 2xx (OK) and 3xx (Redirects) as healthy
            if response and 200 <= response.status_code < 400:
                latency_ms = int(response.elapsed.total_seconds() * 1000)
                result.update({
                    "status": "healthy",
                    "latency_ms": latency_ms,
                    "error": None
                })
            else:
                # HTTP 4xx/5xx errors -> Classified as 'error' (Service is up but failing)
                status_desc = response.status_code if response is not None else "No Response"
                result.update({"status": "error", "error": f"HTTP {status_desc}"})
                
        except requests.exceptions.Timeout:
             result.update({"status": "timeout", "error": "Timeout"})
        except requests.exceptions.ConnectionError:
             result.update({"status": "down", "error": "Connection Error"})
        except requests.exceptions.RequestException as e:
            # Generic Request Exception (DNS, etc)
            result.update({"status": "down", "error": str(e)})
        except Exception as e:
            # Unhandled exceptions
            result.update({"status": "unknown", "error": str(e)})
            
        return name, result

def check_services_health(executor, services_to_check_config):
    """Checks the health of configured services in parallel."""
    if not services_to_check_config:
        return {"services": {}}
        
    futures = {executor.submit(_check_one_service, name, config, services_to_check_config): name for name, config in services_to_check_config.items()}
    services_status = {}
    for future in as_completed(futures):
        name, status = future.result()
        services_status[name] = status
        
    return {"services": services_status}