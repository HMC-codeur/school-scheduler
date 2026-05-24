from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app
from backend.services.imports.intelligence import analyze_import_content
from backend.services.imports.intelligence.orchestrator import clear_import_drafts


FIXTURES = Path(__file__).parent / "fixtures" / "imports"
client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()
    clear_import_drafts()


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def analyze(name: str) -> dict:
    return analyze_import_content(fixture(name), filename=name)


def test_format_detection_xlsx() -> None:
    assert analyze("simple_requirements.xlsx")["file_type"] == "xlsx"


def test_format_detection_csv() -> None:
    payload = analyze("requirements.csv")
    assert payload["file_type"] == "csv"
    assert payload["summary"]["requirements_count"] >= 1


def test_unsupported_pdf_returns_clean_diagnostic() -> None:
    payload = analyze("unsupported_fake.pdf")
    assert payload["status"] == "blocked"
    assert payload["file_type"] == "pdf"
    assert any(item["code"] == "unsupported_for_now" for item in payload["diagnostics"])


def test_workbook_profile_detects_sheets() -> None:
    payload = analyze("mixed_school_file.xlsx")
    assert payload["summary"]["sheets_count"] >= 5
    assert any(item["sheet_name"] == "Besoins" for item in payload["sheet_profiles"])


def test_sheet_classification_requirements() -> None:
    payload = analyze("simple_requirements.xlsx")
    assert payload["sheet_classifications"][0]["sheet_type"] == "requirements_table"


def test_sheet_classification_schedule_grid() -> None:
    payload = analyze("schedule_grid_fr.xlsx")
    assert payload["sheet_classifications"][0]["sheet_type"] == "schedule_grid"


def test_sheet_classification_availability_hebrew() -> None:
    payload = analyze("teacher_availability_he.xlsx")
    assert payload["sheet_classifications"][0]["sheet_type"] == "teacher_availability"


def test_metadata_sheet_is_ignored() -> None:
    payload = analyze("metadata_only.xlsx")
    assert payload["sheet_classifications"][0]["sheet_type"] in {"metadata", "unknown_review"}
    assert payload["summary"]["requirements_count"] == 0


def test_mixed_sheet_needs_review() -> None:
    payload = analyze("mixed_school_file.xlsx")
    assert any(item["needs_human_review"] for item in payload["sheet_classifications"])


def test_header_detection_french() -> None:
    payload = analyze("simple_requirements.xlsx")
    headers = payload["brain_results"][4]["data"]["headers"]
    assert {"class_name", "teacher_name", "subject_name", "weekly_hours"}.issubset(set(headers[0]["roles"]))


def test_header_detection_hebrew() -> None:
    payload = analyze("teacher_availability_he.xlsx")
    headers = payload["brain_results"][4]["data"]["headers"]
    assert {"teacher_name", "day", "time", "availability"}.issubset(set(headers[0]["roles"]))


def test_semantic_detection_classes_teachers_subjects() -> None:
    payload = analyze("simple_requirements.xlsx")
    preview = payload["normalized_preview"]
    assert {item["name"] for item in preview["classes"]} == {"6eA", "6eB"}
    assert any(item["name"] == "Mme Cohen" for item in preview["teachers"])
    assert any(item["name"] == "Mathématiques" for item in preview["subjects"])


def test_normalization_output_shape() -> None:
    payload = analyze("simple_requirements.xlsx")
    assert set(payload["normalized_preview"]) == {"classes", "teachers", "subjects", "requirements", "constraints", "availability", "schedule_grid_preview", "lesson_candidates", "source_trace"}


