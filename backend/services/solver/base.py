from __future__ import annotations

from backend.services.solver.models import ScheduleInput, ScheduleResult


class ScheduleSolver:
    engine_name = "base"

    def solve(self, input_data: ScheduleInput) -> ScheduleResult:
        raise NotImplementedError
