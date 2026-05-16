import { useState } from "react";
import { createSubject } from "../api/schoolApi.js";
import { DataTable } from "../components/DataTable.jsx";
import { FormMessage } from "../components/FormMessage.jsx";
import { PageHeader } from "../components/PageHeader.jsx";

export function SubjectsPage({ data, loading, refreshData }) {
  const [form, setForm] = useState({ name: "", hours_per_week: 1 });
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const columns = [
    { key: "name", label: "מקצוע" },
    { key: "hours_per_week", label: "שעות שבועיות" },
  ];

  const submitSubject = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await createSubject({
        name: form.name,
        hours_per_week: Number(form.hours_per_week),
      });
      setForm({ name: "", hours_per_week: 1 });
      setMessage({ type: "success", text: "המקצוע נוצר בהצלחה" });
      await refreshData();
    } catch (error) {
      setMessage({ type: "error", text: error.message || "יצירת המקצוע נכשלה" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="תכנית לימודים" title="מקצועות" description="מקצועות ושעות שבועיות מחוברות ל-API הקיים." />
      <section className="panel">
        <div className="section-head">
          <h3>הוסף מקצוע</h3>
        </div>
        <form className="inline-form" onSubmit={submitSubject}>
          <input
            aria-label="שם מקצוע"
            placeholder="שם מקצוע"
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            required
          />
          <input
            aria-label="שעות שבועיות"
            min="1"
            type="number"
            value={form.hours_per_week}
            onChange={(event) => setForm((current) => ({ ...current, hours_per_week: event.target.value }))}
          />
          <button className="primary-button" disabled={saving} type="submit">שמור מקצוע</button>
        </form>
        <FormMessage message={message} />
      </section>
      {loading ? <div className="notice">טוען מקצועות...</div> : null}
      <DataTable columns={columns} rows={data.subjects} emptyText="אין מקצועות להצגה" />
    </>
  );
}
