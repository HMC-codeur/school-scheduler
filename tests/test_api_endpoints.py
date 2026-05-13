import pytest

pytest.importorskip('httpx')
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def test_get_classes_returns_list() -> None:
    response = client.get('/classes')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_post_class_valid_creates_class() -> None:
    response = client.post('/classes', json={'name': '6A', 'max_lessons_per_day': 6})
    assert response.status_code == 200
    assert response.json()['name'] == '6A'


def test_post_class_empty_name_returns_error() -> None:
    response = client.post('/classes', json={'name': '   ', 'max_lessons_per_day': 6})
    assert response.status_code == 422


def test_schedule_load_demo_returns_200() -> None:
    response = client.post('/schedule/load-demo')
    assert response.status_code == 200
    assert 'message' in response.json()


def test_schedule_generate_after_demo_returns_structured_response() -> None:
    client.post('/schedule/load-demo')
    response = client.post('/schedule/generate')
    payload = response.json()
    assert response.status_code == 200
    assert 'success' in payload
    assert 'message' in payload
    assert isinstance(payload.get('schedule', {}), dict)


def test_get_schedule_returns_dictionary() -> None:
    response = client.get('/schedule')
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
