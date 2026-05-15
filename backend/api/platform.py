from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
import csv
from io import StringIO
from typing import Any

from backend.data.memory_store import MemoryStore
from backend.data.store import get_store

router = APIRouter(tags=["platform"])


def _is_complete_option(option: dict) -> bool:
    return bool(
        option.get("id")
        and option.get("schedule") is not None
        and option.get("quality_score") is not None
        and option.get("schedule_signature")
    )


@router.get('/health')
def health() -> dict:
    return {"status": "ok"}


@router.get('/stats')
def stats(store: MemoryStore = Depends(get_store)) -> dict:
    return {
        "classes": len(store.classes),
        "teachers": len(store.teachers),
        "subjects": len(store.subjects),
        "learning_groups": len(getattr(store, "learning_groups", [])),
        "slots": len(store.slots),
        "constraints": len(store.conditions),
        "has_schedule": bool(store.schedule),
        "schedule_versions": len(getattr(store, "schedule_versions", [])),
    }


@router.get('/constraints')
def list_constraints(store: MemoryStore = Depends(get_store)) -> list:
    return store.conditions


@router.post('/constraints')
def create_constraint(payload: dict, store: MemoryStore = Depends(get_store)) -> dict:
    # Alias léger vers /conditions pour compatibilité historique
    from backend.models.schemas import ConditionCreate
    try:
        condition = store.add_condition(ConditionCreate(**payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return condition.model_dump()


@router.delete('/constraints/{constraint_id}')
def delete_constraint(constraint_id: int, store: MemoryStore = Depends(get_store)) -> dict:
    if not store.delete_condition(constraint_id):
        raise HTTPException(status_code=404, detail='Constraint not found')
    return {"message": "Constraint deleted."}


@router.get('/schedule/options')
def schedule_options(store: MemoryStore = Depends(get_store)) -> list[dict]:
    return [option for option in store.schedule_options if _is_complete_option(option)]


@router.get('/schedule/export/json')
def export_schedule_json(store: MemoryStore = Depends(get_store)) -> dict:
    return {"schedule": store.schedule, "options": store.schedule_options}


def _cell_value(cell: Any) -> tuple[str, str]:
    if isinstance(cell, dict):
        return str(cell.get("subject", "")), str(cell.get("teacher", ""))
    return str(cell.subject), str(cell.teacher)


def _cell_session_id(cell: Any) -> str:
    if isinstance(cell, dict):
        return str(cell.get("session_id") or "")
    return str(getattr(cell, "session_id", "") or "")


def _split_slot(slot: str) -> tuple[str, str]:
    if "-" not in slot:
        return slot, ""
    day, start_time = slot.split("-", 1)
    return day, start_time


def _end_time(start_time: str, store: MemoryStore) -> str:
    settings = getattr(store, "time_settings", None)
    if not settings or not start_time:
        return ""
    try:
        start = datetime.strptime(start_time, "%H:%M")
    except ValueError:
        return ""
    end = start + timedelta(minutes=settings.lesson_duration_minutes)
    return end.strftime("%H:%M")


def _schedule_rows_from_schedule(schedule: dict, store: MemoryStore) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for slot, entries in (schedule or {}).items():
        day, start_time = _split_slot(slot)
        end_time = _end_time(start_time, store)
        for class_name, cell in entries.items():
            subject, teacher = _cell_value(cell)
            rows.append(
                {
                    "day": day,
                    "start_time": start_time,
                    "end_time": end_time,
                    "class": class_name,
                    "teacher": teacher,
                    "subject": subject,
                    "session_id": _cell_session_id(cell),
                }
            )
    return sorted(rows, key=lambda row: (_day_sort_key(row["day"]), row["start_time"], row["class"]))


def _schedule_export_rows(store: MemoryStore) -> list[dict[str, str]]:
    return _schedule_rows_from_schedule(store.schedule, store)


def _day_sort_key(day: str) -> tuple[int, str]:
    order = {
        "mon": 1,
        "monday": 1,
        "lun": 1,
        "lundi": 1,
        "tue": 2,
        "tuesday": 2,
        "mar": 2,
        "mardi": 2,
        "wed": 3,
        "wednesday": 3,
        "mer": 3,
        "mercredi": 3,
        "thu": 4,
        "thursday": 4,
        "jeu": 4,
        "jeudi": 4,
        "fri": 5,
        "friday": 5,
        "ven": 5,
        "vendredi": 5,
        "sat": 6,
        "saturday": 6,
        "sam": 6,
        "samedi": 6,
        "sun": 7,
        "sunday": 7,
        "dim": 7,
        "dimanche": 7,
    }
    normalized = day.strip().lower()
    return (order.get(normalized, 99), normalized)


@router.get('/schedule/export/csv')
def export_schedule_csv(store: MemoryStore = Depends(get_store)) -> Response:
    rows = _schedule_export_rows(store)
    if not rows:
        raise HTTPException(status_code=404, detail="No generated schedule to export")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["day", "start_time", "end_time", "class", "teacher", "subject"])
    for row in rows:
        writer.writerow([row["day"], row["start_time"], row["end_time"], row["class"], row["teacher"], row["subject"]])

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="school-schedule.csv"'},
    )


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _selected_schedule_option(store: MemoryStore) -> dict:
    selected_id = getattr(store, "selected_schedule_option_id", None)
    options = [option for option in getattr(store, "schedule_options", []) if _is_complete_option(option)]
    if selected_id:
        selected = next((option for option in options if option.get("id") == selected_id), None)
        if selected:
            return selected
    return next((option for option in options if option.get("selected") is True), options[0] if options else {})


