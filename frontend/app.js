const API = "";
const scheduleState = { slots: [], classes: [], teachers: [], schedule: {}, selectedClass: "", selectedTeacher: "", viewMode: "class", search: "" };
let lastQualityMetrics = null;

const ID_FALLBACKS = {
  "generate-btn": ["generate-schedule-btn"],
  "load-demo-btn": ["demo-btn"],
  "load-large-demo-btn": ["large-demo-btn"],
  "clear-btn": ["clear-data-btn"],
  "schedule-view-mode": ["result-view-mode"],
  "schedule-class-filter": ["class-filter"],
  "schedule-teacher-filter": ["teacher-filter"],
  "schedule-search": ["search-input"],
};

function el(id, required = true) {
  const candidates = [id, ...(ID_FALLBACKS[id] || [])];
  for (const candidate of candidates) {
    const found = document.getElementById(candidate);
    if (found) return found;
  }
  if (required) throw new Error(`Missing required element: ${id}`);
  return null;
}

function on(id, event, handler) {
  const node = el(id, false);
  if (node) node.addEventListener(event, handler);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Request failed");
  }
  return response.json().catch(() => ({}));
}

function notify(message, type = "success") { const toast = el("toast"); toast.textContent = message; toast.className = `toast ${type}`; setTimeout(() => (toast.className = "toast hidden"), 3000); }
function setLoading(button, isLoading, text) { button.disabled = isLoading; if (isLoading) { button.dataset.originalText = button.textContent; button.textContent = text; } else { button.textContent = button.dataset.originalText || button.textContent; } }
function getUnavailableSlots() { return Array.from(el("teacher-unavailable-slots").selectedOptions).map((opt) => opt.value); }
function validateNonEmpty(value, field) { if (!value || !value.trim()) throw new Error(`${field} is required.`); }

function updateConditionFieldVisibility() {
  const type = el("condition-type").value;
  document.querySelectorAll("[data-condition-field]").forEach((el) => {
    const types = el.dataset.conditionField.split(" ");
    el.style.display = types.includes(type) ? "" : "none";
  });
  buildConditionText();
}

function buildConditionText() {
  const type = el("condition-type").value;
  const teacher = el("condition-teacher-name").value.trim();
  const className = el("condition-class-name").value.trim();
  const subject = el("condition-subject-name").value.trim();
  const slot = el("condition-slot").value;
  let text = "Condition personnalisée";
  if (type === "teacher_unavailable") text = `Professeur ${teacher || "(à définir)"} indisponible sur ${slot || "(créneau à définir)"}`;
  if (type === "class_unavailable") text = `Classe ${className || "(à définir)"} indisponible sur ${slot || "(créneau à définir)"}`;
  if (type === "subject_morning_preference") text = `Placer ${subject || "(matière à définir)"} le matin si possible`;
  if (type === "avoid_subject_repeat") text = `Éviter de répéter ${subject || "(matière à définir)"}${className ? ` pour ${className}` : ""} le même jour`;
  el("condition-text").value = text;
}

function resetFormWithDefaults(form) {
  form.reset();
  const excluded = (form.dataset.resetExclusions || "").split(",").map((id) => id.trim()).filter(Boolean);
  excluded.forEach((id) => { if (id === "class-max-lessons") el(id).value = 6; if (id === "teacher-max-lessons") el(id).value = 6; });
  if (form.id === "teacher-form") Array.from(el("teacher-unavailable-slots").options).forEach((opt) => (opt.selected = false));
  if (form.id === "condition-form") updateConditionFieldVisibility();
  updateUnavailableSlotsSummary();
}

