from time import perf_counter

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


def test_load_pilot_demo_generate_options_and_diagnostics_are_stable() -> None:
    load_response = client.post('/schedule/load-pilot-demo')
    assert load_response.status_code == 200
    stats = load_response.json().get('stats', {})
    assert 10 <= stats.get('classes', 0) <= 20
    assert stats.get('teachers', 0) >= 20
    assert stats.get('conditions', 0) >= 8

    diagnosis = client.get('/schedule/diagnose').json()
    assert diagnosis["can_generate"] is True
    assert diagnosis["stats"]["classes"] == stats["classes"]
    assert diagnosis["stats"]["required_sessions"] > 0

    started_at = perf_counter()
    generate_response = client.post('/schedule/generate')
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    payload = generate_response.json()
    assert generate_response.status_code == 200
    assert payload["success"] is True
    assert payload["quality_score"] is not None
    assert payload["conflicts_count"] == 0
    assert payload["scheduled_sessions"] == payload["required_sessions"]
    assert payload["generation_time_ms"] is not None
    assert elapsed_ms < 60_000

    options = client.get('/schedule/options').json()
    assert 1 <= len(options) <= 3
    assert all(option.get("quality_score") is not None for option in options)
    assert any(option.get("selected") for option in options)


def test_clear_resets_schedule() -> None:
    client.post('/schedule/load-demo')
    client.post('/schedule/generate')
    clear_response = client.post('/schedule/clear')
    assert clear_response.status_code == 200

    schedule_response = client.get('/schedule')
    assert schedule_response.status_code == 200
    assert schedule_response.json() == {}


def test_generated_options_are_scored_and_sorted() -> None:
    client.post('/schedule/load-demo')
    generate_response = client.post('/schedule/generate')
    assert generate_response.status_code == 200
    assert generate_response.json().get("success") is True

    options_response = client.get('/schedule/options')
    options = options_response.json()
    assert options_response.status_code == 200
    assert 1 <= len(options) <= 3

    scores = [option.get("quality_score") for option in options]
    assert all(isinstance(score, int) for score in scores)
    assert scores == sorted(scores, reverse=True)

    selected = [option for option in options if option.get("selected")]
    assert len(selected) == 1
    assert selected[0]["id"] == options[0]["id"]

    for option in options:
        assert isinstance(option.get("schedule"), dict)
        assert isinstance(option.get("score_breakdown"), list)
        signature = option.get("schedule_signature")
        assert isinstance(signature, str) and len(signature) == 8


def test_generate_response_matches_selected_option_metrics() -> None:
    client.post('/schedule/load-demo')
    generate_payload = client.post('/schedule/generate').json()
    selected_option = next(option for option in client.get('/schedule/options').json() if option.get("selected"))

    assert generate_payload["quality_score"] == selected_option["quality_score"]
    assert generate_payload["score_breakdown"] == selected_option["score_breakdown"]
    assert generate_payload["conflicts_count"] == selected_option["conflicts_count"]
    assert generate_payload["gaps_count"] == selected_option["gaps_count"]
    assert isinstance(generate_payload["generation_time_ms"], int)


def test_option_signatures_reflect_schedule_content() -> None:
    client.post('/schedule/load-demo')
    client.post('/schedule/generate')
    options = client.get('/schedule/options').json()
    signatures = {option["schedule_signature"] for option in options}
    if len(signatures) > 1:
        assert len(signatures) == len(options)