def _text_command(x: int, y: int, text: str, font_size: int = 9, font: str = "F1") -> str:
    # Set text fill color inside each text object so background fills never
    # leak a pale color into table text.
    return f"BT 0.05 0.06 0.08 rg /{font} {font_size} Tf {x} {y} Td ({_pdf_escape(text)}) Tj ET"


def _rect_command(x: int, y: int, width: int, height: int, fill: bool = False) -> str:
    return f"{x} {y} {width} {height} re {'f' if fill else 'S'}"


def _line_command(x1: int, y1: int, x2: int, y2: int) -> str:
    return f"{x1} {y1} m {x2} {y2} l S"


def _truncate(text: str, max_chars: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(1, max_chars - 1)].rstrip() + "…"


def _table_page_stream(
    title: str,
    rows: list[dict[str, str]],
    option: dict,
    page_number: int,
    total_pages: int,
) -> bytes:
    left = 32
    top = 805
    row_height = 21
    header_height = 22
    table_width = 531
    widths = [62, 58, 58, 92, 139, 122]
    headers = ["Jour", "Heure début", "Heure fin", "Classe", "Matière", "Professeur"]
    max_chars = [10, 9, 9, 16, 25, 22]
    commands = [
        "0.92 0.95 1 rg",
        _rect_command(0, 782, 595, 60, fill=True),
        "0 0 0 RG",
        "0.82 0.86 0.92 RG",
        "0.2 w",
        _text_command(left, top + 14, title, 18, "F2"),
        _text_command(left, top - 6, f"Exporté le {datetime.now().strftime('%d/%m/%Y %H:%M')}", 10),
        _text_command(left + 280, top - 6, f"Option : {option.get('title') or option.get('id') or '-'}", 10),
        _text_command(left + 280, top - 20, f"Score : {option.get('quality_score', '-')}/100", 10),
        _text_command(left, top - 20, f"Signature : {option.get('schedule_signature') or '-'}", 10),
        _text_command(500, 24, f"Page {page_number}/{total_pages}", 8),
        "0.88 0.91 0.96 rg",
        _rect_command(left, 724, table_width, header_height, fill=True),
        "0 0 0 RG",
        "0.78 0.82 0.89 RG",
        _rect_command(left, 724, table_width, header_height),
    ]

    x = left
    header_text_commands = []
    for width, label in zip(widths, headers):
        commands.append(_line_command(x, 724, x, 746))
        header_text_commands.append(_text_command(x + 4, 731, label, 9, "F2"))
        x += width
    commands.append(_line_command(left + table_width, 724, left + table_width, 746))
    commands.extend(header_text_commands)

    y = 704
    for row_index, row in enumerate(rows):
        if row_index % 2 == 0:
            commands.append("0.98 0.99 1 rg")
            commands.append(_rect_command(left, y - 2, table_width, row_height, fill=True))
            commands.append("0 0 0 RG")
        commands.append("0.86 0.89 0.94 RG")
        commands.append(_rect_command(left, y - 2, table_width, row_height))
        values = [
            row["day"],
            row["start_time"],
            row["end_time"] or "-",
            row["class"],
            row["subject"],
            row["teacher"],
        ]
        x = left
        row_text_commands = []
        for width, value, chars in zip(widths, values, max_chars):
            commands.append(_line_command(x, y - 2, x, y + row_height - 2))
            row_text_commands.append(_text_command(x + 4, y + 5, _truncate(value, chars), 9))
            x += width
        commands.append(_line_command(left + table_width, y - 2, left + table_width, y + row_height - 2))
        commands.extend(row_text_commands)
        y -= row_height

    return "\n".join(commands).encode("latin-1", errors="replace")


