const navItems = [
  { id: "dashboard", labelKey: "dashboard", icon: "⌂" },
  { id: "importExcel", labelKey: "importExcel", icon: "⇪" },
  { id: "diagnostic", labelKey: "diagnostic", icon: "!" },
  { id: "repair", labelKey: "repair", icon: "✎" },
  { id: "compare", labelKey: "correctedSchedule", icon: "▥" },
  { id: "exports", labelKey: "exports", icon: "↓" },
  { id: "classes", labelKey: "data", icon: "▦" },
  { id: "generation", labelKey: "generation", icon: "▶" },
];

export function Sidebar({ activePage, onNavigate, t }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">AI</span>
        <div>
          <strong>{t.appName}</strong>
          <small>{t.appSubtitle}</small>
        </div>
      </div>
      <nav className="nav-list" aria-label="ניווט ראשי">
        {navItems.map((item) => (
          <button
            className={`nav-item ${activePage === item.id ? "active" : ""}`}
            key={item.id}
            onClick={() => onNavigate(item.id)}
            type="button"
          >
            <span className="nav-icon" aria-hidden="true">{item.icon}</span>
            <span>{t[item.labelKey]}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
