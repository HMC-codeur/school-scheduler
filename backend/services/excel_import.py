from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET


NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_RELS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def preview_excel_schedule(content: bytes, filename: str | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    lessons: list[dict[str, Any]] = []
    days: list[str] = []
    slots: list[str] = []

    if filename and not filename.lower().endswith(".xlsx"):
        warnings.append("Le fichier ne porte pas l'extension .xlsx.")
    if not content:
        return _empty_preview(warnings, ["Fichier vide."])

    try:
        rows = _read_first_sheet_rows(content)
    except zipfile.BadZipFile:
        return _empty_preview(warnings, ["Fichier .xlsx invalide ou corrompu."])
    except ET.ParseError:
        return _empty_preview(warnings, ["XML Excel invalide dans le fichier .xlsx."])
    except KeyError as exc:
        return _empty_preview(warnings, [f"Structure .xlsx incomplète : {exc}."])

    if not rows:
        return _empty_preview(warnings, ["Aucune cellule exploitable détectée."])

    header_index = _find_header_row(rows)
    if header_index is None:
        return _empty_preview(warnings, ["Impossible de détecter la ligne des jours."])

    header_row = rows[header_index]
    day_columns = [(column, value) for column, value in sorted(header_row.items()) if column > 1 and value]
    if not day_columns:
        return _empty_preview(warnings, ["Aucune colonne de jour détectée."])
    days = _unique_preserve_order([day for _, day in day_columns])

    first_day_column = min(column for column, _ in day_columns)
    for row_number in sorted(row for row in rows if row > header_index):
        row = rows[row_number]
        slot = _detect_slot(row, first_day_column)
        if not slot:
            if any(_normalize_text(row.get(column, "")) for column, _ in day_columns):
                warnings.append(f"Ligne {row_number} ignorée : créneau absent dans la colonne gauche.")
            continue
        slots.append(slot)
        for column, day in day_columns:
            raw = _normalize_text(row.get(column, ""))
            if not raw:
                continue
            lesson = _parse_lesson_cell(raw)
            lesson.update(
                {
                    "day": day,
                    "slot": slot,
                    "row": row_number,
                    "column": column,
                    "raw": raw,
                }
            )
            lessons.append(lesson)

    teachers = _unique_preserve_order([item["teacher"] for item in lessons if item.get("teacher")])
    rooms = _unique_preserve_order([item["room"] for item in lessons if item.get("room")])
    classes = _unique_preserve_order([item["class_name"] for item in lessons if item.get("class_name")])
    subjects = _unique_preserve_order([item["subject"] for item in lessons if item.get("subject")])
    slots = _unique_preserve_order(slots)

    if not lessons:
        warnings.append("Aucune leçon détectée dans la zone planning.")
    for lesson in lessons:
        if not lesson.get("teacher"):
            warnings.append(f"Professeur non détecté : {lesson['day']} {lesson['slot']} cellule {lesson['row']}:{lesson['column']}.")
        if not lesson.get("subject"):
            warnings.append(f"Matière non détectée : {lesson['day']} {lesson['slot']} cellule {lesson['row']}:{lesson['column']}.")

    return {
        "filename": filename,
        "days": days,
        "slots": slots,
        "classes": classes,
        "teachers": teachers,
        "subjects": subjects,
        "rooms": rooms,
        "lessons": lessons,
        "counts": {
            "days": len(days),
            "slots": len(slots),
            "classes": len(classes),
            "teachers": len(teachers),
            "subjects": len(subjects),
            "rooms": len(rooms),
            "lessons": len(lessons),
        },
        "warnings": _unique_preserve_order(warnings),
        "errors": errors,
    }


def _empty_preview(warnings: list[str], errors: list[str]) -> dict[str, Any]:
    return {
        "filename": None,
        "days": [],
        "slots": [],
        "classes": [],
        "teachers": [],
        "subjects": [],
        "rooms": [],
        "lessons": [],
        "counts": {"days": 0, "slots": 0, "classes": 0, "teachers": 0, "subjects": 0, "rooms": 0, "lessons": 0},
        "warnings": warnings,
        "errors": errors,
    }


def _read_first_sheet_rows(content: bytes) -> dict[int, dict[int, str]]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_path = _first_sheet_path(archive)
        worksheet = ET.fromstring(archive.read(sheet_path))

    rows: dict[int, dict[int, str]] = {}
    for cell in worksheet.findall(".//x:sheetData/x:row/x:c", NS_MAIN):
        reference = cell.attrib.get("r", "")
        row_number, column_number = _cell_coordinates(reference)
        if row_number is None or column_number is None:
            continue
        value = _cell_text(cell, shared_strings)
        if not value:
            continue
        rows.setdefault(row_number, {})[column_number] = value
    return rows


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("x:si", NS_MAIN):
        parts = [text.text or "" for text in item.findall(".//x:t", NS_MAIN)]
        values.append(_normalize_text("".join(parts)))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = workbook.find(".//x:sheets/x:sheet", NS_MAIN)
    if first_sheet is None:
        raise KeyError("xl/workbook.xml sans feuille")
    rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    if not rel_id:
        return "xl/worksheets/sheet1.xml"

    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("r:Relationship", NS_RELS):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "worksheets/sheet1.xml")
            return str(PurePosixPath("xl") / target).replace("\\", "/")
    return "xl/worksheets/sheet1.xml"


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return _normalize_text("".join(text.text or "" for text in cell.findall(".//x:t", NS_MAIN)))
    value = cell.find("x:v", NS_MAIN)
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    return _normalize_text(raw)


