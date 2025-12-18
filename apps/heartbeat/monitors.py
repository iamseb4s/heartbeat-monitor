import os
import psutil
import docker
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from network import smart_request # Import smart_request from network.py

# --- Constants & Environment Variables (placeholders for now, will come from config) ---
PING_URL = "http://www.google.com"
SERVICE_TIMEOUT_SECONDS = 2 

# Docker client setup
try:
    docker_client = docker.from_env(timeout=2)
except Exception as e:
    print(f"WARNING: Could not connect to Docker socket: {e}. Docker container checks will fail.")
    docker_client = None

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
        # Use the global session from network.py
        response = smart_request('HEAD', PING_URL, {}, timeout=SERVICE_TIMEOUT_SECONDS) # Empty services_to_check as it's not a configured service
        if response and 200 <= response.status_code < 400:
            return 1, int(response.elapsed.total_seconds() * 1000)
    except requests.exceptions.RequestException:
        pass
    return 0, None

def _check_one_service(name, service_config, services_to_check_global):
    """
    Helper function to check a single service, capturing latency.
    Handles both HTTP/HTTPS and 'docker:' protocol checks.
    """
    url = service_config['url']
    headers = service_config.get('headers', {}) # Get custom headers for the service
    
    # Default structure for the result
    result = {
        "url": url,
        "status": "unhealthy",
        "status_code": None,
        "latency_ms": None,
        "error": None
    }
    
    if url.startswith("docker:"):
        if not docker_client:
            result["error"] = "Docker client unavailable"
            return name, result
        
        container_name = url.split(":", 1)[1].strip()
        start_time = time.monotonic()
        try:
            container = docker_client.containers.get(container_name)
            if container.status == 'running':
                latency_ms = int((time.monotonic() - start_time) * 1000)
                result.update({
                    "status": "healthy",
                    "latency_ms": latency_ms,
                    "error": None
                })
                return name, result
            else:
                result["error"] = f"Container state: {container.status}"
                return name, result
        except docker.errors.NotFound:
            result["error"] = "Container not found"
            return name, result
        except Exception as e:
            result["error"] = str(e)
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
                return name, result
            else:
                status_desc = response.status_code if response is not None else "No Response"
                result["error"] = f"HTTP {status_desc}"
                return name, result
        except requests.exceptions.Timeout:
             result["error"] = "Timeout"
             return name, result
        except requests.exceptions.ConnectionError:
             result["error"] = "Connection Error"
             return name, result
        except requests.exceptions.RequestException as e:
            result["error"] = str(e)
            return name, result
        except Exception as e:
            result["error"] = str(e)
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
