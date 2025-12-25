# Heartbeat Monitor: High-Performance Monitoring Agent & Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-blue.svg" alt="Python 3.14">
  <img src="https://img.shields.io/badge/FastAPI-0.109-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/AlpineJS-3.x-8bc34a.svg" alt="AlpineJS">
  <img src="https://img.shields.io/badge/Docker-passing-brightgreen.svg" alt="Docker Build Status">
</p>

A lightweight, modular, and concurrent observability system specifically designed for Dockerized environments. This system not only verifies availability but also optimizes network latency, manages service states with a resilient architecture, and offers real-time visualization.

Developed in **Python 3.14 (Alpine)**, focused on resource efficiency and metric precision.

## 📊 Analytics Dashboard

The system includes a modern control panel to visualize your infrastructure health.

* **Frontend:** Built with **AlpineJS** and **Chart.js**. Lightweight, no complex build-step, with real-time updates ("Live Mode") and **Jitter** visualization.
* **Semantic Visualization:** Service health is represented using a rich color palette:
  * 🟢 **Healthy:** Service is responding correctly.
  * 🔴 **Down:** Connection refused or service stopped.
  * 🟠 **Error:** Server returned an error (HTTP 5xx).
  * 🟡 **Timeout:** Request exceeded the configured timeout.
  * ⚪ **Unknown:** Internal monitoring error or unexpected failure.
* **Backend:** High-performance RESTful API powered by **FastAPI**. Implements **Dynamic Resolution** (`TARGET_DATA_POINTS = 30`) to ensure fluid charts regardless of the queried time range (from 5 minutes to 30 days).

## 🏗️ System Architecture

The system uses a **decoupled Producer-Consumer pattern** via a shared database.

```ascii
+----------------------+           +--------------------------+
|   HEARTBEAT AGENT    |  (Write)  |       SQLITE (WAL)       |
| (Python / Producer)  |---------->|   (Hybrid Persistence)   |
+----------------------+           +--------------------------+
          ^                                     ^
          | (10s Loop)                          |
          |                                     | (Read-Only :ro)
+----------------------+           +--------------------------+
|  Services / Docker   |           |    DASHBOARD BACKEND     |
| (Monitoring Targets) |           |  (FastAPI / Consumer)    |
+----------------------+           +--------------------------+
                                                ^
                                                | (JSON / REST)
                                                v
                                   +--------------------------+
                                   |    DASHBOARD FRONTEND    |
                                   |   (AlpineJS / Chart.js)  |
                                   +--------------------------+
```

1. **Agent (Write):** Has exclusive write access to the DB. Uses WAL mode to prevent blocking reads.
2. **Dashboard (Read):** Mounts the data volume as `read-only` (`:ro`). If the agent goes down, the dashboard continues to show historical data.
3. **Frontend:** Consumes the backend API using intelligent *polling* (every 2s in Live mode).

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
4. **State Processing:** Changes (Healthy <-> Error/Down/Timeout) are evaluated against defined thresholds.
5. **Notification/Heartbeat:** If critical changes occur or a heartbeat is due, optimized JSON payloads are sent to external endpoints.
6. **Persistence:** An atomic commit of all cycle metrics is made to the local database.

## 📂 Code Structure (Monorepo)

The project has evolved into a **Monorepo** architecture to manage both the main agent and visualization/development tools:

```text
/
├── apps/
│   ├── heartbeat/     # Monitoring Agent (Python Service)
│   │   ├── main.py        # Main orchestrator.
│   │   ├── config.py      # Configuration management.
│   │   ├── monitors.py    # Health checks and metrics logic.
│   │   ├── alerts.py      # State management and notifications.
│   │   ├── network.py     # Network layer (Smart Request, IPv4).
│   │   └── database.py    # SQLite persistence.
│   ├── dashboard/     # Visualization Panel (New)
│   │   ├── backend/       # FastAPI API for analytics.
│   │   └── frontend/      # Reactive UI (AlpineJS + Chart.js).
│   └── mocks/         # Mock Server for local development
│       ├── server.py      # Python test server.
│       └── templates/     # Mock Controller UI.
├── data/              # Persistent volumes (DBs, logs)
│   ├── metrics.db     # Production database.
│   ├── metrics_dev.db # Development database.
│   └── ...
├── docker-compose.prod.yml  # Production Stack (Agent + Dashboard).
├── docker-compose.dev.yml   # Development Stack (Agent + Dashboard + Mock).
├── .env.prod.example        # Production env template.
├── .env.dev.example         # Development env template.
└── ...
```

