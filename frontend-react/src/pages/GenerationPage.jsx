import { useEffect, useState } from "react";
import {
  clearSchedule,
  createSlot,
  generateSchedule,
  getScheduleOptions,
  loadDemo,
  loadLargeDemo,
  loadPilotDemo,
} from "../api/schoolApi.js";
import { EmptyState } from "../components/EmptyState.jsx";
import { FormMessage } from "../components/FormMessage.jsx";
import { PageHeader } from "../components/PageHeader.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

const steps = ["בדיקת נתונים", "יצירת אפשרויות", "השוואה", "אישור"];

export function GenerationPage({ data, refreshData }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [slotForm, setSlotForm] = useState({ slot: "" });
  const [slotMessage, setSlotMessage] = useState(null);
  const [savingSlot, setSavingSlot] = useState(false);
  const [options, setOptions] = useState([]);

  const runAction = async (action) => {
    setBusy(true);
    setMessage("");
    try {
      const result = await action();
      setMessage(result.message || "הפעולה הסתיימה בהצלחה");
      await refreshData();
      const scheduleOptions = await getScheduleOptions();
      setOptions(scheduleOptions);
    } catch (error) {
      setMessage(error.message || "הפעולה נכשלה");
    } finally {
      setBusy(false);
    }
  };

  const readyForGeneration = data.classes.length && data.teachers.length && data.subjects.length && data.slots.length;

  useEffect(() => {
    getScheduleOptions()
      .then(setOptions)
      .catch(() => setOptions([]));
  }, []);

  const submitSlot = async (event) => {
    event.preventDefault();
    setSavingSlot(true);
    setSlotMessage(null);
    try {
      await createSlot({ slot: slotForm.slot });
      setSlotForm({ slot: "" });
      setSlotMessage({ type: "success", text: "השעה נוצרה בהצלחה" });
      await refreshData();
    } catch (error) {
      setSlotMessage({ type: "error", text: error.message || "יצירת השעה נכשלה" });
    } finally {
      setSavingSlot(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Workflow"
        title="יצירת מערכת"
        description="תהליך מדורג שמתחבר רק לפעולות שכבר קיימות בשרת."
      />
      <section className="workflow">
        {steps.map((step, index) => (
          <article className="workflow-step" key={step}>
            <span>{index + 1}</span>
            <strong>{step}</strong>
          </article>
        ))}
      </section>
      <section className="panel">
        <div className="section-head">
          <h3>בדיקת מוכנות</h3>
          <StatusBadge status={readyForGeneration ? "ready" : "warning"}>
            {readyForGeneration ? "אפשר ליצור" : "חסר מידע"}
          </StatusBadge>
        </div>
        <div className="action-row">
          <button className="secondary-button" disabled={busy} onClick={() => runAction(loadDemo)} type="button">טען דמו</button>
          <button className="secondary-button" disabled={busy} onClick={() => runAction(loadLargeDemo)} type="button">טען דמו גדול</button>
          <button className="secondary-button" disabled={busy} onClick={() => runAction(loadPilotDemo)} type="button">טען דמו פיילוט</button>
          <button className="secondary-button" disabled={busy} onClick={() => runAction(clearSchedule)} type="button">נקה נתונים</button>
          <button className="primary-button" disabled={busy} onClick={() => runAction(generateSchedule)} type="button">צור מערכת</button>
        </div>
        {message ? <div className="notice">{message}</div> : null}
      </section>
      <section className="panel">
        <div className="section-head">
          <h3>הוסף שעה</h3>
          <span className="muted">פורמט: Day-HH:MM</span>
        </div>
        <form className="inline-form" onSubmit={submitSlot}>
          <input
            aria-label="שעה"
            placeholder="Mon-08:00"
            value={slotForm.slot}
            onChange={(event) => setSlotForm({ slot: event.target.value })}
            required
          />
          <button className="primary-button" disabled={savingSlot} type="submit">שמור שעה</button>
        </form>
        <FormMessage message={slotMessage} />
        <div className="chip-list">
          {data.slots.slice(0, 24).map((slot) => (
            <span className="chip" key={slot}>{slot}</span>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="section-head">
          <h3>אפשרויות מערכת</h3>
          <span className="muted">מחובר ל-/schedule/options</span>
        </div>
        {!options.length ? (
          <EmptyState title="אין אפשרויות להשוואה עדיין" description="לאחר יצירת מערכת, אפשרויות זמינות יוצגו כאן." />
        ) : (
          <div className="card-grid">
            {options.map((option) => (
              <article className="option-card" key={option.id}>
                <h3>{option.title || option.id}</h3>
                <strong>{option.quality_score || 0}</strong>
                <span>ציון איכות</span>
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
