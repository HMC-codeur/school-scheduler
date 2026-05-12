const API = "";
const scheduleState = { slots: [], classes: [], teachers: [], schedule: {}, selectedClass: "", selectedTeacher: "", viewMode: "class", search: "" };

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Request failed");
  }
  return response.json().catch(() => ({}));
}

function notify(message, type = "success") { const el = document.getElementById("toast"); el.textContent = message; el.className = `toast ${type}`; setTimeout(() => (el.className = "toast hidden"), 3000); }
function setLoading(button, isLoading, text) { button.disabled = isLoading; if (isLoading) { button.dataset.originalText = button.textContent; button.textContent = text; } else { button.textContent = button.dataset.originalText || button.textContent; } }
function getUnavailableSlots() { return Array.from(document.getElementById("teacher-unavailable-slots").selectedOptions).map((opt) => opt.value); }
function validateNonEmpty(value, field) { if (!value || !value.trim()) throw new Error(`${field} is required.`); }

function updateConditionFieldVisibility() {
  const type = document.getElementById("condition-type").value;
  document.querySelectorAll("[data-condition-field]").forEach((el) => {
    const types = el.dataset.conditionField.split(" ");
    el.style.display = types.includes(type) ? "" : "none";
  });
  buildConditionText();
}

function buildConditionText() {
  const type = document.getElementById("condition-type").value;
  const teacher = document.getElementById("condition-teacher-name").value.trim();
  const className = document.getElementById("condition-class-name").value.trim();
  const subject = document.getElementById("condition-subject-name").value.trim();
  const slot = document.getElementById("condition-slot").value;
  let text = "Condition personnalisée";
  if (type === "teacher_unavailable") text = `Professeur ${teacher || "(à définir)"} indisponible sur ${slot || "(créneau à définir)"}`;
  if (type === "class_unavailable") text = `Classe ${className || "(à définir)"} indisponible sur ${slot || "(créneau à définir)"}`;
  if (type === "subject_morning_preference") text = `Placer ${subject || "(matière à définir)"} le matin si possible`;
  if (type === "avoid_subject_repeat") text = `Éviter de répéter ${subject || "(matière à définir)"}${className ? ` pour ${className}` : ""} le même jour`;
  document.getElementById("condition-text").value = text;
}

function resetFormWithDefaults(form) {
  form.reset();
  const excluded = (form.dataset.resetExclusions || "").split(",").map((id) => id.trim()).filter(Boolean);
  excluded.forEach((id) => { if (id === "class-max-lessons") document.getElementById(id).value = 6; if (id === "teacher-max-lessons") document.getElementById(id).value = 6; });
  if (form.id === "teacher-form") Array.from(document.getElementById("teacher-unavailable-slots").options).forEach((opt) => (opt.selected = false));
  if (form.id === "condition-form") updateConditionFieldVisibility();
  updateUnavailableSlotsSummary();
}