def _build_pdf(title: str, rows: list[dict[str, str]], option: dict) -> bytes:
    rows_per_page = 32
    pages = [rows[index:index + rows_per_page] for index in range(0, len(rows), rows_per_page)] or [[]]
    font_ref = 3 + len(pages) * 2

    objects: list[bytes] = []
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))

    for index, page_rows in enumerate(pages):
        page_ref = 3 + index * 2
        content_ref = page_ref + 1
        stream = _table_page_stream(title, page_rows, option, index + 1, len(pages))
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_ref} 0 R /F2 {font_ref + 1} 0 R >> >> /Contents {content_ref} 0 R >>"
            ).encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _build_pdf_document(streams: list[bytes]) -> bytes:
    font_ref = 3 + len(streams) * 2
    objects: list[bytes] = []
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(streams)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(streams)} >>".encode("ascii"))
    for index, stream in enumerate(streams):
        page_ref = 3 + index * 2
        content_ref = page_ref + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_ref} 0 R /F2 {font_ref + 1} 0 R >> >> /Contents {content_ref} 0 R >>"
            ).encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _repair_report_cover_stream(proposal: dict) -> bytes:
    changed_items = proposal.get("changed_items") or []
    commands = [
        "0.92 0.95 1 rg",
        _rect_command(0, 782, 595, 60, fill=True),
        "0.05 0.06 0.08 RG",
        _text_command(32, 819, "Repair Report", 20, "F2"),
        _text_command(32, 800, f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}", 10),
        _text_command(32, 760, "Résumé", 14, "F2"),
    ]
    summary_lines = [
        f"proposal_id: {proposal.get('proposal_id') or '-'}",
        f"repair_type: {proposal.get('repair_type') or '-'}",
        f"repair_policy: {proposal.get('repair_policy') or '-'}",
        f"quality_score: {proposal.get('quality_score', '-')}/100",
        f"stability_score: {proposal.get('stability_score', '-')}/100",
        f"hard_conflicts: {proposal.get('hard_conflicts', '-')}",
        f"changed_items_count: {len(changed_items)}",
    ]
    y = 738
    for line in summary_lines:
        commands.append(_text_command(42, y, _truncate(line, 80), 10))
        y -= 16

    commands.append(_text_command(32, y - 10, "Changements détectés", 14, "F2"))
    y -= 32
    if not changed_items:
        commands.append(_text_command(42, y, "Aucun changement détaillé retourné.", 10))
    for item in changed_items[:24]:
        subject = item.get("subject_name") or item.get("subject_id") or "-"
        class_name = item.get("class_name") or item.get("class_id") or "-"
        old_slot = item.get("old_slot") or "-"
        new_slot = item.get("new_slot") or "-"
        old_teacher = item.get("old_teacher_name") or item.get("old_teacher_id") or "-"
        new_teacher = item.get("new_teacher_name") or item.get("new_teacher_id") or "-"
        session_id = item.get("session_id") or "-"
        line = f"{class_name} | {subject} | {old_slot} -> {new_slot} | {old_teacher} -> {new_teacher} | {session_id}"
        commands.append(_text_command(42, y, _truncate(line, 95), 8))
        y -= 14
        if y < 48:
            break
    if len(changed_items) > 24:
        commands.append(_text_command(42, max(40, y), f"... {len(changed_items) - 24} changement(s) supplémentaire(s)", 8))
    commands.append(_text_command(500, 24, "Page 1", 8))
    return "\n".join(commands).encode("latin-1", errors="replace")


def _repair_table_page_stream(
    rows: list[dict[str, str]],
    changed_session_ids: set[str],
    page_number: int,
    total_pages: int,
) -> bytes:
    stream = _table_page_stream(
        "Planning proposé",
        rows,
        {"title": "Repair proposal", "quality_score": "-", "schedule_signature": "-"},
        page_number,
        total_pages,
    ).decode("latin-1", errors="replace")
    if not changed_session_ids:
        return stream.encode("latin-1", errors="replace")
    commands = [stream, "0.20 0.70 0.32 RG", "1.1 w"]
    left = 32
    table_width = 531
    y = 704
    row_height = 21
    for row in rows:
        if row.get("session_id") in changed_session_ids:
            commands.append(_rect_command(left + 1, y - 1, table_width - 2, row_height - 2))
        y -= row_height
    return "\n".join(commands).encode("latin-1", errors="replace")


def build_repair_report_pdf(proposal: dict, store: MemoryStore) -> bytes:
    rows = _schedule_rows_from_schedule(proposal.get("schedule", {}), store)
    changed_session_ids = {
        str(item.get("session_id"))
        for item in proposal.get("changed_items", [])
        if item.get("session_id")
    }
    rows_per_page = 32
    row_pages = [rows[index:index + rows_per_page] for index in range(0, len(rows), rows_per_page)] or [[]]
    total_pages = len(row_pages) + 1
    streams = [_repair_report_cover_stream(proposal)]
    for index, page_rows in enumerate(row_pages, start=2):
        streams.append(_repair_table_page_stream(page_rows, changed_session_ids, index, total_pages))
    return _build_pdf_document(streams)


@router.get('/schedule/export/pdf')
def export_schedule_pdf(store: MemoryStore = Depends(get_store)) -> Response:
    rows = _schedule_export_rows(store)
    if not rows:
        raise HTTPException(status_code=404, detail="No generated schedule to export")
    pdf = _build_pdf("Emploi du temps scolaire", rows, _selected_schedule_option(store))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="school-schedule.pdf"'},
    )
