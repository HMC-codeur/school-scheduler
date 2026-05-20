export function Topbar({ error, backendStatus, apiDebug, language, setLanguage, t }) {
  const connected = backendStatus === "connected";
  const statusClass = connected ? "ready" : backendStatus === "checking" ? "warning" : "danger";
  const statusText = connected ? "Connecté au serveur" : backendStatus === "checking" ? "Connexion au serveur..." : "Pas connecté au serveur";

  return (
    <header className="topbar">
      <div>
        <span className="eyebrow">MVP repair-first</span>
        <h1>{t.appName}</h1>
        <details className="api-debug-panel">
          <summary>API</summary>
          <p>API utilisée: <span>{apiDebug?.apiBaseUrl || "-"}</span></p>
          <p>Status: <span>{apiDebug?.status || backendStatus || "-"}</span></p>
          <p>Dernier appel: <span>{apiDebug?.lastEndpoint || "-"}</span></p>
          <p>Erreur: <span>{apiDebug?.lastError || error || "-"}</span></p>
          <p>Réponse /health: <span>{apiDebug?.healthResponse || "-"}</span></p>
        </details>
      </div>
      <div className="topbar-status">
        <select value={language} onChange={(event) => setLanguage(event.target.value)} aria-label="Language">
          <option value="he">עברית</option>
          <option value="fr">Français</option>
        </select>
        <span className={`status-dot ${statusClass}`} />
        <span>{statusText}</span>
      </div>
    </header>
  );
}