function bindForms() {
  const bindSubmit = (formId, path, payloadBuilder) => {
    const formNode = el(formId, false);
    if (!formNode) return;
    formNode.addEventListener("submit", async (e) => {
    e.preventDefault(); const form = e.target; const btn = form.querySelector("button[type='submit']"); setLoading(btn, true, "Saving...");
    try { await api(path, { method: "POST", body: JSON.stringify(payloadBuilder()) }); notify(form.dataset.successMessage || "Saved successfully"); resetFormWithDefaults(form); await refresh(); }
    catch (error) { notify(error.message, "error"); } finally { setLoading(btn, false); }
  });
  };

  bindSubmit("class-form", "/classes", () => ({ name: el("class-name").value.trim(), max_lessons_per_day: Number(el("class-max-lessons").value) }));
  bindSubmit("subject-form", "/subjects", () => ({ name: el("subject-name").value.trim(), hours_per_week: Number(el("subject-hours").value) }));
  bindSubmit("teacher-form", "/teachers", () => ({ name: el("teacher-name").value.trim(), subjects: el("teacher-subjects").value.split(",").map((s) => s.trim()).filter(Boolean), unavailable_slots: getUnavailableSlots(), max_lessons_per_day: Number(el("teacher-max-lessons").value) }));
  bindSubmit("slot-form", "/slots", () => ({ slot: el("slot-value").value.trim() }));
  bindSubmit("condition-form", "/conditions", () => {
    const condition_type = el("condition-type").value;
    const payload = { condition_type, text: el("condition-text").value.trim(), teacher_name: null, class_name: null, subject_name: null, slot: null };
    if (condition_type === "teacher_unavailable") { payload.teacher_name = el("condition-teacher-name").value.trim(); payload.slot = el("condition-slot").value; }
    if (condition_type === "class_unavailable") { payload.class_name = el("condition-class-name").value.trim(); payload.slot = el("condition-slot").value; }
    if (condition_type === "subject_morning_preference") payload.subject_name = el("condition-subject-name").value.trim();
    if (condition_type === "avoid_subject_repeat") { payload.subject_name = el("condition-subject-name").value.trim(); payload.class_name = el("condition-class-name").value.trim() || null; }
    return payload;
  });

  bindSubmit("time-settings-form", "/time-settings", () => ({ day_start_time: el("day-start-time").value, day_end_time: el("day-end-time").value, lesson_duration_minutes: Number(el("lesson-duration-minutes").value), break_duration_minutes: Number(el("break-duration-minutes").value), working_days: el("working-days").value.split(",").map((d) => d.trim()).filter(Boolean), lunch_break_start: el("lunch-break-start").value || null, lunch_break_end: el("lunch-break-end").value || null }));

  on("condition-type", "change", updateConditionFieldVisibility);
  ["condition-teacher-name", "condition-class-name", "condition-subject-name"].forEach((id) => on(id, "input", buildConditionText));
  on("condition-slot", "change", buildConditionText);
  on("teacher-unavailable-slots", "change", updateUnavailableSlotsSummary);
  on("generate-btn", "click", runGenerateSchedule);
  on("load-demo-btn", "click", () => runAction("load-demo-btn", "/schedule/load-demo", "Loading..."));
  on("load-large-demo-btn", "click", runLoadLargeDemo);
  on("clear-btn", "click", () => runAction("clear-btn", "/schedule/clear", "Clearing..."));
  on("schedule-view-mode", "change", (e) => { scheduleState.viewMode = e.target.value; syncScheduleFiltersUI(); renderScheduleTableFromState(); });
  on("schedule-class-filter", "change", (e) => { scheduleState.selectedClass = e.target.value; renderScheduleTableFromState(); });
  on("schedule-teacher-filter", "change", (e) => { scheduleState.selectedTeacher = e.target.value; renderScheduleTableFromState(); });
  on("schedule-search", "input", (e) => { scheduleState.search = e.target.value.trim().toLowerCase(); renderScheduleTableFromState(); });
  bindViewNavigation();
}

