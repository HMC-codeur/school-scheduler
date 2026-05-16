export function Topbar({ error }) {
  return (
    <header className="topbar">
      <div>
        <span className="eyebrow">פלטפורמה לבתי ספר וישיבות</span>
        <h1>יצירת מערכת שעות חכמה</h1>
      </div>
      <div className="topbar-status">
        <span className={`status-dot ${error ? "danger" : "ready"}`} />
        <span>{error ? "נדרש חיבור לשרת" : "מחובר לשרת"}</span>
      </div>
    </header>
  );
}
