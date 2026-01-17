import sqlite3
import uuid
from pathlib import Path
from config import SQLITE_DB_PATH

DB_FILE = Path(SQLITE_DB_PATH)

def initialize_database():
    """Initializes the SQLite database with the relational schema."""
    try:
        # Ensure the data directory exists
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        print("Initializing database...")
        
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()

        # Enable WAL mode for better concurrency
        cur.execute("PRAGMA journal_mode=WAL;")
        print("WAL mode enabled.")

        # 1. Table: monitoring_cycles (Global cycle facts)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS monitoring_cycles (
                id TEXT PRIMARY KEY,
                timestamp_lima TEXT NOT NULL,
                cpu_percent REAL NOT NULL,
                ram_percent REAL NOT NULL,
                ram_used_mb REAL NOT NULL,
                disk_percent REAL NOT NULL,
                uptime_seconds REAL,
                container_count INTEGER NOT NULL,
                internet_status BOOLEAN NOT NULL,
                ping_ms REAL,
                worker_status INTEGER,
                cycle_duration_ms INTEGER
            )
        """)

        # 2. Table: service_checks (Detailed metrics per service)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS service_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                service_url TEXT,
                status TEXT NOT NULL,
                status_code INTEGER,
                latency_ms REAL,
                error_message TEXT,
                FOREIGN KEY(cycle_id) REFERENCES monitoring_cycles(id)
            )
        """)

        # Create indexes for efficient querying
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cycles_timestamp ON monitoring_cycles(timestamp_lima);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_checks_service_name ON service_checks(service_name);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_checks_cycle_id ON service_checks(cycle_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cycles_ts_id ON monitoring_cycles(timestamp_lima, id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_svc_cycle_lat ON service_checks(cycle_id, service_name, latency_ms);")
        cur.execute("ANALYZE;")

        con.commit()
        con.close()
        print("Database initialized.")
    except sqlite3.Error as e:
        print(f"Database error during initialization: {e}")
        raise

def save_metrics_to_db(metrics):
    """Saves metrics to the relational database (monitoring_cycles + service_checks)."""
    try:
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()
        
        cycle_id = str(uuid.uuid4())

        # 1. Insert Cycle Data
        cur.execute("""
            INSERT INTO monitoring_cycles (
                id, timestamp_lima, cpu_percent, ram_percent, ram_used_mb, 
                disk_percent, uptime_seconds, container_count, internet_status, ping_ms, 
                worker_status, cycle_duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
            (
                cycle_id,
                metrics['timestamp_lima'],
                metrics['cpu_percent'],
                metrics['ram_percent'],
                metrics['ram_used_mb'], 
                metrics['disk_percent'],
                metrics.get('uptime_seconds'),
                metrics['container_count'],
                metrics['internet_ok'], 
                metrics['ping_ms'], 
                metrics['worker_status'],
                metrics['cycle_duration_ms']
            )
        )

        # 2. Insert Service Checks
        # metrics['services_health'] is expected to be a dictionary
        services = metrics.get('services_health', {})
        
        service_rows = []
        for name, data in services.items():
            service_rows.append((
                cycle_id,
                name,
                data.get('url'),
                data.get('status'),
                data.get('status_code'),
                data.get('latency_ms'),
                data.get('error')
            ))

        if service_rows:
            cur.executemany("""
                INSERT INTO service_checks (
                    cycle_id, service_name, service_url, status, status_code, latency_ms, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, service_rows)

        con.commit()
        con.close()
    except sqlite3.Error as e:
        print(f"Database error when saving metrics: {e}")
