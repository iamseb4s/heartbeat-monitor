# Heartbeat Monitor: High-Performance Monitoring Agent

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-blue.svg" alt="Python 3.14">
  <img src="https://img.shields.io/badge/Docker-passing-brightgreen.svg" alt="Docker Build Status">
</p>

A lightweight, modular, and concurrent monitoring agent specifically designed for Dockerized environments. This system not only verifies availability but also optimizes network latency and manages service states with a resilient architecture.

Developed in **Python 3.14 (Alpine)**, focused on resource efficiency and metric precision.

## 🚀 Key Technical Features

More than a simple "ping" script, this project implements engineering patterns to solve common problems in distributed monitoring:

* **⚡ Concurrent Architecture:** `ThreadPoolExecutor` implementation to parallelize I/O operations (HTTP requests, Docker socket queries), decoupling metric collection from network blocking and ensuring precise execution cycles.
* **🧠 Smart Networking:**
  * **DNS Override & Host Injection:** Mechanism capable of intercepting traffic to internal services, resolving directly to local IPs and injecting `Host` headers. This eliminates external DNS resolution latency and SSL overhead in internal networks (reducing ~50ms to ~2ms).
  * **IPv4 Enforcement:** Custom HTTP adapters at the transport layer to mitigate common IPv6 resolution delays in Alpine Linux/Docker containers.
* **🐳 Native Docker Protocol:** Support for the `docker:<container_name>` scheme, allowing direct health checks against the Unix Docker socket (`/var/run/docker.sock`) for services that do not expose HTTP ports.
* **🛡️ Data Resilience:** Use of SQLite in **WAL (Write-Ahead Logging)** mode to allow high concurrency in read/write operations without database blocking.
* **🔔 Debounced State Management:** Intelligent alerting system that filters false positives using configurable state change thresholds and automatic retry logic for failed webhooks.

## ⚙️ Agent Execution Flow

The agent operates in a main loop, executing every 10 seconds, coordinating collection, processing, and notification.

```ascii
[ START ]
    |
    v
[ 1. Load Configuration (.env) ]
    |
    v
[ 2. Init Database (SQLite WAL) ]
    |
    +---> [ MAIN LOOP (Every 10s) ] <-------------------------------+
            |                                                       |
            |-- (A) System Metrics (CPU/RAM) [Synchronous]          |
            |                                                       |
            |-- (B) Health Checks [ThreadPoolExecutor / Parallel]   |
            |       |--> HTTP/HTTPS (Smart Request)                 |
            |       |--> Docker Socket                              |
            |       +--> Ping Internet                              |
            |                                                       |
            v                                                       |
    [ 3. Process State (Debounce Logic) ]                           |
            |                                                       |
            +--- State Changed? --------> [ Send Alert (N8N) ]      |
            |                                                       |
            +--- Internet OK? ----------> [ Send Heartbeat (CF) ]   |
            |                                                       |
            v                                                       |
    [ 4. Persistence (Save Metrics to DB) ] ------------------------+
```

### Detailed Execution Flow (10s Cycle)

1. **Initialization:** Configuration loading and establishment of persistent connections (Keep-Alive).
2. **System Metrics (Synchronous):** Instantaneous reading of CPU/RAM/Disk (`psutil`).
3. **Health Checks (Parallel):** Concurrent threads are launched to verify all configured services and Internet connectivity.
4. **State Processing:** Changes (Healthy <-> Unhealthy) are evaluated against defined thresholds.
5. **Notification/Heartbeat:** If critical changes occur or a heartbeat is due, optimized JSON payloads are sent to external endpoints.
6. **Persistence:** An atomic commit of all cycle metrics is made to the local database.

## 📂 Code Structure

The project has been refactored from a monolithic script into a modular architecture based on Single Responsibility Principle (SRP):

```text
app/
├── main.py        # Main application orchestrator.
├── config.py      # Configuration and environment variables management.
├── monitors.py    # Metrics collection and health checks.
├── alerts.py      # State management and notification sending.
├── network.py     # Network infrastructure and requests configuration.
└── database.py    # SQLite data persistence functionalities.
```

