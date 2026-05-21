function defaultApiBaseUrl() {
  if (typeof window === "undefined") return "http://127.0.0.1:8000";
  const { protocol, hostname, port, origin } = window.location;
  const isLocalFrontend = ["localhost", "127.0.0.1", ""].includes(hostname) || ["3000", "5173", "5174", "5500"].includes(port);
  const productionUrl = "https://school-scheduler-uzyo.onrender.com";
  const productionHost = new URL(productionUrl).hostname;
  if (isLocalFrontend && protocol.startsWith("http")) return "http://127.0.0.1:8000";
  if (hostname.includes(productionHost)) return productionUrl;
  return origin || productionUrl;
}

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl();
console.log("API_BASE_URL", API_BASE_URL);

let apiDebugListener = null;

const apiDebugState = {
  apiBaseUrl: API_BASE_URL,
  status: "unknown",
  lastEndpoint: "",
  lastError: "",
  lastResponse: "",
  healthResponse: "",
};

export function getApiDebugSnapshot() {
  return { ...apiDebugState };
}

export function setApiDebugListener(listener) {
  apiDebugListener = listener;
  if (apiDebugListener) apiDebugListener(getApiDebugSnapshot());
  return () => {
    if (apiDebugListener === listener) apiDebugListener = null;
  };
}

function updateApiDebug(patch) {
  Object.assign(apiDebugState, { apiBaseUrl: API_BASE_URL }, patch);
  if (apiDebugListener) apiDebugListener(getApiDebugSnapshot());
}

async function parseError(response) {
  const payload = await response.json().catch(() => ({}));
  const detail = payload.detail;
  return Array.isArray(detail)
    ? detail.map((item) => `${(item.loc || []).join(".")}: ${item.msg}`).join(" | ")
    : typeof detail === "string"
      ? detail
      : detail && typeof detail === "object"
        ? JSON.stringify(detail)
        : payload.message || "הבקשה נכשלה";
}

function formatApiDebugPayload(payload) {
  if (payload === undefined || payload === null) return "";
  if (typeof payload === "string") return payload;
  try {
    const text = JSON.stringify(payload);
    return text.length > 500 ? `${text.slice(0, 500)}...` : text;
  } catch (error) {
    return String(payload);
  }
}

export async function apiRequest(path, options = {}) {
  let response;
  const headers = options.body instanceof FormData
    ? options.headers || {}
    : {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };
  updateApiDebug({ status: "checking", lastEndpoint: path, lastError: "" });
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers,
      ...options,
    });
  } catch (error) {
    const message = `שגיאת רשת: ${error.message || "השרת אינו זמין"}`;
    updateApiDebug({ status: "error", lastError: message });
    throw new Error(message);
  }

  if (!response.ok) {
    const message = await parseError(response);
    updateApiDebug({ status: "error", lastError: message });
    throw new Error(message);
  }

  const payload = await response.json().catch(() => ({}));
  updateApiDebug({
    status: "ok",
    lastError: "",
    lastResponse: formatApiDebugPayload(payload),
    ...(path === "/health" ? { healthResponse: formatApiDebugPayload(payload) } : {}),
  });
  return payload;
}

export async function downloadRequest(path) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch (error) {
    throw new Error(`שגיאת רשת: ${error.message || "השרת אינו זמין"}`);
  }
  if (!response.ok) {
    const message = await parseError(response);
    throw new Error(message);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  return {
    blob,
    filename: match?.[1] || "school-schedule",
  };
}
