import os
import datetime
import json
import pytz
import requests
from network import smart_request # Import smart_request from network.py

# --- Constants & Environment Variables (placeholders for now, will come from config) ---
SECRET_KEY = os.getenv('SECRET_KEY')
HEARTBEAT_URL = os.getenv('HEARTBEAT_URL')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
LIMA_TZ = pytz.timezone('America/Lima')
STATUS_CHANGE_THRESHOLD = 4 
LOOP_INTERVAL_SECONDS = 10 # Needed for log duration calculation

# --- Unified State Management ---
global_states = {}

def send_heartbeat(services_payload):
    """Sends a heartbeat with services status to the Cloudflare worker."""
    if not SECRET_KEY or not HEARTBEAT_URL:
        if not hasattr(send_heartbeat, "warned"):
            print("Warning: Missing SECRET_KEY or HEARTBEAT_URL.")
            send_heartbeat.warned = True
        return None
    
    headers = {"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"}
    try:
        # services_to_check is not relevant for the heartbeat URL itself, pass empty dict
        response = smart_request('POST', HEARTBEAT_URL, {}, headers=headers, json=services_payload, timeout=6)
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
            # services_to_check is not relevant for the webhook URL itself, pass empty dict
            smart_request('POST', N8N_WEBHOOK_URL, {}, json={"title": title, "message": message}, timeout=5)
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
