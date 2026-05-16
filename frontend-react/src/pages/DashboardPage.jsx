import { EmptyState } from "../components/EmptyState.jsx";
import { PageHeader } from "../components/PageHeader.jsx";
import { StatCard } from "../components/StatCard.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

export function DashboardPage({ data, loading, error, navigate }) {
  const scheduleSize = Object.keys(data.schedule || {}).length;
  const checklist = [
    { label: "להוסיף כיתות", done: data.classes.length > 0 },
    { label: "להוסיף מורים ומקצועות", done: data.teachers.length > 0 && data.subjects.length > 0 },
    { label: "להגדיר שעות לימוד", done: data.slots.length > 0 },
    { label: "ליצור מערכת ראשונה", done: scheduleSize > 0 },
  ];

  return (
    <>
      <PageHeader
        eyebrow="סקירה"
        title="לוח בקרה"
        description="תמונה קצרה של מוכנות בית הספר לפני יצירת מערכת."
        action={<button className="primary-button" onClick={() => navigate("generation")} type="button">ליצירת מערכת</button>}
      />
      <section className="quick-actions" aria-label="פעולות מהירות">
        <button className="secondary-button" onClick={() => navigate("classes")} type="button">הוסף כיתה</button>
        <button className="secondary-button" onClick={() => navigate("teachers")} type="button">הוסף מורה</button>
        <button className="secondary-button" onClick={() => navigate("subjects")} type="button">הוסף מקצוע</button>
        <button className="secondary-button" onClick={() => navigate("generation")} type="button">הוסף שעה</button>
        <button className="secondary-button" onClick={() => navigate("constraints")} type="button">הוסף אילוץ</button>
      </section>

      {loading ? <div className="notice">טוען נתונים...</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      <section className="stat-grid">
        <StatCard label="כיתות" value={data.classes.length} helper="מחובר לשרת" tone="ready" />
        <StatCard label="מורים" value={data.teachers.length} helper="מחובר לשרת" />
        <StatCard label="מקצועות" value={data.subjects.length} helper="מחובר לשרת" />
        <StatCard label="אילוצים" value={data.conditions.length} helper="מחובר לשרת" />
        <StatCard label="חדרים" value="0" helper="ממשק מוכן, API בהמשך" tone="warning" />
        <StatCard label="מצב מערכת" value={scheduleSize ? "קיימת" : "חסרה"} helper="לפי planning פעיל" tone={scheduleSize ? "ready" : "warning"} />
      </section>

      <section className="panel">
        <div className="section-head">
          <h3>מה צריך להשלים לפני יצירת מערכת</h3>
          <StatusBadge status={checklist.every((item) => item.done) ? "ready" : "warning"}>
            {checklist.every((item) => item.done) ? "מוכן" : "חסרים נתונים"}
          </StatusBadge>
        </div>
        <div className="checklist">
          {checklist.map((item) => (
            <div className="check-row" key={item.label}>
              <span className={item.done ? "check ready" : "check"}>{item.done ? "✓" : "•"}</span>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </section>

      {!loading && !data.classes.length ? (
        <EmptyState
          title="עדיין אין נתוני בית ספר"
          description="אפשר לטעון דמו מהמסך של יצירת המערכת, בלי לשנות את מנוע השרת."
          action={<button className="secondary-button" onClick={() => navigate("generation")} type="button">פתח יצירת מערכת</button>}
        />
      ) : null}
    </>
  );
}
