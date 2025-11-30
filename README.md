# Heartbeat Monitor: Local Server Agent

## Overview

This repository contains a Dockerized Python agent designed to monitor the status of a local server. It collects system metrics, counts running Docker containers, checks internet connectivity, and sends regular heartbeats to a Cloudflare Worker API. It also integrates with a local n8n instance for immediate alerts if the Cloudflare monitoring service itself becomes unreachable.

## Features

* **System Metrics Collection:** Gathers CPU, RAM, and Disk usage statistics.
* **Docker Container Count:** Monitors the number of active Docker containers on the host.
* **Internet Connectivity Check:** Verifies internet access and measures latency to a reliable external endpoint.
* **Clock-Aligned Execution:** Runs every 10 seconds, precisely aligned with the system clock (e.g., at :00, :10, :20 seconds).
* **Cloudflare Heartbeat:** Sends authenticated POST requests to a Cloudflare Worker, acting as a "heartbeat" signal.
* **Local Alerting (n8n):** Triggers a local n8n webhook if the Cloudflare Worker becomes unreachable, providing a redundant alert mechanism.
* **Persistent Data Logging:** Stores all collected metrics in a local SQLite database (`metrics.db`) for historical analysis.
* **Robust Alerting Logic:** Suppresses initial alerts on startup but notifies for all subsequent state changes (online/offline transitions).

## Database Schema

The collected data is stored in an SQLite database (`metrics.db`) within the `data/` directory. The primary table is `metrics`:

| Column | Type | Description |
| :-------------- | :------- | :----------------------------------------------------------------------- |
| `id` | `TEXT` (UUID) | Primary Key, a unique identifier for the record. |
| `timestamp_lima` | `TEXT` (ISO8601) | Timestamp of the record in Lima timezone (UTC-5). |
| `cpu_percent` | `REAL` | CPU usage percentage. |
| `ram_percent` | `REAL` | RAM usage percentage. |
| `ram_used_mb` | `REAL` | Used RAM in Megabytes. |
| `disk_percent` | `REAL` | Disk usage percentage of the root filesystem. |
| `container_count`| `INTEGER` | Number of running Docker containers. |
| `internet_ok` | `INTEGER` | `1` if internet is accessible, `0` otherwise. |
| `ping_ms` | `REAL` | Latency in milliseconds to a test server (Google). `NULL` if no internet. |
| `worker_status` | `INTEGER` | HTTP status code of the heartbeat sent to the Cloudflare worker. `NULL` if heartbeat failed. |
| `cycle_duration_ms` | `REAL` | Duration of the current monitoring cycle in milliseconds. |

## `monitor.py` - The Core Agent Script

The `app/monitor.py` script is the central component responsible for:

* **Database Management:** Initializes the `metrics.db` with WAL mode enabled and creates the `metrics` table.
* **Metric Collection:** Calls various functions (`get_system_metrics`, `get_container_count`, `check_internet_and_ping`) to gather server status.
* **Heartbeat Transmission:** Sends authenticated data to the configured `HEARTBEAT_URL`.
* **Clock Alignment:** Manages the execution loop to ensure metrics are collected precisely every 10 seconds.
* **State Persistence:** Reads the `last_worker_status` from the database on startup to maintain alerting context across restarts.
* **Alerting Logic:** Detects changes in `worker_status` and sends detailed alerts to the n8n webhook, intelligently suppressing false positives on initial startup.

## Getting Started

Follow these steps to set up and run the Heartbeat Monitor:

1. **Clone the repository:**

    ```bash
    git clone https://github.com/iamseb4s/heartbeat-monitor.git
    cd heartbeat-monitor
    ```

2. **Configure Environment Variables:**
    Copy the example environment file and fill in your details:

    ```bash
    cp .env.example .env
    ```

    Edit the `.env` file with your `SECRET_KEY`, `HEARTBEAT_URL` (your Cloudflare Worker endpoint), and `N8N_WEBHOOK_URL` (your local n8n webhook for local alerts). Refer to `.env.example` for details.

3. **Run with Docker Compose:**
    Build the Docker image and start the monitoring service:

    ```bash
    docker compose up -d --build
    ```

4. **View Logs:**
    To check the monitor's output:

    ```bash
    docker compose logs -f monitor-agent
    ```

    (Press `Ctrl+C` to exit the logs).

5. **Inspect Database:**
    To view the latest records being written to the database (without running as root):

    ```bash
    sqlite3 data/metrics.db "SELECT * FROM metrics ORDER BY timestamp_lima DESC LIMIT 20;"
    ```

## Troubleshooting

If you encounter permission errors with `metrics.db` or the Docker socket:

* Ensure the `data/` directory is owned by your user (`ls -l data/`).
* Verify your user's UID and the Docker group's GID are correctly set in `docker-compose.yml` (`user: "YOUR_UID:DOCKER_GID"`). You can find your UID with `id -u` and Docker GID with `getent group docker | cut -d: -f3`).