def test_schedule_grid_preview_extracts_lesson_candidates() -> None:
    response = client.post(
        "/imports/analyze",
        files={"file": ("generic_school_grid.xlsx", fixture("schedule_grid_fr.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    payload = response.json()
    preview = payload["normalized_preview"]
    candidates = preview["schedule_grid_preview"] or preview["lesson_candidates"]
    assert candidates
    assert payload["status"] == "needs_review"
    assert payload["can_apply"] is False
    assert payload["can_commit"] is False
    assert payload["needs_human_review"] is True
    assert not any(item["code"] == "no_importable_data" for item in payload["diagnostics"])
    assert {"schedule_grid_detected", "schedule_grid_preview_only", "schedule_grid_requires_confirmation"}.issubset({item["code"] for item in payload["diagnostics"]})
    first = candidates[0]
    assert {"class_name", "day", "time", "raw_cell", "subject", "teacher", "confidence", "source_trace"}.issubset(first)
    assert first["source_trace"]["sheet"]
    assert first["source_trace"]["row"] is not None
    assert first["source_trace"]["column"] is not None


def test_schedule_grid_preview_is_not_filename_hardcoded() -> None:
    original = client.post(
        "/imports/analyze",
        files={"file": ("schedule_grid_fr.xlsx", fixture("schedule_grid_fr.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    renamed = client.post(
        "/imports/analyze",
        files={"file": ("renamed_fixture.xlsx", fixture("schedule_grid_fr.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    assert len(original["normalized_preview"]["schedule_grid_preview"]) == len(renamed["normalized_preview"]["schedule_grid_preview"])
    assert renamed["normalized_preview"]["schedule_grid_preview"]


def test_validation_detects_missing_teacher() -> None:
    payload = analyze("messy_semicolon.csv")
    assert any(item["code"] == "missing_teacher" for item in payload["diagnostics"])


def test_duplicate_resolution() -> None:
    payload = analyze("messy_requirements.xlsx")
    subjects = {item["name"] for item in payload["normalized_preview"]["subjects"]}
    assert "Mathématiques" in subjects
    assert "Maths" not in subjects


def test_human_review_items_are_prioritized() -> None:
    payload = analyze("messy_semicolon.csv")
    assert payload["human_review"]
    assert all("question" in item for item in payload["human_review"])


def test_import_does_not_crash_on_empty_file() -> None:
    payload = analyze("invalid_empty.xlsx")
    assert payload["status"] in {"blocked", "needs_review", "ok"}
    assert "diagnostics" in payload


def test_analyze_endpoint_returns_stable_contract() -> None:
    response = client.post(
        "/imports/analyze",
        files={"file": ("simple_requirements.xlsx", fixture("simple_requirements.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert {"import_id", "status", "file_type", "confidence", "summary", "sheet_profiles", "sheet_classifications", "normalized_preview", "diagnostics", "human_review"}.issubset(payload)


def test_analyze_endpoint_rejects_missing_file_without_405() -> None:
    response = client.post("/imports/analyze")
    assert response.status_code == 422


def test_import_route_table_registers_expected_methods() -> None:
    routes = {
        (path, tuple(sorted(methods or [])))
        for route in app.routes
        for path, methods in [(getattr(route, "path", None), getattr(route, "methods", None))]
        if path and path.startswith("/imports")
    }
    assert ("/imports/analyze", ("POST",)) in routes
    assert ("/imports/{import_id}", ("GET",)) in routes
    assert ("/imports/{import_id}/confirm", ("POST",)) in routes
    assert ("/imports/{import_id}/apply", ("POST",)) in routes
    assert ("/imports/excel/analyze", ("POST",)) in routes


def test_apply_import_does_not_corrupt_existing_data() -> None:
    store = get_store()
    store.add_class("Existing")
    response = client.post(
        "/imports/analyze",
        files={"file": ("simple_requirements.xlsx", fixture("simple_requirements.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    import_id = response.json()["import_id"]
    apply_response = client.post(f"/imports/{import_id}/apply")
    assert apply_response.status_code == 200
    assert any(item.name == "Existing" for item in store.classes)


def test_old_import_mode_still_works() -> None:
    response = client.post(
        "/imports/excel/analyze",
        files={"file": ("simple_requirements.xlsx", fixture("simple_requirements.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    assert response.json()["engine_used"] == "v1"
