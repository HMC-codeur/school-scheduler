import { useState } from "react";
import { createTeacher } from "../api/schoolApi.js";
import { DataTable } from "../components/DataTable.jsx";
import { FormMessage } from "../components/FormMessage.jsx";
import { PageHeader } from "../components/PageHeader.jsx";

export function TeachersPage({ data, loading, refreshData }) {
  const [form, setForm] = useState({
    name: "",
    subjects: "",
    unavailable_slots: "",
    max_lessons_per_day: 6,
  });
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const columns = [
    { key: "name", label: "שם מורה" },
    { key: "subjects", label: "מקצועות", render: (row) => row.subjects?.join(", ") || "-" },
    { key: "max_lessons_per_day", label: "מקסימום ביום" },
  ];

  const submitTeacher = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await createTeacher({
        name: form.name,
        subjects: form.subjects.split(",").map((item) => item.trim()).filter(Boolean),
        unavailable_slots: form.unavailable_slots.split(",").map((item) => item.trim()).filter(Boolean),
        max_lessons_per_day: Number(form.max_lessons_per_day),
      });
      setForm({ name: "", subjects: "", unavailable_slots: "", max_lessons_per_day: 6 });
      setMessage({ type: "success", text: "המורה נוצר בהצלחה" });
      await refreshData();
    } catch (error) {
      setMessage({ type: "error", text: error.message || "יצירת המורה נכשלה" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="צוות" title="מורים" description="מורים, מקצועות וזמינות בסיסית מהשרת הקיים." />
      <section className="panel">
        <div className="section-head">
          <h3>הוסף מורה</h3>
        </div>
        <form className="inline-form" onSubmit={submitTeacher}>
          <input
            aria-label="שם מורה"
            placeholder="שם מורה"
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            required
          />
          <input
            aria-label="מקצועות"
            placeholder="מקצועות מופרדים בפסיק"
            value={form.subjects}
            onChange={(event) => setForm((current) => ({ ...current, subjects: event.target.value }))}
          />
          <input
            aria-label="זמנים לא זמינים"
            placeholder="Mon-08:00, Tue-10:00"
            value={form.unavailable_slots}
            onChange={(event) => setForm((current) => ({ ...current, unavailable_slots: event.target.value }))}
          />
          <input
            aria-label="מקסימום שיעורים ביום"
            min="1"
            type="number"
            value={form.max_lessons_per_day}
            onChange={(event) => setForm((current) => ({ ...current, max_lessons_per_day: event.target.value }))}
          />
          <button className="primary-button" disabled={saving} type="submit">שמור מורה</button>
        </form>
        <FormMessage message={message} />
      </section>
      {loading ? <div className="notice">טוען מורים...</div> : null}
      <DataTable columns={columns} rows={data.teachers} emptyText="אין מורים להצגה" />
    </>
  );
}
