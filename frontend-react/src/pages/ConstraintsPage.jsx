import { useState } from "react";
import { createCondition } from "../api/schoolApi.js";
import { DataTable } from "../components/DataTable.jsx";
import { FormMessage } from "../components/FormMessage.jsx";
import { PageHeader } from "../components/PageHeader.jsx";

const conditionTypes = [
  { value: "teacher_unavailable", label: "מורה לא זמין" },
  { value: "class_unavailable", label: "כיתה לא זמינה" },
  { value: "subject_morning_preference", label: "מקצוע בבוקר" },
  { value: "avoid_subject_repeat", label: "לא לחזור על מקצוע באותו יום" },
  { value: "teacher_prefer_morning", label: "מורה מעדיף בוקר" },
  { value: "avoid_long_sequence", label: "להימנע מרצף ארוך" },
];

export function ConstraintsPage({ data, refreshData }) {
  const [form, setForm] = useState({
    text: "",
    condition_type: "teacher_unavailable",
    teacher_name: "",
    class_name: "",
    subject_name: "",
    slot: "",
    hard: true,
  });
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);

  const submitCondition = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    const payload = {
      text: form.text,
      condition_type: form.condition_type,
      hard: form.hard,
    };
    if (form.teacher_name) payload.teacher_name = form.teacher_name;
    if (form.class_name) payload.class_name = form.class_name;
    if (form.subject_name) payload.subject_name = form.subject_name;
    if (form.slot) payload.slot = form.slot;

    try {
      await createCondition(payload);
      setForm({
        text: "",
        condition_type: "teacher_unavailable",
        teacher_name: "",
        class_name: "",
        subject_name: "",
        slot: "",
        hard: true,
      });
      setMessage({ type: "success", text: "האילוץ נוצר בהצלחה" });
      await refreshData();
    } catch (error) {
      setMessage({ type: "error", text: error.message || "יצירת האילוץ נכשלה" });
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    { key: "text", label: "תיאור" },
    { key: "condition_type", label: "סוג" },
    { key: "slot", label: "שעה", render: (row) => row.slot || "-" },
    { key: "hard", label: "קשיח", render: (row) => (row.hard ? "כן" : "לא") },
  ];

  return (
    <>
      <PageHeader eyebrow="אילוצים" title="אילוצים" description="יצירת אילוצים דרך /conditions הקיים." />
      <section className="panel">
        <div className="section-head">
          <h3>הוסף אילוץ</h3>
        </div>
        <form className="inline-form" onSubmit={submitCondition}>
          <input
            aria-label="תיאור אילוץ"
            placeholder="תיאור אילוץ"
            value={form.text}
            onChange={(event) => setForm((current) => ({ ...current, text: event.target.value }))}
            required
          />
          <select
            aria-label="סוג אילוץ"
            value={form.condition_type}
            onChange={(event) => setForm((current) => ({ ...current, condition_type: event.target.value }))}
          >
            {conditionTypes.map((type) => (
              <option key={type.value} value={type.value}>{type.label}</option>
            ))}
          </select>
          <input
            aria-label="שם מורה"
            placeholder="שם מורה"
            value={form.teacher_name}
            onChange={(event) => setForm((current) => ({ ...current, teacher_name: event.target.value }))}
          />
          <input
            aria-label="שם כיתה"
            placeholder="שם כיתה"
            value={form.class_name}
            onChange={(event) => setForm((current) => ({ ...current, class_name: event.target.value }))}
          />
          <input
            aria-label="שם מקצוע"
            placeholder="שם מקצוע"
            value={form.subject_name}
            onChange={(event) => setForm((current) => ({ ...current, subject_name: event.target.value }))}
          />
          <input
            aria-label="שעה"
            placeholder="Mon-08:00"
            value={form.slot}
            onChange={(event) => setForm((current) => ({ ...current, slot: event.target.value }))}
          />
          <label className="check-label">
            <input
              checked={form.hard}
              type="checkbox"
              onChange={(event) => setForm((current) => ({ ...current, hard: event.target.checked }))}
            />
            אילוץ קשיח
          </label>
          <button className="primary-button" disabled={saving} type="submit">שמור אילוץ</button>
        </form>
        <FormMessage message={message} />
      </section>
      <DataTable columns={columns} rows={data.conditions} emptyText="אין אילוצים להצגה" />
    </>
  );
}
