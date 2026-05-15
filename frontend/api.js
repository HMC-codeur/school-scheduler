const API = "";

async function api(path, requestOptions) {
  const options = requestOptions || {};
  let response;
  try {
    response = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (error) {
    throw new Error(`Erreur réseau : ${error.message || "backend indisponible"}`);
  }
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const detail = err?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => `${(item.loc || []).join(".")}: ${item.msg}`).join(" | ")
      : (typeof detail === "string" ? detail : (err.message || "Request failed"));
    throw new Error(message);
  }
  return response.json().catch(() => ({}));
}
