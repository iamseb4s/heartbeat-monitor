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
5. **Database Persistence:** Finally, all metrics and results from the cycle are saved to the SQLite database.

### Worst-Case Cycle Time Estimation

The use of `ThreadPoolExecutor` means that the duration of the I/O phase is determined by the slowest task, not the sum of all tasks.

* **Normal Scenario:** All network checks respond quickly (e.g., < 300ms). The entire cycle should take less than 1 second.
* **Worst-Case Scenario (Service Timeout):** If one or more services fail to respond, the `_check_one_service` function will take the time defined in `SERVICE_TIMEOUT_SECONDS` (currently 2 seconds). The `ThreadPoolExecutor` will wait for these 2 seconds.
* **Worst-Case Scenario (Heartbeat Timeout):** The heartbeat transmission has its own timeout of 6 seconds.

Therefore, the maximum theoretical duration of a cycle is approximately **`SERVICE_TIMEOUT_SECONDS` + `heartbeat_timeout`**, which could reach about 8 seconds in an extreme cascading failure scenario. The `cycle_duration_ms` stored in the database records the actual duration of each cycle for analysis.

## Service Monitoring

The agent's primary functionality is to monitor the status of multiple web services and report it.

### Dynamic Configuration

The services to be monitored are not hard-coded. They are configured dynamically via environment variables, following a specific pattern:

1. **`SERVICE_NAMES`**: A comma-separated list of service names.
    * Example: `SERVICE_NAMES=nextjs,strapi,umami`
2. **`SERVICE_URL_{name}`**: The URL to check for each defined service name.
    * Example: `SERVICE_URL_nextjs=https://www.example.com`, `SERVICE_URL_strapi=https://api.example.com`

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

* A service is considered `"healthy"` if it responds with a `2xx` or `3xx` status code. Otherwise, it is marked as `"unhealthy"`.

## State Management and Alerting

To prevent false alarms from transient failures, the agent implements a simple state machine before sending alerts to the n8n webhook.

* **`last_stable_status`**: Stores the last worker status code that has remained stable. It is retrieved from the database on startup to persist state across restarts.
* **`transient_status`**: Stores the status observed in the current cycle.
* **`transient_counter`**: Counts how many consecutive cycles the `transient_status` has been observed.
* **`STATE_CHANGE_THRESHOLD`**: If the `transient_counter` reaches this threshold (currently 4 cycles), the status is considered "stable." If this new stable status differs from `last_stable_status`, an alert is sent to n8n, and `last_stable_status` is updated.

This mechanism ensures that only confirmed state changes are reported, not momentary fluctuations.

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
