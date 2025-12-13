# Heartbeat Monitor: Technical Documentation

## Overview

This document details the architecture and internal workings of the monitoring agent. The agent is a Python script running in a Docker container, designed to assess the health of a server and its services, reporting metrics to an external endpoint and a local database.

## Architecture and Execution Flow

The agent operates in a main loop that runs every `LOOP_INTERVAL_SECONDS` (currently 10 seconds). The execution is clock-aligned to ensure interval consistency (e.g., it runs at :00, :10, :20 seconds past the minute, etc.).

Each execution cycle follows a concurrent model to optimize time and prevent blocking:

1. **Sequential CPU Task:** First, system metrics (`cpu_percent`, `ram_percent`, etc.) are collected using `psutil`. The `psutil.cpu_percent(interval=None)` call is non-blocking and measures CPU usage since the last call.
2. **Concurrent I/O Tasks:** Immediately after, a `ThreadPoolExecutor` is used to launch all network-bound tasks (which are inherently blocking) in parallel. This includes:
    * `check_services_health`: Checks the status of all services defined in the environment variables.
    * `check_internet_and_ping`: Measures connectivity and latency to `google.com`.
    * `get_container_count`: Connects to the Docker socket to count active containers.
3. **Result Collection:** The script waits for all concurrent tasks to complete before proceeding.
4. **Heartbeat Transmission:** With the results from the checks, a payload is constructed and sent to the `HEARTBEAT_URL`.
5. **State and Alert Processing:** The status of the worker and each service is analyzed to determine if a stable state change has occurred that requires a notification.
6. **Database Persistence:** Finally, all metrics and results from the cycle are saved to the SQLite database.

### Cycle Time Estimation

The use of `ThreadPoolExecutor` means that the duration of the I/O phase is determined by the slowest task, not the sum of all tasks. The `cycle_duration_ms` stored in the database records the actual duration of each cycle for analysis.

## Service Monitoring

The agent's primary functionality is to monitor the status of multiple web services, report it to the worker, and generate alerts if their status changes persistently.

### Dynamic Configuration

The services to be monitored are not hard-coded. They are configured dynamically via environment variables:

1. **`SERVICE_NAMES`**: A comma-separated list of service names (e.g., `SERVICE_NAMES=nextjs,strapi,umami`).
2. **`SERVICE_URL_{name}`**: The URL to check for each defined service name (e.g., `SERVICE_URL_nextjs=https://www.example.com`).

A service is considered `"healthy"` if it responds with a `2xx` or `3xx` status code. Otherwise, it is marked as `"unhealthy"`.

### Advanced Service Configuration

The monitor supports advanced features to cover complex use cases, such as internal services or protected endpoints.

#### 1. Direct Container Monitoring (`docker:`)
For infrastructure services (like Nginx, tunnels, databases) that do not expose an easily accessible HTTP port, you can use the `docker:` protocol. This directly verifies if the container is in a `running` state.

*   **Syntax:** `SERVICE_URL_<name>="docker:<container_name>"`
*   **Example:**
    ```bash
    SERVICE_URL_nginx="docker:my-nginx-container"
    ```
*   **Note:** This requires the agent to have access to the Docker socket (`/var/run/docker.sock`), which is already configured by default in the `docker-compose.yml`.

#### 2. Custom HTTP Headers
Some health endpoints require authentication or specific headers to respond correctly. You can define these using environment variables with the `SERVICE_HEADERS_` prefix.

*   **Syntax:** `SERVICE_HEADERS_<name>="Header1:Value1,Header2:Value2"`
*   **Example:**
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

All state logic is managed through a single generic function, `check_state_change`, and stored in a global in-memory dictionary, `global_states`. This approach allows monitoring any item (the main worker or individual services) using the same rules, avoiding code duplication.

### Notification Logic

The system sends alerts to the `N8N_WEBHOOK_URL` (the sole channel for all notifications) under the following conditions:

1. **Service Downtime:**
    * If a service reports an `unhealthy` status for `STATUS_CHANGE_THRESHOLD` (currently 4) consecutive cycles, a "Service Down" alert is sent.

2. **Service Recovery:**
    * If a service that was down reports `healthy` **just once**, a "Service Recovered" alert is sent immediately.

3. **Worker Status Change:**
    * Uses the same `STATUS_CHANGE_THRESHOLD` to confirm a stable state change (e.g., from `200` to `500`).
    * Recovery to a `200` status is notified immediately.
    * Alert messages are customized for each status code (`200`, `220`, `221`, `500`) and for cases where the worker is unreachable (due to lack of internet or API failure), providing more precise context.

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
| `cycle_duration_ms` | `REAL` | Duration of the monitoring cycle (ms). |
| `services_health`| `TEXT` | JSON with detailed status and latency of each service. |

## Setup and Deployment

1. **Clone the repository:** `git clone https://github.com/iamseb4s/heartbeat-monitor.git && cd heartbeat-monitor`
2. **Configure `.env`:** Copy `.env.example` to `.env` and fill in `SECRET_KEY`, `HEARTBEAT_URL`, `N8N_WEBHOOK_URL`, `SERVICE_NAMES`, and the corresponding `SERVICE_URL_*` values.
3. **Run:** `docker compose up -d --build`
4. **View Logs:** `docker compose logs -f monitor-agent`
