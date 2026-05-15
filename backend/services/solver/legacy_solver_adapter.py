from __future__ import annotations

from backend.models.schemas import ScheduleCell
from backend.services.scheduler import SchedulerService
from backend.services.solver.base import ScheduleSolver
from backend.services.solver.models import ScheduleInput, ScheduleResult, SolverAssignment, SolverMetrics
from backend.services.solver.stability import schedule_to_assignments, schedule_with_session_ids


class LegacySolverAdapter(ScheduleSolver):
    engine_name = "legacy"

    def solve(self, input_data: ScheduleInput) -> ScheduleResult:
        result = SchedulerService.generate(
            input_data.classes,
            input_data.teachers,
            input_data.subjects,
            input_data.slots,
            input_data.conditions,
        )
        schedule = schedule_with_session_ids(result.schedule)
        assignments = schedule_to_assignments(schedule)
        class_conflicts, teacher_conflicts = _count_basic_conflicts(schedule)
        hard_conflicts = int(result.conflicts_count or (class_conflicts + teacher_conflicts))
        required_sessions = int(result.required_sessions or _required_sessions(input_data))
        scheduled_sessions = int(result.scheduled_sessions if result.scheduled_sessions is not None else len(assignments))
        metrics = SolverMetrics(
            engine=self.engine_name,
            success=result.success,
            required_sessions=required_sessions,
            scheduled_sessions=scheduled_sessions,
            generation_time_ms=int(result.generation_time_ms or 0),
            hard_conflicts=hard_conflicts,
            class_conflicts=class_conflicts,
            teacher_conflicts=teacher_conflicts,
            unplaced_sessions=max(0, required_sessions - scheduled_sessions),
            quality_score=result.quality_score,
        )
        return ScheduleResult(
            success=result.success,
            message=result.message,
            schedule=schedule,
            assignments=assignments,
            metrics=metrics,
        )


def _required_sessions(input_data: ScheduleInput) -> int:
    return len(input_data.classes) * sum(max(0, subject.hours_per_week) for subject in input_data.subjects)


def _count_basic_conflicts(schedule: dict[str, dict[str, ScheduleCell]]) -> tuple[int, int]:
    class_conflicts = 0
    teacher_slot_use: dict[tuple[str, str], int] = {}
    for slot, entries in schedule.items():
        class_conflicts += max(0, len(entries) - len(set(entries)))
        for cell in entries.values():
            key = (cell.teacher, slot)
            teacher_slot_use[key] = teacher_slot_use.get(key, 0) + 1
    teacher_conflicts = sum(max(0, count - 1) for count in teacher_slot_use.values())
    return class_conflicts, teacher_conflicts
