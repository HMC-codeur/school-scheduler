from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher
from backend.services.scheduler import ScheduleResult
from backend.services.scheduler_v2 import FastValidScheduler
from backend.services.scoring import analyze_schedule, score_schedule


def _assert_hard_valid(result, classes, teachers, subjects, slots, conditions=None):
    metrics = analyze_schedule(result.schedule, classes, teachers, subjects, slots, conditions or [])
    assert result.success is True
    assert result.scheduled_sessions == result.required_sessions
    assert result.conflicts_count == 0
    assert metrics["teacher_conflicts"] == 0
    assert metrics["class_conflicts"] == 0
    assert metrics["incompatible_assignments"] == 0
    assert metrics["unplaced_sessions"] == 0
    assert metrics["overloaded_days"] == 0
    assert metrics["teacher_overload"] == 0


def _session_count(schedule):
    return sum(len(entries) for entries in schedule.values())


def test_v2_fast_valid_builds_complete_small_schedule():
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=2), Subject(name="English", hours_per_week=1)]
    teachers = [
        Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=3),
        Teacher(id=2, name="T2", subjects=["English"], max_lessons_per_day=3),
        Teacher(id=3, name="T3", subjects=["Math", "English"], max_lessons_per_day=3),
    ]
    slots = ["Mon-08:00", "Mon-09:00", "Tue-08:00", "Tue-09:00"]

    result = FastValidScheduler.generate(classes, teachers, subjects, slots, fallback_to_current=False)

    _assert_hard_valid(result, classes, teachers, subjects, slots)
    assert result.quality_score is None


def test_v2_fast_valid_respects_hard_unavailability_and_daily_limits():
    classes = [Class(id=1, name="A", max_lessons_per_day=1)]
    subjects = [Subject(name="Math", hours_per_week=2)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], unavailable_slots=["Mon-08:00"], max_lessons_per_day=1)]
    slots = ["Mon-08:00", "Mon-09:00", "Tue-08:00", "Tue-09:00"]
    conditions = [
        Condition(id=1, text="class blocked", condition_type="class_unavailable", class_name="A", slot="Tue-08:00")
    ]

    result = FastValidScheduler.generate(classes, teachers, subjects, slots, conditions, fallback_to_current=False)

    _assert_hard_valid(result, classes, teachers, subjects, slots, conditions)
    assert "Mon-08:00" not in result.schedule
    assert "Tue-08:00" not in result.schedule


def test_v2_falls_back_to_current_scheduler_when_experiment_fails(monkeypatch):
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00"]

    def fail_fast_valid(*args, **kwargs):
        return ScheduleResult(
            False,
            "forced v2 failure",
            {},
            required_sessions=1,
            scheduled_sessions=0,
            generation_time_ms=0,
        )

    monkeypatch.setattr(FastValidScheduler, "build_fast_valid", fail_fast_valid)

    result = FastValidScheduler.generate(classes, teachers, subjects, slots)

    assert result.success is True
    assert result.scheduled_sessions == result.required_sessions
    assert "fallback used" in result.message


def test_v2_candidate_priority_keeps_simple_schedule_valid_and_compact():
    classes = [Class(id=1, name="A", max_lessons_per_day=4)]
    subjects = [Subject(name="Math", hours_per_week=3)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=4)]
    slots = ["Mon-08:00", "Mon-09:00", "Mon-10:00", "Mon-11:00"]

    result = FastValidScheduler.generate(classes, teachers, subjects, slots, fallback_to_current=False)
    metrics = analyze_schedule(result.schedule, classes, teachers, subjects, slots)

    _assert_hard_valid(result, classes, teachers, subjects, slots)
    assert metrics["empty_gaps"] == 0


def test_v2_phase_b_keeps_hard_validity_and_session_count():
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=2), Subject(name="English", hours_per_week=1)]
    teachers = [
        Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=3),
        Teacher(id=2, name="T2", subjects=["English"], max_lessons_per_day=3),
        Teacher(id=3, name="T3", subjects=["Math", "English"], max_lessons_per_day=3),
    ]
    slots = ["Mon-08:00", "Mon-09:00", "Tue-08:00", "Tue-09:00"]
    phase_a = FastValidScheduler.generate(classes, teachers, subjects, slots, fallback_to_current=False)
    before_score = score_schedule(phase_a.schedule, classes, teachers, subjects, slots)["quality_score"]

    optimized = FastValidScheduler.optimize_quality(phase_a.schedule, classes, teachers, subjects, slots)
    after_score = score_schedule(optimized.schedule, classes, teachers, subjects, slots)["quality_score"]
    metrics = analyze_schedule(optimized.schedule, classes, teachers, subjects, slots)

    assert _session_count(optimized.schedule) == phase_a.scheduled_sessions
    assert metrics["teacher_conflicts"] == 0
    assert metrics["class_conflicts"] == 0
    assert metrics["incompatible_assignments"] == 0
    assert metrics["unplaced_sessions"] == 0
    assert after_score >= before_score


def test_v2_phase_b_improves_simple_gap_without_lowering_score():
    classes = [Class(id=1, name="A", max_lessons_per_day=3)]
    subjects = [Subject(name="Math", hours_per_week=2)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=3)]
    slots = ["Mon-08:00", "Mon-09:00", "Mon-10:00"]
    schedule = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Mon-10:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
    }
    before = score_schedule(schedule, classes, teachers, subjects, slots)

    optimized = FastValidScheduler.optimize_quality(schedule, classes, teachers, subjects, slots)
    after = score_schedule(optimized.schedule, classes, teachers, subjects, slots)

    assert optimized.moves_accepted >= 1
    assert optimized.penalty_after < optimized.penalty_before
    assert after["quality_score"] >= before["quality_score"]
    assert after["metrics"]["empty_gaps"] == 0
    assert _session_count(optimized.schedule) == _session_count(schedule)
