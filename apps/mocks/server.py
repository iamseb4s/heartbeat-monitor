import http.server
import socketserver
import json
import sys
import os
import threading
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# --- Config ---
PORT = int(os.getenv('PORT', 8080))
SECRET_KEY = os.getenv('SECRET_KEY', 'dev_secret')
TEMPLATE_DIR = os.getenv('TEMPLATE_DIR', 'templates')
LOG_FILE_PATH = os.getenv('LOG_FILE_PATH', '/tmp/mock_server_access.log') # Persistent log file

# --- Simulation Configuration ---
# Controls how the mock server behaves
sim_config = {
    "is_online": True,          # If False, returns 503 (Service Unavailable)
    "mode": "AUTO",             # AUTO, RECORDED, RECOVERED, BLIND, PARTIAL, CRITICAL
    "host_status": "online"     # Internal DB state: 'online' or 'offline' (for AUTO mode)
}
config_lock = threading.Lock() # Protects sim_config
logs_lock = threading.Lock()   # Protects log file writes

# --- Custom Request Handler ---
class MockHeartbeatHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.log_buffer = [] # Store recent logs for /api/logs endpoint
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        if hasattr(self, 'path') and (self.path.startswith('/api/logs') or self.path.startswith('/api/config')):
             return

        message = "%s - - [%s] %s\n" % \
                  (self.client_address[0], self.log_date_time_string(), format % args)
        
        # Write to log file
        with logs_lock:
            with open(LOG_FILE_PATH, 'a') as f:
                f.write(message)

        sys.stdout.write(message) # Also write to stdout for docker logs

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == '/':
            self.serve_html_dashboard()
        elif path == '/api/config':
            self.send_json_response(200, sim_config)
        elif path == '/api/logs':
            self.serve_logs(parsed_path.query)
        elif path == '/api/status': # For legacy /api/status endpoint
             self.send_json_response(200, sim_config)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == '/api/config':
            self.handle_config_update()
        elif path == '/api/heartbeat':
            self.handle_heartbeat()
        else:
            self.send_error(404)

    def serve_html_dashboard(self):
        try:
            with open(os.path.join(TEMPLATE_DIR, 'index.html'), 'rb') as f:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_error(404, f"Dashboard template not found: {os.path.join(TEMPLATE_DIR, 'index.html')}")

    def serve_logs(self, query_string):
        query_params = parse_qs(query_string)
        offset = int(query_params.get('offset', ['0'])[0])
        
        try:
            with logs_lock:
                with open(LOG_FILE_PATH, 'r') as f:
                    f.seek(offset)
                    logs_content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(logs_content.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(404, "Log file not found.")
        except Exception as e:
            self.send_error(500, f"Error reading logs: {e}")


    def handle_config_update(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            new_config = json.loads(post_data)
            with config_lock:
                sim_config.update(new_config)
            
            self.log_message("[MOCK] ⚙️ CONFIG UPDATED: %s", sim_config)
            
            self.send_json_response(200, {"status": "ok", "config": sim_config})
        except Exception as e:
            self.send_error(400, str(e))

    def handle_heartbeat(self):
        # Read current simulation config
        with config_lock:
            current_config = sim_config.copy() # Make a copy to avoid holding lock during I/O

        # 1. Check Availability Switch
        if not current_config['is_online']:
            self.log_message("❌ [MOCK] Simulation: Service Unavailable (503)")
            self.send_error(503, "Service Unavailable (Simulated)")
            return
        
        # 2. Auth Check
        auth_header = self.headers.get('Authorization')
        expected_auth = f"Bearer {SECRET_KEY}"
        if auth_header != expected_auth:
            self.log_message("❌ [MOCK] Auth Failed. Got: %s", auth_header)
            self.send_error(401, "Unauthorized")
            return

        # 3. Handle specific simulation modes
        mode = current_config['mode']
        if mode == 'CRITICAL':
            self.log_message("🔥 [MOCK] Simulation: Forced 500 CRITICAL")
            self.send_json_response(500, {"error": "CRITICAL: Failed to write timestamps to D1.", "logType": "HEARTBEAT_FAILURE"})
            return
        elif mode == 'BLIND':
            self.log_message("⚠️ [MOCK] Simulation: Forced 220 BLIND")
            self.send_json_response(220, {"error": "OK, but blind. Failed to read DB status.", "logType": "HEARTBEAT_WARNING"})
            return
        elif mode == 'PARTIAL':
            self.log_message("⚠️ [MOCK] Simulation: Forced 221 PARTIAL")
            self.send_json_response(221, {"error": "OK, but update failed.", "logType": "HEARTBEAT_PARTIAL_ERROR"})
            return
        elif mode == 'RECORDED':
            self.log_message("✅ [MOCK] Simulation: Forced 200 RECORDED")
            self.send_json_response(200, {"status": "recorded", "format": "with_payload", "mock": True})
            return
        elif mode == 'RECOVERED':
            self.log_message("🎉 [MOCK] Simulation: Forced 200 RECOVERED")
            self.send_json_response(200, {"status": "recovered", "steps": ["Forced Recovery"], "mock": True})
            return

        # 4. AUTO Mode (Simulate Worker Logic based on internal state)
        self.log_message("🤖 [MOCK] Auto Mode: Processing heartbeat...")
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            payload = json.loads(post_data)
        except json.JSONDecodeError:
            payload = {} # No payload or invalid JSON

        has_payload = 'services' in payload

        response_status = "recorded"
        with config_lock: # Need to lock to modify sim_config['host_status']
            if sim_config['host_status'] == 'offline':
                sim_config['host_status'] = 'online' # Recover!
                response_status = "recovered"
                self.log_message("🚀 [MOCK] AUTO MODE: Host recovery triggered!")
                # Simulate Telegram notification if needed
                # print("\n[MOCK] 🚀 TELEGRAM: Servidor Recuperado\n")
            else:
                self.log_message("✅ [MOCK] AUTO MODE: Host already online.")

        self.send_json_response(200, {
            "status": response_status,
            "format": "with_payload" if has_payload else "without_payload",
            "steps": [f"AUTO Mode ({response_status})"],
            "mock": True
        })

    def send_json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

print(f"[MOCK] Starting Heartbeat Mock Server on port {PORT}...")
print(f"[MOCK] Secret Key: {'[LOADED]' if SECRET_KEY else '[MISSING]'}")
print(f"[MOCK] Dashboard available at http://localhost:{PORT}/ (if port is mapped)")
with socketserver.TCPServer(('', PORT), MockHeartbeatHandler) as httpd:
    httpd.serve_forever()