from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import text
from typing import List, Optional, Dict
import pandas as pd
import datetime
import os
import pytz

from database import get_db
import models
import schemas

# --- Configuration ---
# Target number of data points for graph resolution (default: 30)
TARGET_DATA_POINTS = int(os.getenv('TARGET_DATA_POINTS', 30))

app = FastAPI(title="Heartbeat Dashboard API")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_uptime(seconds: float) -> str:
    """Formats seconds into a readable string (e.g., '14d 2h 30m 15s')."""
    if seconds is None:
        return "N/A"
    
    seconds = int(seconds)
    days = seconds // (24 * 3600)
    hours = (seconds % (24 * 3600)) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    
    return " ".join(parts)

def smart_format_date(iso_str: str) -> str:
    """
    Formats an ISO date string to time (if today) or date+time (if older).
    """
    if not iso_str:
        return "N/A"
    try:
        dt = pd.to_datetime(iso_str)
        now = datetime.datetime.now(dt.tz) if dt.tz else datetime.datetime.now()
        
        if dt.date() == now.date():
            return dt.strftime('%I:%M:%S %p')
        return dt.strftime('%Y-%m-%d %I:%M:%S %p')
    except Exception:
        return str(iso_str)

def smart_round(val: float) -> float:
    """Rounds to 2 decimals, returning an integer if there is no fractional part."""
    if val is None: return 0
    val = round(val, 2)
    return int(val) if val.is_integer() else val

