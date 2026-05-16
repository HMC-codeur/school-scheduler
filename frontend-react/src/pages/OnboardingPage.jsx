import { useState } from "react";
import { PageHeader } from "../components/PageHeader.jsx";
import { FormMessage } from "../components/FormMessage.jsx";

export function OnboardingPage({ navigate, t }) {
  const [form, setForm] = useState({
    schoolName: "",
    hours: "08:00-15:00",
    subjects: "",
    teachers: "",
    classes: "",
  });
  const [message, setMessage] = useState(null);

  const submit = (event) => {
    event.preventDefault();
    localStorage.setItem("schoolSchedulerOnboarding", JSON.stringify(form));
    setMessage({ type: "success", text: "הטיוטה נשמרה מקומית. אין כאן עדיין התחברות אמיתית או tenant אמיתי." });
  };

  return (
    <>
      <PageHeader
        eyebrow="Onboarding"
        title="הגדרת בית ספר"
        description="טיוטת התחלה מקומית לדמו. אין כאן התחברות אמיתית או מערכת רב-מוסדית."
      />
      <section className="panel">
        <form className="stack-form" onSubmit={submit}>
          <input placeholder="שם בית הספר" value={form.schoolName} onChange={(e) => setForm({ ...form, schoolName: e.target.value })} />
          <input placeholder="שעות פעילות" value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} />
          <textarea placeholder="מקצועות, מופרדים בפסיק" value={form.subjects} onChange={(e) => setForm({ ...form, subjects: e.target.value })} />
          <textarea placeholder="מורים, מופרדים בפסיק" value={form.teachers} onChange={(e) => setForm({ ...form, teachers: e.target.value })} />
          <textarea placeholder="כיתות, מופרדות בפסיק" value={form.classes} onChange={(e) => setForm({ ...form, classes: e.target.value })} />
          <div className="action-row">
            <button className="secondary-button" type="button">המשך עם Google (mock)</button>
            <button className="secondary-button" type="button">כניסה בטלפון (mock)</button>
            <button className="primary-button" type="submit">שמור טיוטה</button>
          </div>
        </form>
        <FormMessage message={message} />
      </section>
      <button className="primary-button" type="button" onClick={() => navigate("importExcel")}>{t.importExcel}</button>
    </>
  );
}
