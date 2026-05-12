const API_BASE = "";

const state = {
  classes: [],
  teachers: [],
  subjects: [],
  slots: [],
  schedule: {},
  selectedViewMode: "class",
  selectedClassId: "",
  selectedTeacherId: "",
  searchQuery: "",
  isGenerating: false,
  isLoadingDemo: false,
  errorMessage: "",
};

function el(id) { return document.getElementById(id); }

async function api(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || `HTTP ${response.status}`);
    return data;
  } catch (error) {
    throw new Error(error.message || "Erreur réseau");
  }
}

function showMessage(message, type = "info") {
  const toast = el("toast");
  toast.textContent = message;
  toast.className = `toast ${type}`;
  setTimeout(() => { toast.className = "toast hidden"; }, 3000);
}

function handleError(error, fallback = "Une erreur est survenue") {
  state.errorMessage = error?.message || fallback;
  showMessage(state.errorMessage, "error");
  renderSchedule();
}

async function loadClasses() { state.classes = await api("/classes"); }
async function loadTeachers() { state.teachers = await api("/teachers"); }
async function loadSubjects() { state.subjects = await api("/subjects"); }
async function loadSlots() { state.slots = await api("/slots"); }
async function loadSchedule() { state.schedule = await api("/schedule"); }

async function loadAllData() {
  await Promise.all([loadClasses(), loadTeachers(), loadSubjects(), loadSlots(), loadSchedule()]);
}

function setButtonLoading(button, loading, label) {
  button.disabled = loading;
  if (loading) {
    button.dataset.label = button.textContent;
    button.textContent = label;
  } else {
    button.textContent = button.dataset.label || button.textContent;
  }
}

function renderClasses() {
  const list = el("classes-list");
  list.innerHTML = state.classes.length
    ? state.classes.map((c) => `<li>${c.name} (max/jour: ${c.max_lessons_per_day})</li>`).join("")
    : "<li>Aucune classe.</li>";
  el("count-classes").textContent = state.classes.length;
}

function renderTeachers() {
  const list = el("teachers-list");
  list.innerHTML = state.teachers.length
    ? state.teachers.map((t) => `<li>${t.name} — ${t.subjects.join(", ") || "Aucune matière"}</li>`).join("")
    : "<li>Aucun professeur.</li>";
  el("count-teachers").textContent = state.teachers.length;
}

function renderSubjects() {
  const list = el("subjects-list");
  list.innerHTML = state.subjects.length
    ? state.subjects.map((s) => `<li>${s.name} (${s.hours_per_week}h/sem)</li>`).join("")
    : "<li>Aucune matière.</li>";
  el("count-subjects").textContent = state.subjects.length;
}

function renderSlots() {
  const list = el("slots-list");
  list.innerHTML = state.slots.length ? state.slots.map((slot) => `<li>${slot}</li>`).join("") : "<li>Aucun créneau.</li>";
  el("count-slots").textContent = state.slots.length;
}

function renderScheduleFilters() {
  const classSelect = el("schedule-class-filter");
  const teacherSelect = el("schedule-teacher-filter");
  classSelect.innerHTML = `<option value="">Choisir une classe</option>${state.classes.map((c) => `<option value="${c.name}">${c.name}</option>`).join("")}`;
  teacherSelect.innerHTML = `<option value="">Choisir un professeur</option>${state.teachers.map((t) => `<option value="${t.name}">${t.name}</option>`).join("")}`;

  if (state.selectedClassId && !state.classes.some((c) => c.name === state.selectedClassId)) state.selectedClassId = "";
  if (state.selectedTeacherId && !state.teachers.some((t) => t.name === state.selectedTeacherId)) state.selectedTeacherId = "";

  classSelect.value = state.selectedClassId;
  teacherSelect.value = state.selectedTeacherId;

  const isClassView = state.selectedViewMode === "class";
  el("schedule-class-group").classList.toggle("hidden", !isClassView);
  el("schedule-teacher-group").classList.toggle("hidden", isClassView);
}