### Module Descriptions

* **`main.py`**: Contains the application's main execution loop. It coordinates initialization, data collection, state processing, and metric persistence by interacting with other modules.
* **`config.py`**: Centralizes environment variable reading, global constant definitions, and parsing of service configuration for monitoring.
* **`monitors.py`**: Groups the functions responsible for obtaining system data (CPU, RAM, Disk), counting Docker containers, and performing health checks for HTTP/HTTPS and Docker services.
* **`alerts.py`**: Implements the logic for transient and stable state management, as well as the mechanism for sending alerts via N8N webhooks and heartbeat communication to the Cloudflare worker.
* **`network.py`**: Provides the abstraction layer for network operations. Includes HTTP session configuration (forcing IPv4), and the `smart_request` function with its internal DNS override logic.
* **`database.py`**: Encapsulates all operations related to the SQLite database, including its initialization (table creation) and the saving of collected metrics in each cycle.

## Monitoring Services

The agent's primary functionality is to monitor the status of multiple web services, report it to the worker, and generate alerts if their status changes persistently.

### Dynamic Configuration

The services to be monitored are configured dynamically via environment variables:

1. **`SERVICE_NAMES`**: Comma-separated list of service names (e.g., `SERVICE_NAMES=nextjs,strapi,umami`).
2. **`SERVICE_URL_{name}`**: The URL to check for each defined name (e.g., `SERVICE_URL_nextjs=https://www.example.com`).

A service is considered `"healthy"` if it responds with a `2xx` or `3xx` status code. Otherwise, it is marked as `"unhealthy"`.

### Advanced Service Configuration

The monitor supports advanced features to cover complex use cases, such as internal services or protected endpoints.

#### 1. Direct Container Monitoring (`docker:`)

For infrastructure services (like Nginx, tunnels, databases) that do not expose an easily accessible HTTP port, you can use the `docker:` protocol. This directly verifies if the container is in a `running` state.

* **Syntax:** `SERVICE_URL_<name>="docker:<container_name>"`
* **Example:**

    ```bash
    SERVICE_URL_nginx="docker:my-nginx-container"
    ```

* **Note:** This requires the agent to have access to the Docker socket (`/var/run/docker.sock`), which is already configured by default in the `docker-compose.yml`.

#### 2. Custom HTTP Headers

Some health endpoints require authentication or specific headers to respond correctly. You can define these using environment variables with the `SERVICE_HEADERS_` prefix.

* **Syntax:** `SERVICE_HEADERS_<name>="Header1:Value1,Header2:Value2"`
* **Example:**

    ```bash
    # Checks an endpoint that requires a special token or flag
    SERVICE_URL_api="https://my-api.com/health"
    SERVICE_HEADERS_api="x-health-check:true,Authorization:Bearer my-token"
    ```

### Latency Optimization (DNS Override)

For environments where services reside on the same local network or server (e.g., Docker containers behind an Nginx on the host), the agent allows configuring a DNS override IP (`INTERNAL_DNS_OVERRIDE_IP`) to drastically reduce latency.

* **How it Works:** If this variable is defined, the agent will intercept requests to monitored services, resolve the domain directly to the specified IP, force the use of HTTP (avoiding unnecessary SSL handshake on the internal network), and inject the correct `Host` header.
* **Benefit:** Reduces latency from ~50ms to ~1-3ms by bypassing external DNS resolution and public routing.
* **Configuration:** See `INTERNAL_DNS_OVERRIDE_IP` variable in `.env`.

### Health Status Payload

In each cycle, the agent constructs a JSON payload summarizing the health status of the services and sends it to the `HEARTBEAT_URL`.

* **Payload Structure:**

    ```json
    {
      "services": {
        "nextjs": { "status": "healthy" },
        "strapi": { "status": "unhealthy" },
        "umami": { "status": "healthy" }
      }
    }
    ```

## State Management and Alerting