### Module Descriptions (Heartbeat Agent)

* **`main.py`**: Contains the application's main execution loop. It coordinates initialization, data collection, state processing, and metric persistence.
* **`config.py`**: Centralizes environment variable reading, global constant definitions, and parsing of service configuration.
* **`monitors.py`**: Groups the functions responsible for obtaining system data (CPU, RAM, Disk) and performing HTTP/HTTPS and Docker health checks.
* **`alerts.py`**: Implements the logic for transient and stable state management, as well as notification mechanisms (N8N webhooks) and Cloudflare heartbeat communication.
* **`network.py`**: Provides the abstraction layer for network operations, including session optimization and the `smart_request` logic for DNS Override.
* **`database.py`**: Encapsulates all operations related to the SQLite database and the saving of collected metrics in each cycle.

## Monitoring Services

The agent's primary functionality is to monitor the status of multiple web services, report it to the worker, and generate alerts if their status changes persistently.

### Dynamic Configuration

The services to be monitored are configured dynamically via environment variables. The agent auto-discovers any variable starting with `SERVICE_URL_`.

1. **`SERVICE_URL_{name}`**: The URL to check. The `{name}` suffix acts as the service identifier.
   * Example: `SERVICE_URL_nextjs=https://www.example.com` -> Monitors service "nextjs".

A service is considered `"healthy"` if it responds with a `2xx` or `3xx` status code. Other responses result in specific states like `"error"` (for 5xx codes).

### Service States (Rich Taxonomy)

The system uses a granular state model to provide precise diagnostics:

* `healthy`: Service responded with 2xx/3xx.
* `down`: Connection refused or container stopped.
* `error`: HTTP 5xx server error.
* `timeout`: No response within `SERVICE_TIMEOUT_SECONDS`.
* `unknown`: Monitoring logic failed to execute.

### Advanced Service Configuration

The monitor supports advanced features to cover complex use cases, such as internal services or protected endpoints.

#### 1. Direct Container Monitoring (`docker:`)

For infrastructure services (like Nginx, tunnels, databases) that do not expose an easily accessible HTTP port, you can use the `docker:` protocol. This directly verifies if the container is in a `running` state.

* **Syntax:** `SERVICE_URL_<name>="docker:<container_name>"`
* **Example:** `SERVICE_URL_nginx="docker:my-nginx-container"`
* **Note:** This requires the agent to have access to the Docker socket (`/var/run/docker.sock`).

#### 2. Custom HTTP Headers

Some health endpoints require authentication or specific headers to respond correctly. You can define these using environment variables with the `SERVICE_HEADERS_` prefix.

* **Syntax:** `SERVICE_HEADERS_<name>="Header1:Value1,Header2:Value2"`
* **Example:**

    ```bash
    SERVICE_URL_api="https://my-api.com/health"
    SERVICE_HEADERS_api="x-health-check:true,Authorization:Bearer my-token"
    ```

### Latency Optimization (DNS Override)

For environments where services reside on the same local network or server (e.g., Docker containers behind an Nginx on the host), the agent allows configuring a DNS override IP (`INTERNAL_DNS_OVERRIDE_IP`) to drastically reduce latency.

* **How it Works:** If this variable is defined, the agent will intercept requests to monitored services, resolve the domain directly to the specified IP, force the use of HTTP (avoiding unnecessary SSL handshake on the internal network), and inject the correct `Host` header.
* **Benefit:** Reduces latency from ~50ms to ~1-3ms by bypassing external DNS resolution and public routing.
* **Configuration:** See `INTERNAL_DNS_OVERRIDE_IP` variable in `.env`.

### Health Status Payload