function bindForms() {
  const bindSubmit = (formId, path, payloadBuilder) => document.getElementById(formId).addEventListener("submit", async (e) => {
    e.preventDefault(); const form = e.target; const btn = form.querySelector("button[type='submit']"); setLoading(btn, true, "Saving...");
    try { await api(path, { method: "POST", body: JSON.stringify(payloadBuilder()) }); notify(form.dataset.successMessage || "Saved successfully"); resetFormWithDefaults(form); await refresh(); }
    catch (error) { notify(error.message, "error"); } finally { setLoading(btn, false); }
  });

  bindSubmit("class-form", "/classes", () => ({ name: document.getElementById("class-name").value.trim(), max_lessons_per_day: Number(document.getElementById("class-max-lessons").value) }));
  bindSubmit("subject-form", "/subjects", () => ({ name: document.getElementById("subject-name").value.trim(), hours_per_week: Number(document.getElementById("subject-hours").value) }));
  bindSubmit("teacher-form", "/teachers", () => ({ name: document.getElementById("teacher-name").value.trim(), subjects: document.getElementById("teacher-subjects").value.split(",").map((s) => s.trim()).filter(Boolean), unavailable_slots: getUnavailableSlots(), max_lessons_per_day: Number(document.getElementById("teacher-max-lessons").value) }));
  bindSubmit("slot-form", "/slots", () => ({ slot: document.getElementById("slot-value").value.trim() }));
  bindSubmit("condition-form", "/conditions", () => {
    const condition_type = document.getElementById("condition-type").value;
    const payload = { condition_type, text: document.getElementById("condition-text").value.trim(), teacher_name: null, class_name: null, subject_name: null, slot: null };
    if (condition_type === "teacher_unavailable") { payload.teacher_name = document.getElementById("condition-teacher-name").value.trim(); payload.slot = document.getElementById("condition-slot").value; }
    if (condition_type === "class_unavailable") { payload.class_name = document.getElementById("condition-class-name").value.trim(); payload.slot = document.getElementById("condition-slot").value; }
    if (condition_type === "subject_morning_preference") payload.subject_name = document.getElementById("condition-subject-name").value.trim();
    if (condition_type === "avoid_subject_repeat") { payload.subject_name = document.getElementById("condition-subject-name").value.trim(); payload.class_name = document.getElementById("condition-class-name").value.trim() || null; }
    return payload;
  });

  bindSubmit("time-settings-form", "/time-settings", () => ({ day_start_time: document.getElementById("day-start-time").value, day_end_time: document.getElementById("day-end-time").value, lesson_duration_minutes: Number(document.getElementById("lesson-duration-minutes").value), break_duration_minutes: Number(document.getElementById("break-duration-minutes").value), working_days: document.getElementById("working-days").value.split(",").map((d) => d.trim()).filter(Boolean), lunch_break_start: document.getElementById("lunch-break-start").value || null, lunch_break_end: document.getElementById("lunch-break-end").value || null }));

  document.getElementById("condition-type").addEventListener("change", updateConditionFieldVisibility);
  ["condition-teacher-name", "condition-class-name", "condition-subject-name", "condition-slot"].forEach((id) => document.getElementById(id).addEventListener("input", buildConditionText));
  document.getElementById("teacher-unavailable-slots").addEventListener("change", updateUnavailableSlotsSummary);
  document.getElementById("generate-btn").addEventListener("click", runGenerateSchedule);
  document.getElementById("load-demo-btn").addEventListener("click", () => runAction("load-demo-btn", "/schedule/load-demo", "Loading..."));
  document.getElementById("load-large-demo-btn").addEventListener("click", runLoadLargeDemo);
  document.getElementById("clear-btn").addEventListener("click", () => runAction("clear-btn", "/schedule/clear", "Clearing..."));
  document.getElementById("schedule-view-mode").addEventListener("change", (e) => { scheduleState.viewMode = e.target.value; syncScheduleFiltersUI(); renderScheduleTableFromState(); });
  document.getElementById("schedule-class-filter").addEventListener("change", (e) => { scheduleState.selectedClass = e.target.value; renderScheduleTableFromState(); });
  document.getElementById("schedule-teacher-filter").addEventListener("change", (e) => { scheduleState.selectedTeacher = e.target.value; renderScheduleTableFromState(); });
  document.getElementById("schedule-search").addEventListener("input", (e) => { scheduleState.search = e.target.value.trim().toLowerCase(); renderScheduleTableFromState(); });
}