To prevent false alarms from transient failures and to centralize notifications, the agent implements a **unified state architecture**.

All state logic is managed through a single generic function, `check_state_change`, and is stored in a global in-memory dictionary, `global_states`. This approach allows monitoring any item (the main worker or individual services) using the same rules, avoiding code duplication.

### Notification Logic

The system sends alerts to the `N8N_WEBHOOK_URL` under the following conditions, now including robustness and detail mechanisms:

1. **Robustness and Retries:**
    * If sending the alert fails (e.g., webhook timeout), the system automatically retries up to **3 times** before giving up, ensuring critical alerts reach their destination.

2. **Enriched Alerts:**
    * **Service Down:** Includes the specific reason for the failure (e.g., `HTTP 500`, `Timeout`, `Container Exited`) to facilitate immediate diagnosis.
    * **Service Recovered:** Shows the current latency of the service upon recovery.
    * **Timestamp:** All alerts include the exact date and time of the event (configured timezone) for accurate auditing.

3. **Trigger Conditions:**
    * **Service Downtime:** After `STATUS_CHANGE_THRESHOLD` consecutive failures.
    * **Service Recovery:** Immediate upon the first success.
    * **Worker Status:** Monitoring of state changes of the Cloudflare worker itself with contextual alerts.

This mechanism ensures that only confirmed state changes are notified, applying consistent logic to all monitored elements.

## Data Persistence (Database)

All metrics are stored in an SQLite database (`metrics.db`) with `WAL` mode enabled to improve write/read concurrency.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `TEXT` | Unique UUID of the record. |
| `timestamp_lima`| `TEXT` | ISO8601 timestamp (Lima timezone). |
| `cpu_percent` | `REAL` | CPU usage. |
| `ram_percent` | `REAL` | RAM usage (%). |
| `ram_used_mb` | `REAL` | Used RAM (MB). |
| `disk_percent`| `REAL` | Root disk usage (%). |
| `container_count`| `INTEGER`| Active Docker containers. |
| `internet_ok` | `INTEGER`| `1` if connected, `0` otherwise. |
| `ping_ms` | `REAL` | Latency to `google.com`. |
| `worker_status` | `INTEGER` | HTTP status code returned by the Cloudflare Worker API. Reflects the outcome of the heartbeat processing. <br> - `200`: **Success**. Heartbeat received, processed, and host/service status was updated. Can indicate a "recorded" (no change) or "recovered" state. <br> - `220`: **Warning (Blind)**. Heartbeat received and timestamp updated, but the API could not read the *previous* state from its database. Unable to determine if a recovery occurred. <br> - `221`: **Warning (Recovery Update Failed)**. A recovery was detected, but the API failed to update its own state or send the notification. <br> - `500`: **Critical Worker Error**. The API failed an essential step (e.g., writing the initial timestamp) and the heartbeat was aborted. <br> - `NULL`: **Local Agent Error**. The monitoring script failed to contact the worker API (e.g., timeout, network error, DNS issue). |
| `cycle_duration_ms` | `INTEGER` | Duration of the monitoring cycle (ms). |
| `services_health`| `TEXT` | JSON with detailed status, latency, and error info for each service. <br> Ex: `{"app": {"status": "healthy", "latency_ms": 25, "error": null}}` |

## Setup and Deployment

1. **Clone the repository:** `git clone https://github.com/iamseb4s/heartbeat-monitor.git && cd heartbeat-monitor`
2. **Configure `.env`:** Copy `.env.example` to `.env` and fill in `SECRET_KEY`, `HEARTBEAT_URL`, `N8N_WEBHOOK_URL`, `SERVICE_NAMES`, and the corresponding `SERVICE_URL_*` values.
3. **Run:** `docker compose up -d --build`
4. **View Logs:** `docker compose logs -f monitor-agent`
    * **Note on Logs:** To keep console logs clean, the `error` field is not displayed when a service is `healthy`. This field will only appear in logs and notifications when the service is `unhealthy` and has an associated error.
