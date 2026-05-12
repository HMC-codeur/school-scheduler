import time
from dataclasses import dataclass

from backend.models.schemas import Class, ScheduleSession, Slot, Subject, Teacher


@dataclass
class ScheduleResult:
    success: bool
    message: str
    schedule: list[ScheduleSession]
    stats: dict
    details: list[str]


class SchedulerService:
    @staticmethod
    def generate(classes: list[Class], teachers: list[Teacher], subjects: list[Subject], slots: list[Slot]) -> ScheduleResult:
        start = time.perf_counter()
        by_slot = {s.id: s for s in slots}
        by_teacher = {t.id: t for t in teachers}
        required = []
        for subject in subjects:
            for class_id in subject.target_class_ids:
                for _ in range(subject.weekly_hours):
                    required.append((class_id, subject.id))
        required.sort(key=lambda x: len(next(s for s in subjects if s.id == x[1]).allowed_teacher_ids))
        sessions = []
        busy_class = set(); busy_teacher = set()
        sid = 1
        for class_id, subject_id in required:
            subject = next(s for s in subjects if s.id == subject_id)
            placed = False
            for slot in slots:
                if (class_id, slot.id) in busy_class:
                    continue
                for teacher_id in subject.allowed_teacher_ids:
                    t = by_teacher.get(teacher_id)
                    if not t or slot.id in t.unavailable_slot_ids:
                        continue
                    if (teacher_id, slot.id) in busy_teacher:
                        continue
                    sessions.append(ScheduleSession(session_id=sid, class_id=class_id, teacher_id=teacher_id, subject_id=subject_id, slot_id=slot.id))
                    sid += 1; busy_class.add((class_id, slot.id)); busy_teacher.add((teacher_id, slot.id)); placed = True
                    break
                if placed:
                    break
            if not placed:
                return ScheduleResult(False, "Impossible de générer un planning valide avec les contraintes actuelles.", sessions, {"total_sessions_required": len(required), "total_sessions_scheduled": len(sessions), "generation_time_ms": int((time.perf_counter()-start)*1000)}, [f"Session non planifiée: class_id={class_id}, subject_id={subject_id}"])

        return ScheduleResult(True, "Planning généré.", sessions, {"total_sessions_required": len(required), "total_sessions_scheduled": len(sessions), "conflicts_avoided": len(required), "generation_time_ms": int((time.perf_counter()-start)*1000)}, [])
