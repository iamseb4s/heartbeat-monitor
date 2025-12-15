import os
import requests
import socket
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

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

# --- Environment Variables (for smart_request) ---
# These will be loaded from config.py in the main app
INTERNAL_DNS_OVERRIDE_IP = os.getenv('INTERNAL_DNS_OVERRIDE_IP')
# SERVICES_TO_CHECK will be passed to smart_request or accessed via config

def smart_request(method, url, services_to_check, **kwargs):
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
    if INTERNAL_DNS_OVERRIDE_IP and services_to_check: # Use passed services_to_check
         # Find the original URL for the hostname from services_to_check
         # This is needed to ensure the override only happens for configured services
         for svc_data in services_to_check.values():
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
