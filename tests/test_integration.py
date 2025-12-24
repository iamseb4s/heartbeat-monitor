import pytest
import sqlite3
import requests_mock
from unittest.mock import patch
from main import main
import database

@pytest.fixture(autouse=True)
def mock_environment():
    """
    Mock external dependencies and configuration for all integration tests.
    Patches constants in config, alerts, and database modules to ensure isolation.
    """
    with patch('config.HEARTBEAT_URL', "http://worker.test/heartbeat"), \
         patch('alerts.HEARTBEAT_URL', "http://worker.test/heartbeat"), \
         patch('config.SECRET_KEY', "test-secret"), \
         patch('alerts.SECRET_KEY', "test-secret"), \
         patch('config.N8N_WEBHOOK_URL', "http://n8n.test/webhook"), \
         patch('alerts.N8N_WEBHOOK_URL', "http://n8n.test/webhook"), \
         patch('config.SQLITE_DB_PATH', ":memory:"), \
         patch('network.INTERNAL_DNS_OVERRIDE_IP', None), \
         patch('monitors.get_container_count', return_value=5): 
        yield

def test_integration_full_cycle_with_db(tmp_path):
    """
    Verify a full monitoring cycle: fetching metrics, sending heartbeat, and persisting to DB.
    Uses a temporary SQLite file to verify write operations.
    """
    db_file = tmp_path / "test_metrics.db"
    test_services = {"api": {"url": "http://api.test/health"}}
    
    with requests_mock.Mocker() as m:
        m.head("http://api.test/health", status_code=200)
        m.post("http://worker.test/heartbeat", status_code=200)
        m.head("http://www.google.com", status_code=200)
        
        with patch('time.sleep'), \
             patch('config.SERVICES_TO_CHECK', test_services), \
             patch('database.DB_FILE', db_file): # Patch module-level DB_FILE constant
            
            main(run_once=True)
            
    # Verify DB content
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check global cycle
    cursor.execute("SELECT * FROM monitoring_cycles")
    cycle = cursor.fetchone()
    assert cycle is not None
    assert cycle['internet_status'] == 1
    assert cycle['worker_status'] == 200
    
    # Check individual service detail
    cursor.execute("SELECT * FROM service_checks WHERE cycle_id = ?", (cycle['id'],))
    check = cursor.fetchone()
    assert check is not None
    assert check['service_name'] == 'api'
    assert check['status'] == 'healthy'
    assert check['latency_ms'] is not None
    
    conn.close()

def test_integration_service_failure(tmp_path):
    """
    Verify that service failures are correctly recorded in the database.
    """
    db_file = tmp_path / "test_fail.db"
    test_services = {"api": {"url": "http://api.test/health"}}

    with requests_mock.Mocker() as m:
        m.head("http://api.test/health", status_code=500)
        m.post("http://worker.test/heartbeat", status_code=200)
        m.head("http://www.google.com", status_code=200)
        
        with patch('time.sleep'), \
             patch('config.SERVICES_TO_CHECK', test_services), \
             patch('database.DB_FILE', db_file):
            
            main(run_once=True)
            
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check for specific failure status (HTTP 500 -> 'error')
    cursor.execute("SELECT * FROM service_checks ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    
    assert row is not None
    assert row['service_name'] == 'api'
    assert row['status'] == 'error'
    assert "HTTP 500" in row['error_message']
    
    conn.close()