async def fetch_analytics_optimized(db: AsyncSession, range_str: str):
    """
    Fetches analytics with dynamic grouping to ensure consistent data density.
    Calculates statistics directly from the database for accuracy.
    """
    lima_tz = pytz.timezone("America/Lima")
    now = datetime.datetime.now(lima_tz)
    
    # Time range definitions
    deltas = {
        "live": datetime.timedelta(minutes=5),
        "1h":  datetime.timedelta(hours=1),
        "12h": datetime.timedelta(hours=12),
        "24h": datetime.timedelta(hours=24),
        "7d":  datetime.timedelta(days=7),
        "30d": datetime.timedelta(days=30),
    }
    
    delta = deltas.get(range_str, deltas["live"])
    
    # Calculate grouping interval to match target data density
    interval = int(delta.total_seconds() / TARGET_DATA_POINTS)
    if interval < 1: interval = 1
    
    now_ts = int(now.timestamp())
    start_ts_raw = now_ts - int(delta.total_seconds())
    start_ts = (start_ts_raw // interval) * interval
    start_time_iso = datetime.datetime.fromtimestamp(start_ts, tz=lima_tz).isoformat()

    # 1. Global Metrics (Grouped by Interval)
    query_global = text(f"""
        SELECT 
            (strftime('%s', timestamp_lima) / {interval}) * {interval} as bucket_ts,
            avg(cpu_percent) as cpu,
            avg(ram_percent) as ram,
            avg(disk_percent) as disk,
            avg(cycle_duration_ms) as cycle,
            avg(ping_ms) as ping,
            max(timestamp_lima) as last_ts_in_bucket
        FROM monitoring_cycles
        WHERE timestamp_lima >= :start
        GROUP BY bucket_ts
        ORDER BY bucket_ts ASC
    """)
    
    result_global = await db.execute(query_global, {"start": start_time_iso})
    rows_global = result_global.fetchall()
    
    data_map = {r.bucket_ts: r for r in rows_global}

    # 2. Aggregated Stats (Uptime & Counts)
    query_stats = text("""
        SELECT 
            avg(internet_status) * 100 as net_up,
            sum(case when internet_status = 1 then 1 else 0 end) as net_ok_count,
            sum(case when internet_status = 0 then 1 else 0 end) as net_fail_count,
            avg(case when worker_status = 200 then 1 else 0 end) * 100 as worker_up
        FROM monitoring_cycles
        WHERE timestamp_lima >= :start
    """)
    res_stats = await db.execute(query_stats, {"start": start_time_iso})
    total_stats = res_stats.one()
    
    # 3. Precise Global Stats (Max, Avg, Min, Jitter) from raw data
    query_global_stats = text("""
        SELECT
            max(cycle_duration_ms) as cycle_max,
            avg(cycle_duration_ms) as cycle_avg,
            min(cycle_duration_ms) as cycle_min,
            max(ping_ms) as ping_max,
            avg(ping_ms) as ping_avg,
            min(ping_ms) as ping_min
        FROM monitoring_cycles
        WHERE timestamp_lima >= :start
    """)
    res_global_stats = await db.execute(query_global_stats, {"start": start_time_iso})
    real_stats = res_global_stats.one()

    c_max = int(real_stats.cycle_max or 0)
    c_min = int(real_stats.cycle_min or 0)
    p_max = int(real_stats.ping_max or 0)
    p_min = int(real_stats.ping_min or 0)

    cycle_stats_obj = {
        "max": c_max,
        "avg": int(real_stats.cycle_avg or 0),
        "min": c_min,
        "jitter": c_max - c_min
    }
    ping_stats_obj = {
        "max": p_max,
        "avg": int(real_stats.ping_avg or 0),
        "min": p_min,
        "jitter": p_max - p_min
    }
    
    # 4. Worker Status Distribution
    query_worker_dist = text("""
        SELECT 
            CASE 
                WHEN worker_status IS NULL THEN 'TIMEOUT'
                ELSE CAST(worker_status AS TEXT)
            END as status_label,
            count(*) as cnt
        FROM monitoring_cycles
        WHERE timestamp_lima >= :start
        GROUP BY status_label
        ORDER BY cnt DESC
    """)
    res_worker_dist = await db.execute(query_worker_dist, {"start": start_time_iso})
    worker_dist = [{"value": r.cnt, "name": r.status_label} for r in res_worker_dist.fetchall()]

    net_uptime_pct = smart_round(total_stats.net_up or 0)
    worker_uptime_pct = smart_round(total_stats.worker_up or 0)
    
    net_ok = int(total_stats.net_ok_count or 0)
    net_fail = int(total_stats.net_fail_count or 0)

    # 5. Data Backfilling & Grid Generation
    times = []
    sys_cpu, sys_ram, sys_disk = [], [], []
    cycle_dur, pings = [], []
    
    current_ts = start_ts
    while current_ts <= now_ts:
        row = data_map.get(current_ts)
        
        # Determine appropriate time label
        if row and row.last_ts_in_bucket:
            time_label = smart_format_date(row.last_ts_in_bucket)
        else:
            dt = datetime.datetime.fromtimestamp(current_ts, tz=lima_tz)
            now_local = datetime.datetime.now(lima_tz)
            if dt.date() == now_local.date():
                time_label = dt.strftime('%I:%M:%S %p')
            else:
                time_label = dt.strftime('%Y-%m-%d %I:%M:%S %p')
            
        times.append(time_label)
        
        if row:
            sys_cpu.append(round(row.cpu, 2))
            sys_ram.append(round(row.ram, 2))
            sys_disk.append(round(row.disk, 2))
            cycle_dur.append(int(row.cycle))
            pings.append(int(row.ping) if row.ping else 0)
        else:
            sys_cpu.append(None)
            sys_ram.append(None)
            sys_disk.append(None)
            cycle_dur.append(None)
            pings.append(None)
            
        current_ts += interval

    history_data = {
        "times": times,
        "system": {"cpu": sys_cpu, "ram": sys_ram, "disk": sys_disk},
        "cycle_duration": cycle_dur,
        "ping": pings,
        "services": {}
    }

    # 6. Service Metrics (Grouped)
    query_services = text(f"""
        SELECT 
            service_name,
            (strftime('%s', m.timestamp_lima) / {interval}) * {interval} as bucket_ts,
            avg(latency_ms) as lat
        FROM service_checks s
        JOIN monitoring_cycles m ON s.cycle_id = m.id
        WHERE m.timestamp_lima >= :start
        GROUP BY service_name, bucket_ts
        ORDER BY bucket_ts ASC
    """)
    
    result_svc = await db.execute(query_services, {"start": start_time_iso})
    rows_svc = result_svc.fetchall()

    # Organize service data
    svc_data_map = {}
    service_names = set()
    for r in rows_svc:
        service_names.add(r.service_name)
        if r.service_name not in svc_data_map:
            svc_data_map[r.service_name] = {}
        svc_data_map[r.service_name][r.bucket_ts] = int(r.lat)

    # Backfill service data
    svc_series_map = {}
    for s_name in service_names:
        s_data = []
        current_ts = start_ts
        while current_ts <= now_ts:
            val = svc_data_map.get(s_name, {}).get(current_ts)
            s_data.append(val if val is not None else None)
            current_ts += interval
        svc_series_map[s_name] = s_data

    history_data["services"] = svc_series_map

    # 7. Service Stats (Precise Uptime & Counts)
    query_svc_stats = text("""
        SELECT 
            service_name,
            avg(CASE WHEN status = 'healthy' THEN 1.0 ELSE 0.0 END) * 100 as uptime,
            sum(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END) as healthy_cnt,
            sum(CASE WHEN status != 'healthy' THEN 1 ELSE 0 END) as unhealthy_cnt,
            max(latency_ms) as max_lat,
            avg(latency_ms) as avg_lat,
            min(latency_ms) as min_lat
        FROM service_checks s
        JOIN monitoring_cycles m ON s.cycle_id = m.id
        WHERE m.timestamp_lima >= :start
        GROUP BY service_name
    """)
    result_svc_stats = await db.execute(query_svc_stats, {"start": start_time_iso})
    
    rows_stats = result_svc_stats.fetchall()

    svc_stats_dict = {}
    for r in rows_stats:
        s_max = int(r.max_lat or 0)
        s_min = int(r.min_lat or 0)
        svc_stats_dict[r.service_name] = {
            "uptime": smart_round(r.uptime or 0),
            "success": int(r.healthy_cnt or 0),
            "failure": int(r.unhealthy_cnt or 0),
            "max": s_max,
            "avg": int(r.avg_lat or 0),
            "min": s_min,
            "jitter": s_max - s_min
        }

    stats_summary = {
        "network_uptime": net_uptime_pct,
        "network_counts": {"success": net_ok, "failure": net_fail},
        "worker_uptime": worker_uptime_pct,
        "worker_dist": worker_dist,
        "services": svc_stats_dict,
        "cycle_stats": cycle_stats_obj,
        "ping_stats": ping_stats_obj
    }

    return history_data, stats_summary

@app.get("/api/live", response_model=schemas.DashboardResponse)
async def get_live_metrics(range: str = "1h", db: AsyncSession = Depends(get_db)):
    """
    Returns the most recent cycle data and historical analytics.
    """
    # Fetch the latest cycle with service checks
    stmt = (
        select(models.MonitoringCycle)
        .options(selectinload(models.MonitoringCycle.service_checks))
        .order_by(models.MonitoringCycle.timestamp_lima.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    cycle = result.scalar_one_or_none()

    if not cycle:
        raise HTTPException(status_code=404, detail="No metrics found in database")

    # Fetch historical data
    history_data, stats = await fetch_analytics_optimized(db, range)
    
    if not history_data:
        history_data = {"times": [], "system": {"cpu":[], "ram":[], "disk":[]}, "cycle_duration":[], "ping":[], "services":{}}
        stats = {"network_uptime": 0, "worker_uptime": 0, "worker_dist": [], "services": {}}

    # Construct the response
    return {
        "last_updated": smart_format_date(cycle.timestamp_lima),
        "system": {
            "cpu": cycle.cpu_percent,
            "ram": cycle.ram_percent,
            "disk": cycle.disk_percent,
            "containers": cycle.container_count,
            "uptime": format_uptime(cycle.uptime_seconds)
        },
        "monitor": {
            "worker_status": cycle.worker_status,
            "uptime": {range: stats["worker_uptime"]},
            "distribution": stats["worker_dist"],
            "stats": stats.get("cycle_stats", {"max":0, "avg":0, "min":0, "jitter":0})
        },
        "network": {
            "internet_status": cycle.internet_status,
            "uptime": stats["network_uptime"],
            "uptime_counts": stats.get("network_counts"),
            "stats": stats.get("ping_stats", {"max":0, "avg":0, "min":0, "jitter":0})
        },
        "services": [
            {
                "name": s.service_name,
                "url": s.service_url,
                "status": s.status,
                "latency": s.latency_ms,
                "stats": stats["services"].get(s.service_name, {"max":0, "avg":0, "min":0, "jitter":0, "uptime": 0, "success": 0, "failure": 0})
            } for s in cycle.service_checks
        ],
        "history": history_data
    }

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.datetime.now().isoformat()}

# Serve Static Files (Frontend)
# Must be placed after API routes to avoid capturing /api requests
static_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
else:
    print(f"WARNING: Static folder not found at {static_dir}")