function renderSchedule() {
  const table = el("schedule-table");
  const empty = el("schedule-empty-message");
  const hasSchedule = state.schedule && Object.keys(state.schedule).length > 0;

  if (!hasSchedule) {
    table.innerHTML = "";
    empty.textContent = state.isGenerating ? "Génération en cours..." : "Aucun emploi du temps généré pour le moment.";
    empty.classList.remove("hidden");
    return;
  }

  if (state.errorMessage) {
    empty.textContent = state.errorMessage;
    empty.classList.remove("hidden");
  }

  const search = state.searchQuery.toLowerCase();
  const mode = state.selectedViewMode;
  const selected = mode === "class" ? state.selectedClassId : state.selectedTeacherId;
  if (!selected) {
    table.innerHTML = "";
    empty.textContent = mode === "class" ? "Sélectionnez une classe." : "Sélectionnez un professeur.";
    empty.classList.remove("hidden");
    return;
  }

  const rows = state.slots.map((slot) => {
    const row = state.schedule[slot] || {};
    if (mode === "class") {
      const cell = row[selected] || null;
      if (search && !(cell?.subject || "").toLowerCase().includes(search) && !selected.toLowerCase().includes(search)) return null;
      return `<tr><td class="slot-col">${slot}</td><td>${cell ? `<div class="cell-subject">${cell.subject}</div><div class="cell-meta">${selected} · ${cell.teacher}</div>` : "—"}</td></tr>`;
    }
    const foundClass = Object.keys(row).find((className) => row[className]?.teacher === selected);
    const cell = foundClass ? row[foundClass] : null;
    if (search && !selected.toLowerCase().includes(search) && !(cell?.subject || "").toLowerCase().includes(search)) return null;
    return `<tr><td class="slot-col">${slot}</td><td>${cell ? `<div class="cell-subject">${cell.subject}</div><div class="cell-meta">${foundClass} · ${selected}</div>` : "—"}</td></tr>`;
  }).filter(Boolean);

  if (!rows.length) {
    table.innerHTML = "";
    empty.textContent = "Aucun résultat pour ce filtre.";
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");
  table.innerHTML = `<tr><th class="slot-col">Créneau</th><th>${selected}</th></tr>${rows.join("")}`;
}

function renderAll() {
  renderClasses();
  renderTeachers();
  renderSubjects();
  renderSlots();
  renderScheduleFilters();
  renderSchedule();
}

async function generateSchedule() {
  const button = el("generate-btn");
  state.isGenerating = true;
  state.errorMessage = "";
  setButtonLoading(button, true, "Génération en cours...");
  renderSchedule();
  try {
    const res = await api("/schedule/generate", { method: "POST" });
    if (!res.success) throw new Error(res.message || "Génération impossible");
    await loadSchedule();
    showMessage("Emploi du temps généré avec succès.", "success");
  } catch (error) {
    handleError(error, "Erreur lors de la génération");
  } finally {
    state.isGenerating = false;
    setButtonLoading(button, false);
    renderSchedule();
  }
}

async function loadDemoData() {
  const button = el("load-demo-btn");
  state.isLoadingDemo = true;
  setButtonLoading(button, true, "Chargement...");
  try {
    await api("/schedule/load-demo", { method: "POST" });
    await loadAllData();
    showMessage("Données démo chargées.", "success");
  } catch (error) {
    handleError(error, "Impossible de charger la démo");
  } finally {
    state.isLoadingDemo = false;
    setButtonLoading(button, false);
    renderAll();
  }
}

async function handleCreate(path, payload) {
  await api(path, { method: "POST", body: JSON.stringify(payload) });
  await loadAllData();
  renderAll();
}

function bindForm(formId, path, payloadFn) {
  const form = el(formId);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    setButtonLoading(button, true, "Ajout...");
    try {
      await handleCreate(path, payloadFn());
      form.reset();
      showMessage("Ajout effectué.", "success");
    } catch (error) {
      handleError(error, "Erreur lors de l'ajout");
    } finally {
      setButtonLoading(button, false);
    }
  });
}

function initApp() {
  el("schedule-view-mode").addEventListener("change", (e) => { state.selectedViewMode = e.target.value; renderAll(); });
  el("schedule-class-filter").addEventListener("change", (e) => { state.selectedClassId = e.target.value; renderSchedule(); });
  el("schedule-teacher-filter").addEventListener("change", (e) => { state.selectedTeacherId = e.target.value; renderSchedule(); });
  el("schedule-search").addEventListener("input", (e) => { state.searchQuery = e.target.value.trim(); renderSchedule(); });
  el("generate-btn").addEventListener("click", generateSchedule);
  el("load-demo-btn").addEventListener("click", loadDemoData);

  bindForm("class-form", "/classes", () => ({ name: el("class-name").value.trim(), max_lessons_per_day: Number(el("class-max-lessons").value) }));
  bindForm("teacher-form", "/teachers", () => ({ name: el("teacher-name").value.trim(), subjects: el("teacher-subjects").value.split(",").map((s) => s.trim()).filter(Boolean), unavailable_slots: [], max_lessons_per_day: Number(el("teacher-max-lessons").value) }));
  bindForm("subject-form", "/subjects", () => ({ name: el("subject-name").value.trim(), hours_per_week: Number(el("subject-hours").value) }));
  bindForm("slot-form", "/slots", () => ({ slot: el("slot-value").value.trim() }));
}

(async () => {
  initApp();
  try {
    await loadAllData();
    renderAll();
  } catch (error) {
    handleError(error, "Impossible de charger les données initiales");
  }
})();
