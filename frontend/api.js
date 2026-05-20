const API_CONFIG = {
  local: "http://localhost:8000",
  production: "https://school-scheduler-uzyo.onrender.com",
};

function getApiBaseUrl() {
  const override = window.SCHOOL_SCHEDULER_API_URL || new URLSearchParams(window.location.search).get("api");
  if (override) return normalizeApiBaseUrl(override);

  const host = window.location.hostname;
  const port = window.location.port;
  const isLocalHost = ["localhost", "127.0.0.1", ""].includes(host);
  const isLocalFrontend = isLocalHost || ["3000", "5173", "5174", "5500"].includes(port);

  if (isLocalFrontend) return API_CONFIG.local;
  if (window.location.origin === API_CONFIG.production) return window.location.origin;
  return API_CONFIG.production;
}

function normalizeApiBaseUrl(url) {
  return String(url || "").replace(/\/+$/, "");
}

function buildApiUrl(path) {
  const baseUrl = getApiBaseUrl();
  const cleanPath = String(path || "/").startsWith("/") ? String(path || "/") : `/${path}`;
  return `${baseUrl}${cleanPath}`;
}

function apiErrorMessage(payload, status) {
  const detail = payload?.detail;
  let message = "";
  if (typeof detail === "string") message = detail;
  else if (Array.isArray(detail)) {
    message = detail
      .map((item) => {
        if (typeof item === "string") return item;
        return item?.message || item?.msg || `${(item?.loc || []).join(".")}: ${item?.msg || "Erreur"}`;
      })
      .join(" | ");
  } else if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") message = detail.message;
    else if (Array.isArray(detail.errors)) {
      message = detail.errors.map((item) => (typeof item === "string" ? item : item?.message || String(item))).join(" | ");
    }
  } else if (Array.isArray(payload?.errors)) {
    message = payload.errors.map((item) => (typeof item === "string" ? item : item?.message || String(item))).join(" | ");
  } else {
    message = payload?.message || `Erreur HTTP ${status}`;
  }
  if (status === 404) message = `${message}. Endpoint introuvable. Le frontend appelle peut-être une ancienne route.`;
  return sanitizeExcelError(message);
}

async function apiFetch(path, requestOptions) {
  const options = requestOptions || {};
  const url = buildApiUrl(path);
  const headers = new Headers(options.headers || {});
  const body = options.body;
  if (body && !(body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  updateApiDebug({ lastEndpoint: path, lastError: "" });
  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (error) {
    const message = classifyNetworkError(error);
    updateApiDebug({ status: "error", lastError: message });
    throw new Error(message);
  }
  if (!response.ok) {
    const payload = await parseApiPayload(response);
    const message = apiErrorMessage(payload || {}, response.status);
    updateApiDebug({ status: "error", lastError: message });
    const error = new Error(message);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  updateApiDebug({ status: "ok", lastError: "" });
  return response;
}

async function api(path, requestOptions) {
  const response = await apiFetch(path, requestOptions);
  return parseApiPayload(response);
}

function sanitizeExcelError(message) {
  const text = String(message || "");
  if (text.includes("expected <class") || text.includes("openpyxl.styles.fills.Fill")) {
    return "Impossible de lire ce fichier Excel. Essayez de le réenregistrer en .xlsx depuis Excel ou Google Sheets.";
  }
  return text;
}

async function parseApiPayload(response) {
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) return response.json().catch(() => ({}));
  return response.text().then((text) => text ? { message: text } : {}).catch(() => ({}));
}

function classifyNetworkError(error) {
  const text = error?.message || "";
  if (text.toLowerCase().includes("failed to fetch")) {
    return "Impossible de joindre le backend. Vérifie que FastAPI tourne sur le port 8000 ou que l'URL Render est correcte. Le navigateur peut aussi bloquer la requête: vérifie la configuration CORS du backend.";
  }
  if (text.toLowerCase().includes("timeout")) {
    return "Le serveur Render peut être en train de se réveiller. Réessaie dans quelques secondes.";
  }
  return `Erreur réseau : ${text || "backend indisponible"}`;
}

function updateApiDebug(patch = {}) {
  scheduleState.apiDebug = { ...(scheduleState.apiDebug || {}), apiBaseUrl: getApiBaseUrl(), ...patch };
  if (typeof renderApiDebugPanel === "function") renderApiDebugPanel();
}
