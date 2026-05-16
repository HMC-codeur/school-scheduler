const navItems = [
  { id: "dashboard", label: "לוח בקרה", icon: "⌂" },
  { id: "classes", label: "כיתות", icon: "▦" },
  { id: "teachers", label: "מורים", icon: "◇" },
  { id: "subjects", label: "מקצועות", icon: "◫" },
  { id: "students", label: "תלמידים", icon: "○" },
  { id: "rooms", label: "חדרים", icon: "□" },
  { id: "constraints", label: "אילוצים", icon: "!" },
  { id: "generation", label: "יצירת מערכת", icon: "▶" },
  { id: "schedule", label: "מערכת", icon: "▤" },
];

export function Sidebar({ activePage, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">ש</span>
        <div>
          <strong>School Scheduler</strong>
          <small>ניהול מערכת שעות</small>
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
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
