from __future__ import annotations

import json
import os
from pathlib import Path

from backend.evals.excel.checks import apply_expected_check
from backend.evals.excel.eval_runner import apply_global_gates, build_report, discover_fixture_files, run_eval_suite
from backend.evals.excel.fake_data import detect_fake_availability_lessons, detect_fake_requirements, parse_hours
from backend.evals.excel.readiness import calculate_readiness
from backend.evals.excel.schemas import ExpectedCheck, load_expected_case
from backend.services.imports.excel_mvp.pipeline import analyze_excel_content


def _write_expected(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_expected_json(tmp_path: Path) -> None:
    path = _write_expected(
        tmp_path / "case.json",
        {"case_id": "case", "file_path": "missing.xlsx", "checks": [{"check_id": "fmt", "sheet": "Sheet", "expected_format": "requirements_table"}]},
    )

    case = load_expected_case(path)

    assert case.case_id == "case"
    assert case.checks[0].raw["expected_format"] == "requirements_table"


def test_missing_file_skip_does_not_crash(tmp_path: Path) -> None:
    expected_dir = tmp_path / "expected"
    report_dir = tmp_path / "reports"
    expected_dir.mkdir()
    _write_expected(
        expected_dir / "missing.json",
        {"case_id": "missing", "file_path": "does-not-exist.xlsx", "skip_if_file_missing": True, "checks": [{"check_id": "fmt", "sheet": "Sheet"}]},
    )

    report, _, _ = run_eval_suite(expected_dir=expected_dir, report_dir=report_dir)

    assert report["cases"][0]["status"] == "skipped"
    assert report["cases"][0]["skip_reason"] == "file_missing"


def test_expected_format_pass_and_fail() -> None:
    check = ExpectedCheck("fmt", "Sheet", raw={"check_id": "fmt", "sheet": "Sheet", "expected_format": "requirements_table"})
    sheet = {"sheet_name": "Sheet", "actual_format": "requirements_table", "confidence": 95, "status": "ready", "diagnostic_codes": []}

    assert apply_expected_check(check, sheet)[0]["passed"] is True
    sheet["actual_format"] = "schedule_grid"
    assert apply_expected_check(check, sheet)[0]["passed"] is False


def test_forbidden_format_pass_and_fail() -> None:
    check = ExpectedCheck("forbid", "Sheet", raw={"check_id": "forbid", "sheet": "Sheet", "forbidden_format": "requirements_table"})

    assert apply_expected_check(check, {"sheet_name": "Sheet", "actual_format": "unknown", "confidence": 30, "status": "ignored", "diagnostic_codes": []})[0]["passed"]
    assert not apply_expected_check(check, {"sheet_name": "Sheet", "actual_format": "requirements_table", "confidence": 90, "status": "ready", "diagnostic_codes": []})[0]["passed"]


def test_min_max_count_checks() -> None:
    check = ExpectedCheck("counts", "Sheet", raw={"check_id": "counts", "sheet": "Sheet", "min_requirements": 1, "max_scheduled_lessons": 0})
    sheet = {
        "sheet_name": "Sheet",
        "actual_format": "requirements_table",
        "confidence": 95,
        "status": "ready",
        "requirements_count": 1,
        "scheduled_lessons_count": 0,
        "teacher_availability_count": 0,
        "fake_availability_lessons": [],
        "fake_requirements": [],
        "diagnostic_codes": [],
    }

    assert all(item["passed"] for item in apply_expected_check(check, sheet))


def test_fake_availability_lesson_detection_hebrew() -> None:
    sheet = {"actual_format": "schedule_grid", "extracted_entities": {"scheduled_lessons": [{"subject": "זמין"}]}}

    assert detect_fake_availability_lessons(sheet)[0]["reasons"] == ["subject_is_availability_marker"]


def test_fake_availability_lesson_detection_english() -> None:
    sheet = {"actual_format": "schedule_grid", "extracted_entities": {"scheduled_lessons": [{"subject_name": "available"}]}}

    assert detect_fake_availability_lessons(sheet)


def test_valid_subject_not_fake_availability() -> None:
    sheet = {"actual_format": "schedule_grid", "extracted_entities": {"scheduled_lessons": [{"subject": "Mathematics"}]}}

    assert detect_fake_availability_lessons(sheet) == []


def test_fake_requirement_without_hours_detected() -> None:
    sheet = {
        "sheet_name": "constraints",
        "actual_format": "requirements_table",
        "extracted_entities": {"requirements": [{"class_name": "7A", "subject_name": "Math", "teacher_name": "Cohen", "weekly_hours_raw": "yes"}]},
    }

    fake = detect_fake_requirements(sheet)

    assert "hours_not_parseable" in fake[0]["reasons"]
    assert parse_hours("5 שעות") == 5
    assert parse_hours("three") is None


def test_valid_requirement_not_fake() -> None:
    sheet = {
        "sheet_name": "requirements",
        "actual_format": "requirements_table",
        "extracted_entities": {"requirements": [{"class_name": "7A", "subject_name": "Math", "teacher_name": "Cohen", "weekly_hours": 4}]},
    }

    assert detect_fake_requirements(sheet) == []


def test_readiness_capped_by_fake_data_gate() -> None:
    gates = [{"id": "no_availability_markers_as_lessons", "severity": "blocking", "passed": False}]

    readiness = calculate_readiness([{"status": "passed", "synthetic": False, "checks": [], "sheets": []}], gates)

    assert readiness["score"] <= 40
    assert readiness["recommendation"] == "not_ready"


def test_blocking_gate_makes_report_failed() -> None:
    report = build_report(
        "v2",
        [{"case_id": "case", "status": "passed", "checks": []}],
        [{"id": "gate", "severity": "blocking", "passed": False, "message": "failed"}],
        {"score": 30, "recommendation": "not_ready", "dimensions": {}, "caps_applied": [], "explanation": ""},
        [],
    )

    assert report["status"] == "failed"


def test_markdown_and_json_reports_generated(tmp_path: Path) -> None:
    expected_dir = tmp_path / "expected"
    report_dir = tmp_path / "reports"
    expected_dir.mkdir()
    _write_expected(
        expected_dir / "synthetic.json",
        {
            "case_id": "synthetic_core",
            "file_path": str(tmp_path / "generated.xlsx"),
            "synthetic": True,
            "skip_if_file_missing": False,
            "checks": [{"check_id": "synthetic_requirements", "sheet": "synthetic_requirements", "expected_format": "requirements_table", "min_requirements": 1}],
        },
    )

    report, json_path, md_path = run_eval_suite(expected_dir=expected_dir, report_dir=report_dir)

    assert report["status"] == "passed"
    assert json_path.exists()
    assert md_path.exists()


def test_runner_can_run_synthetic_case(tmp_path: Path) -> None:
    report, _, _ = run_eval_suite(expected_dir=Path("backend/evals/excel/expected"), report_dir=tmp_path / "reports", case_id="synthetic_core")

    assert report["status"] == "passed"
    assert report["summary"]["passed_checks"] > 0
    assert report["gates"][9]["id"] == "v2_engine_used_in_eval"


def test_discover_fixture_files_ignores_manifest_and_finds_xlsx(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    nested = fixtures / "nested"
    nested.mkdir(parents=True)
    (fixtures / "00_MANIFEST_pack_tests_v2.xlsx").write_bytes(b"manifest")
    (fixtures / "01_planning.xlsx").write_bytes(b"one")
    (nested / "02_besoins.xlsx").write_bytes(b"two")
    (nested / "notes.txt").write_text("ignore", encoding="utf-8")

    files = discover_fixture_files(fixtures)

    assert [path.name for path in files] == ["01_planning.xlsx", "02_besoins.xlsx"]


def test_runner_preserves_v1_default_after_forcing_v2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EXCEL_INTELLIGENCE_MODE", raising=False)

    report, _, _ = run_eval_suite(expected_dir=Path("backend/evals/excel/expected"), report_dir=tmp_path / "reports", case_id="synthetic_core")
    result = analyze_excel_content(_tiny_workbook(), filename="default.xlsx")

    assert report["status"] == "passed"
    assert os.getenv("EXCEL_INTELLIGENCE_MODE") is None
    assert result["engine_used"] == "v1"


def test_global_gate_detects_fake_lesson() -> None:
    cases = [
        {
            "case_id": "bad",
            "status": "passed",
            "engine_used": "v2",
            "sheets": [
                {
                    "sheet_name": "availability",
                    "actual_format": "availability_grid",
                    "scheduled_lessons_count": 1,
                    "fake_availability_lessons": [{"lesson": {"subject": "yes"}, "reasons": ["subject_is_availability_marker"]}],
                    "fake_requirements": [],
                }
            ],
        }
    ]

    gates = apply_global_gates(cases, engine="v2")

    assert next(gate for gate in gates if gate["id"] == "no_availability_markers_as_lessons")["passed"] is False


def _tiny_workbook() -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["class", "subject", "teacher", "hours"])
    sheet.append(["7A", "Math", "Cohen", 4])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