function updateUnavailableSlotsSummary() { const selected = getUnavailableSlots(); el("teacher-unavailable-selected").textContent = selected.length ? `Créneaux sélectionnés : ${selected.join(", ")}` : "Aucun créneau sélectionné."; }
async function runAction(buttonId, path, loadingLabel) { const btn = el(buttonId); setLoading(btn, true, loadingLabel); try { const res = await api(path, { method: "POST" }); notify(res.message || "Done", res.success === false ? "error" : "success"); await refresh(); if (path === "/schedule/clear") el("demo-summary").textContent = "Aucune démo volumineuse chargée."; } catch (error) { notify(error.message, "error"); } finally { setLoading(btn, false); } }
async function runGenerateSchedule() { const btn = el("generate-btn"); setLoading(btn, true, "Generating..."); try { const res = await api("/schedule/generate", { method: "POST" }); if (res.success === false) throw new Error(res.message || "Failed to generate schedule"); lastQualityMetrics = res; renderQualityMetrics(lastQualityMetrics); await refreshScheduleTable(); notify(res.message || "Emploi du temps généré avec succès"); el("generation-status").textContent = `Dernière génération : ${new Date().toLocaleString("fr-FR")}.`; } catch (error) { notify(`Échec de génération : ${error.message}`, "error"); } finally { setLoading(btn, false); } }
async function runLoadLargeDemo() {
  const btn = el("load-large-demo-btn");
  setLoading(btn, true, "Chargement en cours...");
  const startedAt = performance.now();
  try {
    const res = await api("/schedule/load-large-demo", { method: "POST" });
    await refresh();
    const stats = res.stats || {};
    const elapsedMs = Math.round(performance.now() - startedAt);
    el("demo-summary").textContent = `Grosse démo chargée : ${stats.classes || 0} classes, ${stats.teachers || 0} professeurs, ${stats.subjects || 0} matières, ${stats.slots || 0} créneaux (${elapsedMs} ms).`;
    el("generation-status").textContent = "Démo prête : vous pouvez générer immédiatement un emploi du temps.";
    notify("Grosse démo chargée avec succès.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setLoading(btn, false);
  }
}
function renderQualityMetrics(metrics) { /* unchanged */ const card = el("quality-card"); const hasMetrics = Number.isFinite(metrics?.quality_score); if (!hasMetrics) { card.className = "quality-card quality-unknown"; el("quality-score").textContent = "--/100"; el("quality-conflicts").textContent = "-"; el("quality-gaps").textContent = "-"; el("quality-repeats").textContent = "-"; el("quality-sequences").textContent = "-"; el("quality-balance").textContent = "-"; return; } const score = Number(metrics.quality_score); const level = score >= 75 ? "good" : score >= 50 ? "average" : "bad"; card.className = `quality-card quality-${level}`; el("quality-score").textContent = `${score}/100`; el("quality-conflicts").textContent = String(metrics.conflicts_count ?? 0); el("quality-gaps").textContent = String(metrics.gaps_count ?? 0); el("quality-repeats").textContent = String(metrics.repeated_subjects_count ?? 0); el("quality-sequences").textContent = String(metrics.long_sequences_count ?? 0); el("quality-balance").textContent = String(metrics.load_balance_status ?? "-"); }
function populateUnavailableSlots(slots) { const select = el("teacher-unavailable-slots"); const currentSelection = new Set(getUnavailableSlots()); select.innerHTML = slots.map((slot) => `<option value="${slot}">${slot}</option>`).join(""); Array.from(select.options).forEach((opt) => { opt.selected = currentSelection.has(opt.value); }); const conditionSlot = el("condition-slot"); conditionSlot.innerHTML = `<option value="">Choisir un créneau</option>${slots.map((slot) => `<option value="${slot}">${slot}</option>`).join("")}`; updateUnavailableSlotsSummary(); }
async function refresh() { const [classes, subjects, teachers, slots, schedule, conditions, timeSettings] = await Promise.all([api("/classes"), api("/subjects"), api("/teachers"), api("/slots"), api("/schedule"), api("/conditions"), api("/time-settings")]); el("count-classes").textContent = classes.length; el("count-subjects").textContent = subjects.length; el("count-teachers").textContent = teachers.length; el("count-slots").textContent = slots.length; fillList("classes-list", classes.map((x) => `${x.name} (max/day: ${x.max_lessons_per_day})`)); fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`)); fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")} | max/day: ${x.max_lessons_per_day} | unavailable: ${x.unavailable_slots.join(", ") || "-"}`)); fillList("slots-list", slots); renderConditionsList(conditions); fillTimeSettingsForm(timeSettings); populateUnavailableSlots(slots); scheduleState.slots = slots; scheduleState.classes = classes.map((c) => c.name); scheduleState.teachers = teachers.map((t) => t.name); scheduleState.schedule = schedule || {}; populateScheduleFilters(); renderScheduleTableFromState(); renderQualityMetrics(lastQualityMetrics || {}); updateConditionFieldVisibility(); }
function fillTimeSettingsForm(timeSettings) { if (!timeSettings) return; el("day-start-time").value = timeSettings.day_start_time; el("day-end-time").value = timeSettings.day_end_time; el("lesson-duration-minutes").value = timeSettings.lesson_duration_minutes; el("break-duration-minutes").value = timeSettings.break_duration_minutes; el("working-days").value = timeSettings.working_days.join(","); el("lunch-break-start").value = timeSettings.lunch_break_start || ""; el("lunch-break-end").value = timeSettings.lunch_break_end || ""; }
function renderConditionsList(conditions) { const list = el("conditions-list"); if (!conditions.length) { list.innerHTML = "<li>-</li>"; return; } list.innerHTML = conditions.map((condition) => `<li class="conditions-item"><span>${condition.text}</span><button data-id="${condition.id}" class="danger">Supprimer</button></li>`).join(""); Array.from(list.querySelectorAll("button[data-id]")).forEach((btn) => { btn.addEventListener("click", async () => { try { await api(`/conditions/${btn.dataset.id}`, { method: "DELETE" }); notify("Condition deleted"); await refresh(); } catch (error) { notify(error.message, "error"); } }); }); }
async function refreshScheduleTable() { const [classes, slots, schedule, teachers] = await Promise.all([api("/classes"), api("/slots"), api("/schedule"), api("/teachers")]); scheduleState.classes = classes.map((c) => c.name); scheduleState.slots = slots; scheduleState.schedule = schedule || {}; scheduleState.teachers = teachers.map((t) => t.name); populateScheduleFilters(); renderScheduleTableFromState(); renderQualityMetrics(lastQualityMetrics || {}); }
function fillList(id, items) { el(id).innerHTML = items.map((x) => `<li>${x}</li>`).join("") || "<li>-</li>"; }
function populateScheduleFilters() {
  const classSelect = el("schedule-class-filter");
  const teacherSelect = el("schedule-teacher-filter");
  classSelect.innerHTML = `<option value="">Choisir une classe</option>${scheduleState.classes.map((name) => `<option value="${name}">${name}</option>`).join("")}`;
  teacherSelect.innerHTML = `<option value="">Choisir un professeur</option>${scheduleState.teachers.map((name) => `<option value="${name}">${name}</option>`).join("")}`;

  const hasScheduleData = Boolean(scheduleState.schedule && Object.keys(scheduleState.schedule).length);
  if (hasScheduleData) {
    if (scheduleState.viewMode === "class" && !scheduleState.selectedClass && scheduleState.classes.length) scheduleState.selectedClass = scheduleState.classes[0];
    if (scheduleState.viewMode === "teacher" && !scheduleState.selectedTeacher && scheduleState.teachers.length) scheduleState.selectedTeacher = scheduleState.teachers[0];
  }

  if (!scheduleState.classes.includes(scheduleState.selectedClass)) scheduleState.selectedClass = "";
  if (!scheduleState.teachers.includes(scheduleState.selectedTeacher)) scheduleState.selectedTeacher = "";
  classSelect.value = scheduleState.selectedClass;
  teacherSelect.value = scheduleState.selectedTeacher;
  syncScheduleFiltersUI();
}


