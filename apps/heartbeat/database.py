import sqlite3
import uuid
from pathlib import Path
from config import SQLITE_DB_PATH

DB_FILE = Path(SQLITE_DB_PATH)

def initialize_database():
    """Initializes the SQLite database and its schema."""
    try:
        # Ensure the data directory exists
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        print("Initializing database...")
        
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()

        # Enable WAL mode for better concurrency
        cur.execute("PRAGMA journal_mode=WAL;")
        print("WAL mode enabled.")

        # Create table with the new schema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id TEXT PRIMARY KEY,
                timestamp_lima TEXT NOT NULL,
                cpu_percent REAL NOT NULL,
                ram_percent REAL NOT NULL,
                ram_used_mb REAL NOT NULL,
                disk_percent REAL NOT NULL,
                container_count INTEGER NOT NULL,
                internet_ok INTEGER NOT NULL,
                ping_ms REAL,
                worker_status INTEGER,
                cycle_duration_ms INTEGER,
                services_health TEXT
            )
        """)
        con.commit()
        con.close()
        print("Database is initialized and ready.")
    except sqlite3.Error as e:
        print(f"Database error during initialization: {e}")
        raise

def save_metrics_to_db(metrics):
    """Saves a dictionary of metrics to the SQLite database."""
    try:
        con = sqlite3.connect(DB_FILE, timeout=5)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO metrics (id, timestamp_lima, cpu_percent, ram_percent, ram_used_mb, 
            disk_percent, container_count, internet_ok, ping_ms, worker_status, cycle_duration_ms, services_health)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
            (str(uuid.uuid4()), metrics['timestamp_lima'], metrics['cpu_percent'], metrics['ram_percent'], metrics['ram_used_mb'], 
            metrics['disk_percent'], metrics['container_count'], metrics['internet_ok'], metrics['ping_ms'], 
            metrics['worker_status'], metrics['cycle_duration_ms'], metrics['services_health']))
        con.commit()
        con.close()
    except sqlite3.Error as e:
        print(f"Database error when saving metrics: {e}")
