const $ = (id) => document.getElementById(id);

const create = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};

function notify(message, type = "success") {
  const el = $("toast");
  if (!el) return;
  el.textContent = message;
  el.className = `toast ${type}`;
  setTimeout(() => (el.className = "toast hidden"), 3500);
}

function scoreLabel(score) {
  const numeric = Number(score);
  if (!Number.isFinite(numeric)) return { label: "Non généré", className: "muted" };
  if (numeric >= 90) return { label: "Excellent", className: "excellent" };
  if (numeric >= 75) return { label: "Bon", className: "good" };
  if (numeric >= 50) return { label: "Moyen", className: "average" };
  return { label: "À améliorer", className: "bad" };
}

function setLoading(button, isLoading, text) {
  if (!button) return;
  button.disabled = isLoading;
  if (isLoading) {
    if (!button.dataset.originalText) button.dataset.originalText = button.textContent;
    button.textContent = text;
    return;
  }
  button.textContent = button.dataset.originalText || button.textContent;
  delete button.dataset.originalText;
}

function setButtonsLoading(buttons, isLoading, text) {
  Array.from(buttons || []).forEach((button) => setLoading(button, isLoading, text));
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("fr-FR");
}

function formatScore(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric}/100` : "--";
}
