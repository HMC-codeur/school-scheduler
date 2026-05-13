import pytest

pytest.importorskip('httpx')
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def test_generate_without_data_fails_cleanly() -> None:
    response = client.post('/schedule/generate')
    payload = response.json()
    assert response.status_code == 200
    assert payload['success'] is False
    assert isinstance(payload['message'], str)


def test_load_large_demo_and_generate_exposes_metrics() -> None:
    load_response = client.post('/schedule/load-large-demo')
    assert load_response.status_code == 200
    stats = load_response.json().get('stats', {})
    assert stats.get('classes', 0) > 0

    generate_response = client.post('/schedule/generate')
    payload = generate_response.json()
    assert generate_response.status_code == 200
    assert payload['success'] is True
    assert payload.get('required_sessions') is not None
    assert payload.get('scheduled_sessions') is not None
    assert payload.get('generation_time_ms') is not None


def test_clear_resets_schedule() -> None:
    client.post('/schedule/load-demo')
    client.post('/schedule/generate')
    clear_response = client.post('/schedule/clear')
    assert clear_response.status_code == 200

    schedule_response = client.get('/schedule')
    assert schedule_response.status_code == 200
    assert schedule_response.json() == {}
