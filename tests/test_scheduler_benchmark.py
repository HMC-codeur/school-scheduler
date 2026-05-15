from backend.benchmarks.scheduler_benchmark import run_benchmarks


def test_small_scheduler_benchmark_creates_report(tmp_path) -> None:
    output = tmp_path / "scheduler_benchmark_latest.json"

    report = run_benchmarks(["small"], output_path=output)

    assert output.exists()
    assert "generated_at" in report
    assert report["thresholds_enforced"] is False
    assert len(report["results"]) == 1

    result = report["results"][0]
    required_fields = {
        "dataset",
        "success",
        "total_time_ms",
        "dataset_build_time_ms",
        "generation_time_ms",
        "options_time_ms",
        "scoring_time_ms",
        "diagnostics_time_ms",
        "phase_times_ms",
        "required_sessions",
        "scheduled_sessions",
        "placement_rate",
        "conflicts_count",
        "options_generated",
        "average_score",
        "score_min",
        "score_max",
        "penalty_summary",
        "penalty_counts",
        "class_gaps_count",
        "teacher_gaps_count",
        "long_sequences_count",
        "top_penalty_categories",
        "memory_peak_kb",
        "threshold_ms",
        "threshold_exceeded",
    }
    assert required_fields <= set(result)
    assert result["dataset"] == "small"
    assert result["required_sessions"] > 0
    assert result["scheduled_sessions"] == result["required_sessions"]
    assert result["conflicts_count"] == 0
    assert result["total_time_ms"] >= 0
    assert result["memory_peak_kb"] >= 0
    assert result["average_score"] is not None
    assert result["average_score"] >= 42
    assert isinstance(result["penalty_summary"], list)
    assert result["top_penalty_categories"] == result["penalty_summary"][:5]
    assert result["placement_rate"] == 100
    assert set(result["phase_times_ms"]) >= {"dataset_build", "single_generation", "multiple_options", "external_scoring", "diagnostics"}
    assert result["diagnostics_time_ms"] is not None
    assert "comparison" in report
    assert "analysis" in report
