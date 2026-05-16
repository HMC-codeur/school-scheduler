export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function parseError(response) {
  const payload = await response.json().catch(() => ({}));
  const detail = payload.detail;
  return Array.isArray(detail)
    ? detail.map((item) => `${(item.loc || []).join(".")}: ${item.msg}`).join(" | ")
    : typeof detail === "string"
      ? detail
      : payload.message || "הבקשה נכשלה";
}

export async function apiRequest(path, options = {}) {
  let response;
  const headers = options.body instanceof FormData
    ? options.headers || {}
    : {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers,
      ...options,
    });
  } catch (error) {
    throw new Error(`שגיאת רשת: ${error.message || "השרת אינו זמין"}`);
  }

  if (!response.ok) {
    const message = await parseError(response);
    throw new Error(message);
  }

  return response.json().catch(() => ({}));
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
