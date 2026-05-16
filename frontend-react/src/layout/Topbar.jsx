export function Topbar({ error, language, setLanguage, t }) {
  return (
    <header className="topbar">
      <div>
        <span className="eyebrow">MVP repair-first</span>
        <h1>{t.appName}</h1>
      </div>
      <div className="topbar-status">
        <select value={language} onChange={(event) => setLanguage(event.target.value)} aria-label="Language">
          <option value="he">עברית</option>
          <option value="fr">Français</option>
        </select>
        <span className={`status-dot ${error ? "danger" : "ready"}`} />
        <span>{error ? "נדרש חיבור לשרת" : "מחובר לשרת"}</span>
      </div>
    </header>
  );
}
