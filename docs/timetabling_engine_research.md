# Timetabling engine research

This document summarizes reusable ideas from mature timetabling and constraint-solving systems for the current `school-scheduler` OR-Tools engine. It is intentionally implementation-oriented: the goal is to improve our isolated solver while keeping the legacy engine, frontend, and persistence untouched.

## Source systems

### Google OR-Tools Scheduling / CP-SAT

Sources:
- https://developers.google.com/optimization/scheduling
- https://developers.google.com/optimization/cp/cp_tasks

OR-Tools provides CP-SAT modeling primitives for hard feasibility and weighted optimization. It is best when the problem can be represented with compact Boolean/integer variables, strong domain reduction, and a clear objective. Solver limits such as `max_time_in_seconds` are first-class and should be part of every production-style run.

Strengths:
- Precise hard constraints.
- Weighted objectives for soft constraints.
- Deterministic, inspectable CP-SAT status and search statistics.
- Good fit for domain-reduced school scheduling.

Limits:
- Model size grows quickly if every teacher/slot/session combination is represented.
- Multi-objective behavior must be modeled through weighted penalties.
- Explanations are not automatic; they must be computed after solving.

Reusable lessons:
- Keep hard constraints absolute.
- Precompute domains before creating variables.
- Export solver statistics: variables, branches, conflicts, wall time, status.
- Use separate strategy weights instead of changing constraint semantics.

### Timefold School Timetabling

Source:
- https://docs.timefold.ai/timefold-solver/latest/quickstart/shared/school-timetabling/school-timetabling-quickstart

Timefold models timetabling as planning entities with planning variables, scored by constraints. Its main conceptual contribution for us is a clean separation between hard and soft score, plus multiple explainable constraints instead of one opaque quality number.

Strengths:
- Hard/soft score model.
- Constraint-focused architecture.
- Good fit for explainable optimization.
- Practical pattern for comparing schedules by score.

Limits:
- JVM ecosystem, not directly reusable in this Python/FastAPI stack.
- Metaheuristic approach differs from CP-SAT modeling.

Reusable lessons:
- Keep each scoring concern named and measurable.
- Make weights explicit.
- Treat explainability as a product feature, not a debug afterthought.

### OptaPlanner School / Course Timetabling

Sources:
- https://optaplanner.io/learn/useCases/schoolTimetabling
- https://www.optaplanner.org/docs/optaplanner/latest/use-cases-and-examples/course-timetabling/course-timetabling.html

OptaPlanner emphasizes constraints such as teacher conflicts, room occupancy, unavailable periods, minimum working days, curriculum compactness, and room stability. Its score model separates infeasible schedules from feasible-but-low-quality schedules.

Strengths:
- Mature hard/soft scoring vocabulary.
- Compactness and spread are treated as explicit constraints.
- Metaheuristics such as tabu search and late acceptance help escape local minima.

Limits:
- Some features depend on richer domain concepts than this project currently has, such as rooms, curricula, and student conflicts.
- Direct algorithm copying is not appropriate; we should reuse modeling ideas.

Reusable lessons:
- Add compactness and spread as separate metrics.
- Preserve room/curriculum concepts as future extension points.
- Use multiple strategies to search different quality tradeoffs.

### FET

Sources:
- https://lalescu.ro/liviu/fet/
- https://www.timetabling.de/manual/FET-manual.en.html

FET is focused on school timetabling with many practical constraints: max gaps, max hours daily, min days between activities, max days per week, preferred times, and teacher/student-specific limits. It also highlights a key operational lesson: overly strict constraints can make timetables unsolvable, so many quality preferences should start as weighted soft constraints.

Strengths:
- Rich school-specific constraint catalog.
- Strong anti-gap vocabulary for teachers and student sets.
- Practical advice on using max daily hours and max gaps carefully.

Limits:
- UI/application model is much broader than this SaaS prototype.
- Some constraints are institution-specific and should not be hard-coded globally.

