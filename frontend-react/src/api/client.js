export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });
  } catch (error) {
    throw new Error(`שגיאת רשת: ${error.message || "השרת אינו זמין"}`);
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => `${(item.loc || []).join(".")}: ${item.msg}`).join(" | ")
      : typeof detail === "string"
        ? detail
        : payload.message || "הבקשה נכשלה";
    throw new Error(message);
  }

  return response.json().catch(() => ({}));
}