In each cycle, the agent constructs a JSON payload summarizing the health status of the services and sends it to the `HEARTBEAT_URL`. The payload now includes rich states for advanced worker-side processing.

* **Payload Structure:**

    ```json
    {
      "services": {
        "nextjs": { "status": "healthy" },
        "strapi": { "status": "down" },
        "umami": { "status": "timeout" }
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
    * **Service Down:** Includes the specific reason for the failure (e.g., `HTTP 500`, `Timeout`, `Container Exited`) for facilitate immediate diagnosis.
    * **Service Recovered:** Shows the current latency of the service upon recovery.
    * **Timestamp:** All alerts include the exact date and time of the event (configured timezone) for accurate auditing.

3. **Trigger Conditions:**
    * **Service Downtime:** After `STATUS_CHANGE_THRESHOLD` consecutive failures (down/error/timeout).
    * **Service Recovery:** Immediate upon the first success.
    * **Worker Status:** Monitoring of state changes of the Cloudflare worker itself with contextual alerts.

This mechanism ensures that only confirmed state changes are notified, applying consistent logic to all monitored elements.

## 💾 Data Persistence (Relational Schema)

The system uses **SQLite** in **WAL (Write-Ahead Logging)** mode to allow high-concurrency writes from the agent and simultaneous reads from the dashboard without locking. The schema has been normalized to support efficient analytical queries.

### Table 1: `monitoring_cycles` (Global Facts)

Stores one row per execution cycle (10s).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `TEXT (PK)` | Unique cycle UUID. |
| `timestamp_lima`| `TEXT` | ISO8601 Timestamp (Indexed). |
| `cpu_percent` | `REAL` | Global CPU usage. |
| `ram_percent` | `REAL` | Global RAM usage. |
| `disk_percent`| `REAL` | Root disk usage. |
| `uptime_seconds`| `REAL` | Host system uptime. |
| `container_count`| `INTEGER`| Total running Docker containers. |
| `internet_status` | `BOOLEAN`| `1` (Online) / `0` (Offline). |
| `ping_ms` | `REAL` | Internet latency (ICMP/HTTP Ping). |
| `worker_status` | `INTEGER` | HTTP code from Cloudflare Worker (Heartbeat). <br> - `200`: **Success**. Heartbeat received and processed. <br> - `220`: **Warning (Blind)**. Received but previous state unknown. <br> - `221`: **Warning (Recovery Update Failed)**. Recovery detected but state update failed. <br> - `500`: **Critical Worker Error**. Essential step failed. <br> - `NULL`: **Local Agent Error**. Communication failed (timeout, network, DNS). |
| `cycle_duration_ms` | `INTEGER` | Total cycle execution time. |

### Table 2: `service_checks` (Service Details)

Stores individual status for each monitored service per cycle. 1:N relationship with `monitoring_cycles`.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `INTEGER (PK)` | Auto-incremental. |
| `cycle_id` | `TEXT (FK)` | Reference to `monitoring_cycles.id`. |
| `service_name` | `TEXT` | Service name (Indexed). |
| `service_url` | `TEXT` | Verified endpoint. |
| `status` | `TEXT` | Semantic status: `healthy`, `down`, `error`, `timeout`, `unknown`. |
| `latency_ms` | `REAL` | Service response time (NULL if down). |
| `status_code` | `INTEGER` | HTTP response code (e.g., 200, 500). |
| `error_message` | `TEXT` | Error detail (Timeout, Connection Refused). |

## 🔌 Dashboard API (Backend)

The dashboard backend exposes a REST API optimized for real-time and historical metric consumption.

### `GET /api/live`

Returns the current system status and historical time series.

* **Parameters:**
  * `range` (Query, optional): Time window. Options: `live` (5m), `1h`, `12h`, `24h`, `7d`, `30d`. Default: `1h`.

* **Optimization (Dynamic Resolution):**
  The backend automatically applies a downsampling algorithm based on the `TARGET_DATA_POINTS = 30` constant.
  * If you request `24h`, data is grouped into ~48-minute buckets.
  * If you request `live` (5m), data is returned in 10-second buckets (raw data).
  * **Benefit:** The frontend always receives ~30 points, keeping rendering fast and lightweight.

* **Included Metrics:**
  * **Jitter:** Calculated as `MAX(latency) - MIN(latency)` per bucket.
  * **Uptime %:** Calculated over total cycles in the range.
  * **Status Distribution:** Counts grouped by rich semantic status (healthy, down, error, etc).

## ⚙️ Configuration & Env Variables

System behavior is centrally controlled via environment variables (`.env` files).

### 🔧 Operational Configuration (Advanced)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `LOOP_INTERVAL_SECONDS` | Agent main loop interval (in seconds). | `10` |
| `STATUS_CHANGE_THRESHOLD` | Confirmation threshold for state changes (Debounce). | `4` |
| `SERVICE_TIMEOUT_SECONDS` | Maximum wait time for each service health check. | `2` |
| `TARGET_DATA_POINTS` | Point density in dashboard charts (Bucketing). | `30` |
| `TZ` | System timezone (e.g., `America/Lima`). | `UTC` |

### 🔑 Credentials & Endpoints

| Variable | Required | Description | Example |
| :--- | :---: | :--- | :--- |
| `SECRET_KEY` | **Yes** | Shared key to authenticate with the Cloudflare Worker. | `sk_12345abcdef` |
| `HEARTBEAT_URL` | **Yes** | Cloudflare Worker endpoint URL for heartbeats. | `https://worker.dev/api/heartbeat` |
| `N8N_WEBHOOK_URL` | No | Webhook URL for external alerts (Slack, Discord, etc). | `https://n8n.mi-server.com/...` |
| `SQLITE_DB_PATH` | No | Internal path for the SQLite database file. | `data/metrics.db` |