Reusable lessons:
- Anti-gap rules are a high-value quick win.
- Daily load balancing is safer as soft first, hard later only when configured.
- Teacher-friendly schedules often mean fewer gaps and fewer required attendance days.

### UniTime

Sources:
- https://www.unitime.org/
- https://help.unitime.org/manuals/courses-solver

UniTime separates feasibility checking from optimization. It loads and validates data, searches for a complete feasible timetable, then optimizes preferences and provides conflict-based diagnostics. It also supports modifying existing timetables, which points toward minimal perturbation as a future mode.

Strengths:
- Clear staged workflow: check, solve, optimize, report.
- Conflict-based diagnostics for infeasible or weak solutions.
- Preference optimization and student conflict minimization.
- Minimal perturbation concepts for schedule changes.

Limits:
- University course timetabling includes rooms, students, departments, and existing timetables.
- Full UniTime-style workflows are beyond the current project scope.

Reusable lessons:
- Keep feasibility and quality diagnostics separate.
- Report why a schedule is weak, not just its score.
- Add minimal perturbation only after previous schedule inputs exist.

## Comparison

| System | Hard constraints | Soft scoring | Gaps/compactness | Preferences | Diagnostics | Multi-option |
| --- | --- | --- | --- | --- | --- | --- |
| OR-Tools | Explicit CP-SAT constraints | Weighted objective | Must be modeled manually | Must be modeled manually | Solver stats only; app adds explanations | App-controlled strategies |
| Timefold | Hard score | Soft score | Constraint-based | Constraint-based | Constraint matches and score analysis | Solver can keep best over time |
| OptaPlanner | Hard score | Soft score | Curriculum compactness, working days | Constraint-based | Score explanations | Metaheuristic exploration |
| FET | Large constraint catalog | Weighted constraints | Max gaps, max hours, preferred times | Rich teacher/student constraints | Practical reports/UI | Generates complete timetables |
| UniTime | Feasibility first | Preference optimization | Distribution preferences | Instructor, room, student demand | Conflict-based statistics | Solver configurations/modes |

## 10 concrete ideas for our solver

1. Keep hard and soft constraints in separate code paths.
2. Use named `StrategyWeights` instead of magic numbers.
3. Export detailed soft metrics, not only `quality_score`.
4. Generate top human-readable explanations per schedule.
5. Keep domain reduction before variable creation.
6. Add multiple OR-Tools strategies and select the best feasible result.
7. Treat teacher and class gaps separately.
8. Model spread by class/subject/day, not only total daily load.
9. Add morning preference penalties from existing `Condition` data.
10. Reserve `stability_penalty` for future minimal perturbation once previous schedules are part of input.

## Quick wins

- Keep medium at zero hard conflicts while improving quality metrics.
- Add `compact`, `teacher_friendly`, and `class_friendly` strategy profiles.
- Add benchmark columns for gaps, overload, spread, compactness, long series, and winning strategy.
- Limit detailed explanations to the top issues to keep JSON readable.

## Medium improvements

- Add optional teacher/day attendance penalties to reduce scattered teacher schedules.
- Add subject distribution targets per class.
- Add warm-start hints from the legacy schedule or previous OR-Tools solution.
- Add strategy-specific pre-assignment rules for teacher selection.

## Advanced roadmap

- Add rooms and room stability.
- Add student groups/curricula and student conflicts.
- Add minimal perturbation mode using a previous schedule.
- Add interactive repair mode for fixing selected classes.
- Add long-running asynchronous solve jobs when persistence is ready.

## Recommendations for current architecture

- Keep `ORToolsSolver` as the public experimental engine.
- Move reusable hard/soft/scoring helpers into `backend/services/solver/constraints.py`.
- Keep `legacy` as the default `/schedule/generate` behavior.
- Use benchmarks, not frontend changes, to expose multi-strategy first.
- Require all strategy outputs to pass the existing hard-conflict checks before comparing soft score.
