import os
import pytz

# --- Operational Configuration ---
# Configurable via environment variables with sensible defaults.

LIMA_TZ = pytz.timezone(os.getenv('TZ', 'America/Lima'))
PING_URL = os.getenv('PING_URL', "http://www.google.com")

# Main execution loop interval in seconds
LOOP_INTERVAL_SECONDS = int(os.getenv('LOOP_INTERVAL_SECONDS', 10))

# Threshold for consecutive status checks to confirm a state change (Debounce)
STATUS_CHANGE_THRESHOLD = int(os.getenv('STATUS_CHANGE_THRESHOLD', 4))

# Timeout for individual service health checks
SERVICE_TIMEOUT_SECONDS = int(os.getenv('SERVICE_TIMEOUT_SECONDS', 2))

# --- Environment Variables ---
SECRET_KEY = os.getenv('SECRET_KEY')
HEARTBEAT_URL = os.getenv('HEARTBEAT_URL')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
INTERNAL_DNS_OVERRIDE_IP = os.getenv('INTERNAL_DNS_OVERRIDE_IP')
SQLITE_DB_PATH = os.getenv('SQLITE_DB_PATH', 'data/metrics.db')

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