function bindViewNavigation() {
  const navButtons = Array.from(document.querySelectorAll(".view-nav-btn"));
  const views = Array.from(document.querySelectorAll(".app-view"));
  const activateView = (viewId) => {
    views.forEach((view) => view.classList.toggle("active-view", view.id === viewId));
    navButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.view === viewId));
    if (viewId === "results-view") renderScheduleTableFromState();
  };
  navButtons.forEach((btn) => btn.addEventListener("click", () => activateView(btn.dataset.view)));
}

function syncScheduleFiltersUI() {
  const isClassView = scheduleState.viewMode === "class";
  el("schedule-class-filter").disabled = !isClassView;
  el("schedule-teacher-filter").disabled = isClassView;
}

function renderScheduleTableFromState() {
  const table = el("schedule-table");
  const emptyMessage = el("schedule-empty-message");
  const { slots, classes, schedule } = scheduleState;
  if (!classes.length || !slots.length) {
    table.innerHTML = "<tr><td>Ajoutez des classes et des créneaux pour afficher un résultat généré.</td></tr>";
    emptyMessage.textContent = "Sélectionnez une classe ou un professeur.";
    emptyMessage.classList.remove("hidden");
    return;
  }

  const search = scheduleState.search;
  if (scheduleState.viewMode === "class") {
    const selectedClass = scheduleState.selectedClass;
    if (!selectedClass) {
      table.innerHTML = "";
      emptyMessage.textContent = "Sélectionnez une classe ou un professeur.";
      emptyMessage.classList.remove("hidden");
      return;
    }
    if (search && !selectedClass.toLowerCase().includes(search)) {
      table.innerHTML = "";
      emptyMessage.textContent = "Aucun résultat avec cette recherche.";
      emptyMessage.classList.remove("hidden");
      return;
    }
    const head = `<tr><th class="slot-col">Créneau</th><th>${selectedClass}</th></tr>`;
    const rows = slots.map((slot) => {
      const cell = schedule?.[slot]?.[selectedClass];
      return `<tr><td class="slot-col">${slot}</td><td>${cell ? `<div class='cell-subject'>${cell.subject}</div><div class='cell-teacher'>${cell.teacher}</div>` : "<span class='empty-cell'>-</span>"}</td></tr>`;
    }).join("");
    table.innerHTML = head + rows;
    emptyMessage.classList.add("hidden");
    return;
  }

  const selectedTeacher = scheduleState.selectedTeacher;
  if (!selectedTeacher) {
    table.innerHTML = "";
    emptyMessage.textContent = "Sélectionnez une classe ou un professeur.";
    emptyMessage.classList.remove("hidden");
    return;
  }
  if (search && !selectedTeacher.toLowerCase().includes(search)) {
    table.innerHTML = "";
    emptyMessage.textContent = "Aucun résultat avec cette recherche.";
    emptyMessage.classList.remove("hidden");
    return;
  }
  const head = `<tr><th class="slot-col">Créneau</th><th>${selectedTeacher}</th></tr>`;
  const rows = slots.map((slot) => {
    const className = classes.find((name) => schedule?.[slot]?.[name]?.teacher === selectedTeacher);
    const cell = className ? schedule?.[slot]?.[className] : null;
    return `<tr><td class="slot-col">${slot}</td><td>${cell ? `<div class='cell-subject'>${cell.subject}</div><div class='cell-teacher'>Classe: ${className}</div>` : "<span class='empty-cell'>-</span>"}</td></tr>`;
  }).join("");
  table.innerHTML = head + rows;
  emptyMessage.classList.add("hidden");
}

bindForms();
refresh();
