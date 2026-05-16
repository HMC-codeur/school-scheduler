import { Sidebar } from "./Sidebar.jsx";
import { Topbar } from "./Topbar.jsx";

export function AppShell({ activePage, onNavigate, error, children }) {
  return (
    <div className="app-shell" dir="rtl" lang="he">
      <Sidebar activePage={activePage} onNavigate={onNavigate} />
      <main className="main-panel">
        <Topbar error={error} />
        <div className="page-surface">{children}</div>
      </main>
    </div>
  );
}
