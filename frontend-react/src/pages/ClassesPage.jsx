import { useMemo, useState } from "react";
import { createClass } from "../api/schoolApi.js";
import { EmptyState } from "../components/EmptyState.jsx";
import { FormMessage } from "../components/FormMessage.jsx";
import { PageHeader } from "../components/PageHeader.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

export function ClassesPage({ data, loading, navigate, refreshData }) {
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ name: "", max_lessons_per_day: 6 });
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const classes = useMemo(
    () => data.classes.filter((classItem) => classItem.name.toLowerCase().includes(query.toLowerCase())),
    [data.classes, query]
  );

  const submitClass = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await createClass({
        name: form.name,
        max_lessons_per_day: Number(form.max_lessons_per_day),
      });
      setForm({ name: "", max_lessons_per_day: 6 });
      setMessage({ type: "success", text: "הכיתה נוצרה בהצלחה" });
      await refreshData();
    } catch (error) {
      setMessage({ type: "error", text: error.message || "יצירת הכיתה נכשלה" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="ניהול"
        title="כיתות"
        description="רשימת הכיתות והשלמות נדרשות לפני בניית מערכת."
      />
      <section className="panel">
        <div className="section-head">
          <h3>הוסף כיתה</h3>
        </div>
        <form className="inline-form" onSubmit={submitClass}>
          <input
            aria-label="שם כיתה"
            placeholder="שם כיתה"
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            required
          />
          <input
            aria-label="מקסימום שיעורים ביום"
            min="1"
            type="number"
            value={form.max_lessons_per_day}
            onChange={(event) => setForm((current) => ({ ...current, max_lessons_per_day: event.target.value }))}
          />
          <button className="primary-button" disabled={saving} type="submit">שמור כיתה</button>
        </form>
        <FormMessage message={message} />
      </section>
      <div className="toolbar">
        <input
          aria-label="חיפוש כיתה"
          placeholder="חיפוש כיתה"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {loading ? <div className="notice">טוען כיתות...</div> : null}
      {!loading && !classes.length ? (
        <EmptyState title="אין כיתות להצגה" description="כאן תופיע רשימת הכיתות לאחר טעינה או יצירה." />
      ) : (
        <div className="card-grid">
          {classes.map((classItem) => (
            <button className="class-card" key={classItem.id} onClick={() => navigate("classDetail", { classItem })} type="button">
              <div>
                <h3>{classItem.name}</h3>
                <p>{classItem.max_lessons_per_day} שיעורים ביום לכל היותר</p>
              </div>
              <div className="class-meta">
                <span>תלמידים: לא מחובר</span>
                <span>מקצועות: {data.subjects.length}</span>
              </div>
              <StatusBadge status={data.subjects.length && data.teachers.length ? "ready" : "warning"}>
                {data.subjects.length && data.teachers.length ? "שלם" : "חסרים נתונים"}
              </StatusBadge>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
