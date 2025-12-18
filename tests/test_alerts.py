import pytest
from unittest.mock import MagicMock, patch
import alerts
import config

@pytest.fixture(autouse=True)
def reset_global_states():
    """Clear global state dictionary before each test execution."""
    alerts.global_states.clear()

def test_check_state_change_transient_failure():
    """Verify that state changes below the threshold do not trigger notifications."""
    service_name = "test_service"
    
    # Initialize as healthy
    alerts.global_states[service_name] = {
        'last_stable_status': 'healthy',
        'transient_status': 'healthy',
        'transient_counter': 0
    }
    
    with patch('alerts.STATUS_CHANGE_THRESHOLD', 3): 
        # First failure: should increment counter but return no action
        action, old_status, _ = alerts.check_state_change(service_name, 'unhealthy', ['healthy'])
        
        assert action is None
        assert alerts.global_states[service_name]['transient_counter'] == 1
        assert alerts.global_states[service_name]['last_stable_status'] == 'healthy' 

def test_check_state_change_confirmed_failure():
    """Verify that state changes reaching the threshold trigger a failure notification."""
    service_name = "test_service"
    
    alerts.global_states[service_name] = {
        'last_stable_status': 'healthy',
        'transient_status': 'healthy',
        'transient_counter': 0
    }
    
    with patch('alerts.STATUS_CHANGE_THRESHOLD', 3):
        # Sequence of failures leading to threshold
        alerts.check_state_change(service_name, 'unhealthy', ['healthy'])
        alerts.check_state_change(service_name, 'unhealthy', ['healthy'])
        action, old_status, _ = alerts.check_state_change(service_name, 'unhealthy', ['healthy'])
        
        assert action == 'NOTIFY_DOWN'
        assert old_status == 'healthy'
        assert alerts.global_states[service_name]['last_stable_status'] == 'unhealthy'
        assert alerts.global_states[service_name]['transient_counter'] == 3

def test_immediate_recovery():
    """Verify that transitioning to an immediate notify status triggers recovery instantly."""
    service_name = "test_service"
    
    alerts.global_states[service_name] = {
        'last_stable_status': 'unhealthy',
        'transient_status': 'unhealthy',
        'transient_counter': 3
    }
    
    with patch('alerts.STATUS_CHANGE_THRESHOLD', 3):
        # Recovery triggered on first success
        action, old_status, _ = alerts.check_state_change(service_name, 'healthy', ['healthy'])
        
        assert action == 'NOTIFY_RECOVERY'
        assert old_status == 'unhealthy'
        assert alerts.global_states[service_name]['last_stable_status'] == 'healthy'
