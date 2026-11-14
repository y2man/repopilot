from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
def test_health_returns_dependency_state():
    response = client.get('/health')
    assert response.status_code == 200
    body = response.json()
    assert body['status'] in {'ok','degraded'}
    assert body['service'] == 'repopilot-api'
    assert 'database' in body and 'ai_configured' in body


def test_request_id_is_echoed_for_log_correlation():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        response = client.get('/health', headers={'X-Request-ID':'client-request-1234'})
        assert response.status_code == 200
        assert response.headers['X-Request-ID'] == 'client-request-1234'


def test_prometheus_metrics_capture_route_count_and_duration():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        client.get('/health')
        response = client.get('/metrics')
        assert response.status_code == 200
        assert 'repopilot_http_requests_total' in response.text
        assert 'route="/health"' in response.text
        assert 'repopilot_http_request_duration_seconds_bucket' in response.text
