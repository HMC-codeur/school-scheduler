import { useMemo, useState } from "react";
import { EmptyState } from "../components/EmptyState.jsx";
import { PageHeader } from "../components/PageHeader.jsx";

function flattenSchedule(schedule) {
  return Object.entries(schedule || {}).flatMap(([slot, classes]) =>
    Object.entries(classes || {}).map(([className, cell]) => ({
      id: `${slot}-${className}-${cell.subject}`,
      slot,
      className,
      subject: cell.subject,
      teacher: cell.teacher,
    }))
  );
}

export function SchedulePage({ data, loading }) {
  const [classFilter, setClassFilter] = useState("");
  const [teacherFilter, setTeacherFilter] = useState("");
  const rows = useMemo(() => flattenSchedule(data.schedule), [data.schedule]);
  const filteredRows = rows.filter((row) => {
    const classMatch = !classFilter || row.className === classFilter;
    const teacherMatch = !teacherFilter || row.teacher === teacherFilter;
    return classMatch && teacherMatch;
  });
  const teachers = [...new Set(rows.map((row) => row.teacher).filter(Boolean))];

  return (
    <>
      <PageHeader eyebrow="תוצאה" title="מערכת שעות" description="תצוגה נקייה של המערכת הפעילה, עם סינון בסיסי." />
      {loading ? <div className="notice">טוען מערכת...</div> : null}
      <div className="toolbar">
        <select value={classFilter} onChange={(event) => setClassFilter(event.target.value)} aria-label="סינון כיתה">
          <option value="">כל הכיתות</option>
          {data.classes.map((classItem) => (
            <option value={classItem.name} key={classItem.id}>{classItem.name}</option>
          ))}
        </select>
        <select value={teacherFilter} onChange={(event) => setTeacherFilter(event.target.value)} aria-label="סינון מורה">
          <option value="">כל המורים</option>
          {teachers.map((teacher) => (
            <option value={teacher} key={teacher}>{teacher}</option>
          ))}
        </select>
      </div>
      {!filteredRows.length ? (
        <EmptyState title="אין מערכת להצגה" description="לאחר יצירת מערכת, השיעורים יופיעו כאן לפי כיתה ומורה." />
      ) : (
        <div className="schedule-list">
          {filteredRows.slice(0, 80).map((row) => (
            <article className="schedule-item" key={row.id}>
              <time>{row.slot}</time>
              <strong>{row.className}</strong>
              <span>{row.subject}</span>
              <span>{row.teacher}</span>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
