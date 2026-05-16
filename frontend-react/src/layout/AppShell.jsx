import { Sidebar } from "./Sidebar.jsx";
import { Topbar } from "./Topbar.jsx";

export function AppShell({ activePage, onNavigate, error, language, setLanguage, direction, t, children }) {
  return (
    <div className="app-shell" dir={direction} lang={language}>
      <Sidebar activePage={activePage} onNavigate={onNavigate} t={t} />
      <main className="main-panel">
        <Topbar error={error} language={language} setLanguage={setLanguage} t={t} />
        <div className="page-surface">{children}</div>
      </main>
    </div>
  );
}
