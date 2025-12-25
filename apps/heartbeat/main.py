import datetime
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# Module imports
import database
import monitors
import alerts
import config

# Initialize psutil for accurate first readings
import psutil
psutil.cpu_percent(interval=None)

# Global variables
global_states = alerts.global_states

def main(run_once=False):
    """Main monitoring loop with parallel data collection."""
    database.initialize_database()
    
    if not config.N8N_WEBHOOK_URL:
        print("WARNING: N8N_WEBHOOK_URL is not set. Alerts will NOT be sent.")

    if not config.SERVICES_TO_CHECK:
        print("CRITICAL: No services configured. Please set SERVICE_NAMES and SERVICE_URL_* environment variables.")
        return
    
    print(f"Starting monitoring loop. Monitoring services: {list(config.SERVICES_TO_CHECK.keys())}")
    print(f"Config: Interval={config.LOOP_INTERVAL_SECONDS}s, Threshold={config.STATUS_CHANGE_THRESHOLD} cycles per state change.")
    
    while True:
        try:
            # --- Align with Main Loop Grid ---
            current_time = time.time()
            wait_seconds = config.LOOP_INTERVAL_SECONDS - (current_time % config.LOOP_INTERVAL_SECONDS)
            time.sleep(wait_seconds)
            
            cycle_start_time = time.monotonic()
            now_lima = datetime.datetime.now(config.LIMA_TZ)
            timestamp_lima = now_lima.isoformat()
            timestamp_pretty = now_lima.strftime('%Y-%m-%d %H:%M:%S')

            # --- Collect System-Level Metrics ---
            sys_metrics = monitors.get_system_metrics()
            
            # --- Run I/O-Bound Checks in Parallel ---
            with ThreadPoolExecutor(max_workers=4) as executor: 
                future_services = {executor.submit(monitors._check_one_service, name, svc_config, config.SERVICES_TO_CHECK): name for name, svc_config in config.SERVICES_TO_CHECK.items()}
                future_internet = executor.submit(monitors.check_internet_and_ping)
                future_containers = executor.submit(monitors.get_container_count)

                services_health_full = {"services": {}}
                for future in as_completed(future_services):
                    name, status = future.result()
                    services_health_full["services"][name] = status

                internet_ok, ping_ms = future_internet.result()
                container_count = future_containers.result()
            
            # --- Send Heartbeat to Worker ---
            worker_status = None
            if internet_ok:
                # Create a clean payload for the worker with raw statuses
                services_payload_clean = {
                    "services": {
                        name: {"status": data["status"]} 
                        for name, data in services_health_full.get("services", {}).items()
                    }
                }
                worker_status = alerts.send_heartbeat(services_payload_clean)

            # --- Unified State Processing ---
            # Process Worker Status
            action, old_status, _ = alerts.check_state_change('worker', worker_status, [200])
            if action:
                alerts.send_notification('worker', worker_status, old_status, internet_ok=internet_ok)
            
            # Process Individual Service Statuses
            for name, health_data in services_health_full.get("services", {}).items():
                service_status = health_data['status']
                # Extract extra info based on status: latency for healthy, error for unhealthy/down/etc
                extra_info = health_data.get('latency_ms') if service_status == 'healthy' else health_data.get('error')
                
                action, old_status, info_to_send = alerts.check_state_change(name, service_status, ['healthy'], extra_info)
                if action:
                    alerts.send_notification(name, service_status, old_status, extra_info=info_to_send)

            # --- Save & Log ---
            cycle_duration_ms = int((time.monotonic() - cycle_start_time) * 1000)
            
            # Save RAW detailed status to internal DB (e.g., 'down', 'timeout')
            all_metrics = {
                "timestamp_lima": timestamp_lima, **sys_metrics, "container_count": container_count,
                "internet_ok": internet_ok, "ping_ms": ping_ms, "worker_status": worker_status, 
                "cycle_duration_ms": cycle_duration_ms,
                "services_health": services_health_full.get("services", {})
            }
            database.save_metrics_to_db(all_metrics)

            # --- Log Cycle Summary ---
            log_items = []
            for name, data in services_health_full.get("services", {}).items():
                status = data['status']
                if status == 'healthy':
                    latency = data.get('latency_ms', 0)
                    log_items.append(f"{name} 🔵 ({latency}ms)")
                else:
                    error = data.get('error', 'Unknown')
                    log_items.append(f"{name} 🔴 [{status.upper()}] {error}")
            
            services_log_str = "   |   ".join(log_items)
            worker_log = alerts.global_states.get('worker', {})
            transient_cnt = worker_log.get('transient_counter', 0)
            duration_str = str(datetime.timedelta(seconds=transient_cnt * config.LOOP_INTERVAL_SECONDS))
            
            log_msg = (
                f"Metrics saved at {timestamp_pretty}.\n"
                f"  Services: {services_log_str}\n"
                f"  Worker Status: {worker_status or 'N/A'} ({worker_log.get('last_stable_status', 'N/A')} for {duration_str} - {transient_cnt} cycles). Cycle duration: {cycle_duration_ms}ms"
            )
            print(log_msg)
            
            if run_once:
                break

        except Exception as e:
            if run_once:
                raise e
            print(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(config.LOOP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