### 🔍 Service Monitoring

| Variable                | Description                                                       | Example                     |
| :---------------------- | :---------------------------------------------------------------- | :-------------------------- |
| `SERVICE_NAMES`         | Comma-separated list of service identifiers.                      | `api,webapp,db_primary`     |
| `SERVICE_URL_{NAME}`    | Target URL for health check. Supports `http(s)://` and `docker:`. | `docker:postgres-container` |
| `SERVICE_HEADERS_{NAME}`| Optional HTTP headers (Auth, User-Agent, etc.).                   | `Authorization:Bearer xyz`  |

### 🌐 Advanced Networking

| Variable | Description | Example |
| :--- | :--- | :--- |
| `INTERNAL_DNS_OVERRIDE_IP` | IP to force local DNS resolution. Useful for Docker setups. | `172.17.0.1` |

## 🛠️ Setup and Deployment

### Production Environment

1. **Clone the repository:**

    ```bash
    git clone https://github.com/iamseb4s/heartbeat-monitor.git
    cd heartbeat-monitor
    ```

2. **Configure Variables:**
    * Copy `.env.prod.example` to `.env.prod`.
    * Fill in `SECRET_KEY`, `HEARTBEAT_URL`, `N8N_WEBHOOK_URL`, `SERVICE_NAMES`, and corresponding `SERVICE_URL_*`.
3. **Run:**

    ```bash
    docker compose -f docker-compose.prod.yml up -d --build
    ```

4. **Access:**
    * **Dashboard:** `http://localhost:8100` (or configured IP/domain).
    * **Agent Logs:** `docker logs -f heartbeat-agent-prod`

### Development Environment (Local + Mock)

1. **Configure Variables:** Copy `.env.dev.example` to `.env.dev`.
2. **Run:** `docker compose -f docker-compose.dev.yml up --build`
3. **Available Tools:**
    * **Dashboard:** **<http://localhost:8098>** - Real-time metrics visualization.
    * **Mock Controller:** **<http://localhost:8099>** - Simulate outages, view logs, and force responses.

## 🧪 Testing

The project includes a comprehensive suite of unit and integration tests.

* **Manual Execution:** Run tests inside the development container:

  ```bash
  docker exec heartbeat-agent-dev pytest
  ```

* **Automation (Git Hook):** To execute tests automatically before each merge, enable the included hook:

  ```bash
  git config core.hooksPath .githooks
  ```