function updateUnavailableSlotsSummary() { const selected = getUnavailableSlots(); document.getElementById("teacher-unavailable-selected").textContent = selected.length ? `Créneaux sélectionnés : ${selected.join(", ")}` : "Aucun créneau sélectionné."; }
async function runAction(buttonId, path, loadingLabel) { const btn = document.getElementById(buttonId); setLoading(btn, true, loadingLabel); try { const res = await api(path, { method: "POST" }); notify(res.message || "Done", res.success === false ? "error" : "success"); await refresh(); if (path === "/schedule/clear") document.getElementById("demo-summary").textContent = "Aucune démo volumineuse chargée."; } catch (error) { notify(error.message, "error"); } finally { setLoading(btn, false); } }
async function runGenerateSchedule() { const btn = document.getElementById("generate-btn"); setLoading(btn, true, "Generating..."); try { const res = await api("/schedule/generate", { method: "POST" }); if (res.success === false) throw new Error(res.message || "Failed to generate schedule"); renderQualityMetrics(res); await refreshScheduleTable(); notify(res.message || "Emploi du temps généré avec succès"); document.getElementById("generation-status").textContent = `Dernière génération : ${new Date().toLocaleString("fr-FR")}.`; } catch (error) { notify(`Échec de génération : ${error.message}`, "error"); } finally { setLoading(btn, false); } }
async function runLoadLargeDemo() {
  const btn = document.getElementById("load-large-demo-btn");
  setLoading(btn, true, "Chargement en cours...");
  const startedAt = performance.now();
  try {
    const res = await api("/schedule/load-large-demo", { method: "POST" });
    await refresh();
    const stats = res.stats || {};
    const elapsedMs = Math.round(performance.now() - startedAt);
    document.getElementById("demo-summary").textContent = `Grosse démo chargée : ${stats.classes || 0} classes, ${stats.teachers || 0} professeurs, ${stats.subjects || 0} matières, ${stats.slots || 0} créneaux (${elapsedMs} ms).`;
    document.getElementById("generation-status").textContent = "Démo prête : vous pouvez générer immédiatement un emploi du temps.";
    notify("Grosse démo chargée avec succès.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setLoading(btn, false);
  }
}
function renderQualityMetrics(metrics) { /* unchanged */ const card = document.getElementById("quality-card"); const hasMetrics = Number.isFinite(metrics?.quality_score); if (!hasMetrics) { card.className = "quality-card quality-unknown"; document.getElementById("quality-score").textContent = "--/100"; document.getElementById("quality-conflicts").textContent = "-"; document.getElementById("quality-gaps").textContent = "-"; document.getElementById("quality-repeats").textContent = "-"; document.getElementById("quality-sequences").textContent = "-"; document.getElementById("quality-balance").textContent = "-"; return; } const score = Number(metrics.quality_score); const level = score >= 75 ? "good" : score >= 50 ? "average" : "bad"; card.className = `quality-card quality-${level}`; document.getElementById("quality-score").textContent = `${score}/100`; document.getElementById("quality-conflicts").textContent = String(metrics.conflicts_count ?? 0); document.getElementById("quality-gaps").textContent = String(metrics.gaps_count ?? 0); document.getElementById("quality-repeats").textContent = String(metrics.repeated_subjects_count ?? 0); document.getElementById("quality-sequences").textContent = String(metrics.long_sequences_count ?? 0); document.getElementById("quality-balance").textContent = String(metrics.load_balance_status ?? "-"); }
function populateUnavailableSlots(slots) { const select = document.getElementById("teacher-unavailable-slots"); const currentSelection = new Set(getUnavailableSlots()); select.innerHTML = slots.map((slot) => `<option value="${slot}">${slot}</option>`).join(""); Array.from(select.options).forEach((opt) => { opt.selected = currentSelection.has(opt.value); }); const conditionSlot = document.getElementById("condition-slot"); conditionSlot.innerHTML = `<option value="">Choisir un créneau</option>${slots.map((slot) => `<option value="${slot}">${slot}</option>`).join("")}`; updateUnavailableSlotsSummary(); }
async function refresh() { const [classes, subjects, teachers, slots, schedule, conditions, timeSettings] = await Promise.all([api("/classes"), api("/subjects"), api("/teachers"), api("/slots"), api("/schedule"), api("/conditions"), api("/time-settings")]); document.getElementById("count-classes").textContent = classes.length; document.getElementById("count-subjects").textContent = subjects.length; document.getElementById("count-teachers").textContent = teachers.length; document.getElementById("count-slots").textContent = slots.length; fillList("classes-list", classes.map((x) => `${x.name} (max/day: ${x.max_lessons_per_day})`)); fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`)); fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")} | max/day: ${x.max_lessons_per_day} | unavailable: ${x.unavailable_slots.join(", ") || "-"}`)); fillList("slots-list", slots); renderConditionsList(conditions); fillTimeSettingsForm(timeSettings); populateUnavailableSlots(slots); scheduleState.slots = slots; scheduleState.classes = classes.map((c) => c.name); scheduleState.teachers = teachers.map((t) => t.name); scheduleState.schedule = schedule || {}; populateScheduleFilters(); renderScheduleTableFromState(); renderQualityMetrics({}); updateConditionFieldVisibility(); }
function fillTimeSettingsForm(timeSettings) { if (!timeSettings) return; document.getElementById("day-start-time").value = timeSettings.day_start_time; document.getElementById("day-end-time").value = timeSettings.day_end_time; document.getElementById("lesson-duration-minutes").value = timeSettings.lesson_duration_minutes; document.getElementById("break-duration-minutes").value = timeSettings.break_duration_minutes; document.getElementById("working-days").value = timeSettings.working_days.join(","); document.getElementById("lunch-break-start").value = timeSettings.lunch_break_start || ""; document.getElementById("lunch-break-end").value = timeSettings.lunch_break_end || ""; }
function renderConditionsList(conditions) { const list = document.getElementById("conditions-list"); if (!conditions.length) { list.innerHTML = "<li>-</li>"; return; } list.innerHTML = conditions.map((condition) => `<li class="conditions-item"><span>${condition.text}</span><button data-id="${condition.id}" class="danger">Supprimer</button></li>`).join(""); Array.from(list.querySelectorAll("button[data-id]")).forEach((btn) => { btn.addEventListener("click", async () => { try { await api(`/conditions/${btn.dataset.id}`, { method: "DELETE" }); notify("Condition deleted"); await refresh(); } catch (error) { notify(error.message, "error"); } }); }); }
async function refreshScheduleTable() { const [classes, slots, schedule, teachers] = await Promise.all([api("/classes"), api("/slots"), api("/schedule"), api("/teachers")]); scheduleState.classes = classes.map((c) => c.name); scheduleState.slots = slots; scheduleState.schedule = schedule || {}; scheduleState.teachers = teachers.map((t) => t.name); populateScheduleFilters(); renderScheduleTableFromState(); }
function fillList(id, items) { document.getElementById(id).innerHTML = items.map((x) => `<li>${x}</li>`).join("") || "<li>-</li>"; }
function populateScheduleFilters() {
  const classSelect = document.getElementById("schedule-class-filter");
  const teacherSelect = document.getElementById("schedule-teacher-filter");
  classSelect.innerHTML = `<option value="">Choisir une classe</option>${scheduleState.classes.map((name) => `<option value="${name}">${name}</option>`).join("")}`;
  teacherSelect.innerHTML = `<option value="">Choisir un professeur</option>${scheduleState.teachers.map((name) => `<option value="${name}">${name}</option>`).join("")}`;
  if (!scheduleState.classes.includes(scheduleState.selectedClass)) scheduleState.selectedClass = "";
  if (!scheduleState.teachers.includes(scheduleState.selectedTeacher)) scheduleState.selectedTeacher = "";
  classSelect.value = scheduleState.selectedClass;
  teacherSelect.value = scheduleState.selectedTeacher;
  syncScheduleFiltersUI();
}

function syncScheduleFiltersUI() {
  const isClassView = scheduleState.viewMode === "class";
  document.getElementById("schedule-class-filter").disabled = !isClassView;
  document.getElementById("schedule-teacher-filter").disabled = isClassView;
}

function renderScheduleTableFromState() {
  const table = document.getElementById("schedule-table");
  const emptyMessage = document.getElementById("schedule-empty-message");
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
