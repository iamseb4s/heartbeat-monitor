import pytest
from unittest.mock import MagicMock, patch
import monitors
import docker

def test_check_one_service_docker_running():
    """Verify that a running container is reported as healthy."""
    service_name = "db"
    service_config = {"url": "docker:my-db"}
    services_global = {}
    
    mock_container = MagicMock()
    mock_container.status = 'running'
    
    with patch('monitors.docker_client') as mock_client:
        mock_client.containers.get.return_value = mock_container
        
        name, result = monitors._check_one_service(service_name, service_config, services_global)
        
        assert name == service_name
        assert result['status'] == 'healthy'
        assert result['error'] is None

def test_check_one_service_docker_stopped():
    """Verify that a stopped container is reported as down."""
    service_name = "db"
    service_config = {"url": "docker:my-db"}
    services_global = {}
    
    mock_container = MagicMock()
    mock_container.status = 'exited'
    
    with patch('monitors.docker_client') as mock_client:
        mock_client.containers.get.return_value = mock_container
        
        name, result = monitors._check_one_service(service_name, service_config, services_global)
        
        assert result['status'] == 'down'
        assert "Container state: exited" in result['error']

def test_check_one_service_docker_not_found():
    """Verify that a missing container is reported as down."""
    service_name = "db"
    service_config = {"url": "docker:ghost-container"}
    services_global = {}
    
    with patch('monitors.docker_client') as mock_client:
        mock_client.containers.get.side_effect = docker.errors.NotFound("Not found")
        
        name, result = monitors._check_one_service(service_name, service_config, services_global)
        
        assert result['status'] == 'down'
        assert result['error'] == "Container not found"

def test_get_system_metrics():
    """Verify that system metrics collection returns expected structure and types."""
    with patch('psutil.cpu_percent', return_value=10.5), \
         patch('psutil.virtual_memory') as mock_ram, \
         patch('psutil.disk_usage') as mock_disk:
        
        mock_ram.return_value.percent = 50.0
        mock_ram.return_value.used = 1024 * 1024 * 512 # 512 MB
        mock_disk.return_value.percent = 20.0
        
        metrics = monitors.get_system_metrics()
        
        assert metrics['cpu_percent'] == 10.5
        assert metrics['ram_percent'] == 50.0
        assert metrics['ram_used_mb'] == 512.0
        assert metrics['disk_percent'] == 20.0