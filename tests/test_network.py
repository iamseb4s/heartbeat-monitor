import pytest
import requests_mock
from network import smart_request

def test_smart_request_no_override():
    """Verify that a request is made normally when no DNS override is configured."""
    url = "https://api.example.com/health"
    services = {"api": {"url": url}}
    
    with requests_mock.Mocker() as m:
        m.get(url, text="ok")
        
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("network.INTERNAL_DNS_OVERRIDE_IP", None)
            response = smart_request('GET', url, services)
            
            assert response.text == "ok"
            assert m.called
            assert m.request_history[0].url == url
            assert 'Host' not in m.request_history[0].headers

def test_smart_request_with_dns_override():
    """Verify that DNS override correctly replaces hostname with IP and sets Host header."""
    original_url = "https://service.local/status"
    override_ip = "192.168.1.10"
    services = {"my_service": {"url": original_url}}
    
    # Expected rewritten URL: https -> http and hostname -> IP
    expected_url = "http://192.168.1.10/status"
    
    with requests_mock.Mocker() as m:
        m.get(expected_url, text="overridden")
        
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("network.INTERNAL_DNS_OVERRIDE_IP", override_ip)
            response = smart_request('GET', original_url, services)
            
            assert response.text == "overridden"
            assert m.called
            
            last_request = m.request_history[0]
            assert last_request.url == expected_url
            assert last_request.headers['Host'] == "service.local"

def test_smart_request_with_unmatched_service():
    """Verify that DNS override is NOT applied if the hostname does not match a monitored service."""
    # Use a path to avoid trailing slash ambiguity
    url = "https://google.com/search"
    override_ip = "1.1.1.1"
    services = {"app": {"url": "https://myapp.internal/health"}}
    
    with requests_mock.Mocker() as m:
        m.get(url, text="public")
        
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("network.INTERNAL_DNS_OVERRIDE_IP", override_ip)
            response = smart_request('GET', url, services)
            
            assert response.text == "public"
            assert m.request_history[0].url == url
            assert 'Host' not in m.request_history[0].headers
