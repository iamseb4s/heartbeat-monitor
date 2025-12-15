import os
import pytz

# --- Constants ---
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