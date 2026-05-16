import { useMemo, useState } from "react";
import { createClass, createSubject, createTeacher } from "../api/schoolApi.js";
import { PageHeader } from "../components/PageHeader.jsx";
import { FormMessage } from "../components/FormMessage.jsx";

const steps = ["פרטי כיתה", "מקצועות", "מורים", "קבוצות", "סיכום"];

export function ClassNewPage({ navigate, refreshData }) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState(() => {
    const saved = localStorage.getItem("classNewDraft");
    return saved ? JSON.parse(saved) : {
      className: "",
      maxLessons: 6,
      subjects: "",
      teachers: "",
      groups: "הקבצה א, הקבצה ב, הקבצה ג",
    };
  });
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);

  const update = (patch) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    localStorage.setItem("classNewDraft", JSON.stringify(next));
  };

  const subjectNames = useMemo(() => draft.subjects.split(",").map((item) => item.trim()).filter(Boolean), [draft.subjects]);
  const teacherNames = useMemo(() => draft.teachers.split(",").map((item) => item.trim()).filter(Boolean), [draft.teachers]);

  const saveRealData = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await createClass({ name: draft.className, max_lessons_per_day: Number(draft.maxLessons) });
      for (const subject of subjectNames) {
        await createSubject({ name: subject, hours_per_week: 1 }).catch(() => null);
      }
      for (const teacher of teacherNames) {
        await createTeacher({ name: teacher, subjects: subjectNames.slice(0, 2), unavailable_slots: [], max_lessons_per_day: 6 }).catch(() => null);
      }
      localStorage.removeItem("classNewDraft");
      setMessage({ type: "success", text: "הכיתה נשמרה בשרת. קבוצות נשארות מקומיות עד API מתאים." });
      await refreshData();
    } catch (err) {
      setMessage({ type: "error", text: err.message || "שמירת הכיתה נכשלה" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="/classes/new" title="יצירת כיתה חדשה" description="Assistant multi-étapes RTL. כיתה/מקצועות/מורים נשמרים לשרת; קבוצות הן טיוטה מקומית." />
      <section className="wizard-steps">
        {steps.map((label, index) => <button className={index === step ? "active" : ""} key={label} onClick={() => setStep(index)} type="button">{index + 1}. {label}</button>)}
      </section>
      <section className="panel">
        {step === 0 ? (
          <div className="stack-form">
            <input placeholder="שם כיתה" value={draft.className} onChange={(e) => update({ className: e.target.value })} />
            <input min="1" type="number" placeholder="מקסימום שיעורים ביום" value={draft.maxLessons} onChange={(e) => update({ maxLessons: e.target.value })} />
          </div>
        ) : null}
        {step === 1 ? <textarea placeholder="מקצועות, מופרדים בפסיק" value={draft.subjects} onChange={(e) => update({ subjects: e.target.value })} /> : null}
        {step === 2 ? <textarea placeholder="מורים, מופרדים בפסיק" value={draft.teachers} onChange={(e) => update({ teachers: e.target.value })} /> : null}
        {step === 3 ? (
          <>
            <textarea placeholder="קבוצות/הקבצות מקומיות" value={draft.groups} onChange={(e) => update({ groups: e.target.value })} />
            <p className="muted">TODO: connect real learning groups/students flow later.</p>
          </>
        ) : null}
        {step === 4 ? (
          <div className="summary-list">
            <span>כיתה: {draft.className || "-"}</span>
            <span>מקצועות לשמירה: {subjectNames.length}</span>
            <span>מורים לשמירה: {teacherNames.length}</span>
            <span>קבוצות מקומיות: {draft.groups || "-"}</span>
          </div>
        ) : null}
        <div className="action-row">
          <button className="secondary-button" disabled={step === 0} onClick={() => setStep(step - 1)} type="button">חזרה</button>
          {step < steps.length - 1 ? <button className="primary-button" onClick={() => setStep(step + 1)} type="button">המשך</button> : null}
          {step === steps.length - 1 ? <button className="primary-button" disabled={saving || !draft.className} onClick={saveRealData} type="button">שמור בשרת</button> : null}
          <button className="secondary-button" onClick={() => navigate("classes")} type="button">יציאה</button>
        </div>
        <FormMessage message={message} />
      </section>
    </>
  );
}
