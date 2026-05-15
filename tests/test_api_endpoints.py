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


def test_post_class_duplicate_name_returns_error() -> None:
    client.post('/classes', json={'name': '6A', 'max_lessons_per_day': 6})
    response = client.post('/classes', json={'name': '6A', 'max_lessons_per_day': 6})
    assert response.status_code == 400


def test_post_class_empty_name_returns_error() -> None:
    response = client.post('/classes', json={'name': '   ', 'max_lessons_per_day': 6})
    assert response.status_code == 422


def test_slot_format_is_strict() -> None:
    response = client.post('/slots', json={'slot': 'Mon-8'})
    assert response.status_code == 422


def test_time_settings_reject_zero_generated_slots() -> None:
    response = client.post(
        '/time-settings',
        json={
            'day_start_time': '08:00',
            'day_end_time': '08:30',
            'lesson_duration_minutes': 60,
            'break_duration_minutes': 0,
            'working_days': ['Mon'],
        },
    )
    assert response.status_code == 400


def test_condition_rejects_unknown_targets() -> None:
    client.post('/classes', json={'name': '6A', 'max_lessons_per_day': 6})
    client.post('/subjects', json={'name': 'Math', 'hours_per_week': 1})
    client.post('/teachers', json={'name': 'Mme A', 'subjects': ['Math'], 'max_lessons_per_day': 6})
    client.post('/slots', json={'slot': 'Mon-08:00'})

    response = client.post(
        '/conditions',
        json={
            'text': 'Unknown teacher unavailable',
            'condition_type': 'teacher_unavailable',
            'teacher_name': 'Unknown',
            'slot': 'Mon-08:00',
        },
    )
    assert response.status_code == 400


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