def _cell_coordinates(reference: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", reference or "")
    if not match:
        return None, None
    column = 0
    for char in match.group(1):
        column = column * 26 + (ord(char) - ord("A") + 1)
    return int(match.group(2)), column


def _find_header_row(rows: dict[int, dict[int, str]]) -> int | None:
    day_words = {
        "mon", "monday", "lun", "lundi",
        "tue", "tuesday", "mar", "mardi",
        "wed", "wednesday", "mer", "mercredi",
        "thu", "thursday", "jeu", "jeudi",
        "fri", "friday", "ven", "vendredi",
        "sun", "sunday", "dim", "dimanche",
        "ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת",
    }
    best_row: int | None = None
    best_score = 0
    for row_number, row in rows.items():
        values = [_normalize_text(value) for column, value in sorted(row.items()) if column > 1 and value]
        if len(values) < 2:
            continue
        score = sum(1 for value in values if _looks_like_day(value, day_words))
        if score > best_score:
            best_score = score
            best_row = row_number
    if best_row is not None and best_score > 0:
        return best_row
    for row_number, row in rows.items():
        if len([value for column, value in row.items() if column > 1 and value]) >= 2:
            return row_number
    return None


def _looks_like_day(value: str, day_words: set[str]) -> bool:
    cleaned = re.sub(r"^יום\s+", "", value.strip().lower())
    return cleaned in day_words or any(word in cleaned for word in day_words if len(word) > 3)


def _detect_slot(row: dict[int, str], first_day_column: int) -> str:
    for column in range(1, first_day_column):
        value = _normalize_text(row.get(column, ""))
        if value:
            return value
    return _normalize_text(row.get(1, ""))


def _parse_lesson_cell(raw: str) -> dict[str, str | None]:
    teacher = _extract_label_value(raw, ["מורה", "teacher", "prof", "professeur"])
    room = _extract_label_value(raw, ["חדר", "room", "salle"])
    content_lines = []
    for line in raw.split("\n"):
        if _line_has_label(line, ["מורה", "teacher", "prof", "professeur", "חדר", "room", "salle"]):
            continue
        cleaned = _normalize_text(line)
        if cleaned:
            content_lines.append(cleaned)
    subject_line = content_lines[0] if content_lines else ""
    class_name = _extract_class_name(subject_line) or _extract_class_name(raw)
    subject = _subject_from_line(subject_line, class_name)
    return {
        "subject": subject or None,
        "class_name": class_name,
        "teacher": teacher,
        "room": room,
    }


def _extract_label_value(text: str, labels: list[str]) -> str | None:
    joined = "\n".join(_normalize_text(line) for line in text.split("\n"))
    for label in labels:
        match = re.search(rf"(?:^|\n)\s*{re.escape(label)}\s*[:：]\s*([^\n]+)", joined, flags=re.IGNORECASE)
        if match:
            return _normalize_text(match.group(1)) or None
    return None


def _line_has_label(line: str, labels: list[str]) -> bool:
    return any(re.search(rf"^\s*{re.escape(label)}\s*[:：]", line, flags=re.IGNORECASE) for label in labels)


def _extract_class_name(text: str) -> str | None:
    explicit = re.search(r"(?:כיתה|classe|class)\s*[:：-]?\s*([0-9A-Za-zא-ת\"'׳ -]{1,16})", text, flags=re.IGNORECASE)
    if explicit:
        return _clean_class_token(explicit.group(1))
    tokens = [token.strip("()[]{}.,;:") for token in text.split()]
    for token in reversed(tokens):
        cleaned = _clean_class_token(token)
        if cleaned and _looks_like_class_token(cleaned):
            return cleaned
    return None


def _clean_class_token(value: str) -> str | None:
    cleaned = _normalize_text(value).strip("()[]{}.,;:")
    return cleaned or None


def _looks_like_class_token(value: str) -> bool:
    return bool(
        re.fullmatch(r"\d{1,2}[A-Za-zא-ת]?", value)
        or re.fullmatch(r"[A-Za-zא-ת]\d{1,2}", value)
        or re.fullmatch(r"[זחטיכל][\"'׳]?\d?", value)
    )


def _subject_from_line(subject_line: str, class_name: str | None) -> str:
    subject = subject_line
    subject = re.sub(r"(?:כיתה|classe|class)\s*[:：-]?\s*[0-9A-Za-zא-ת\"'׳ -]{1,16}", "", subject, flags=re.IGNORECASE).strip()
    if class_name:
        subject = re.sub(rf"(?:^|\s){re.escape(class_name)}(?:$|\s)", " ", subject).strip()
    return _normalize_text(subject)


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = _normalize_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique
