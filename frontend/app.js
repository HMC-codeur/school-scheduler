const API = "";
const scheduleState = {
  slots: [],
  classes: [],
  teachers: [],
  schedule: {},
  selectedClass: "",
  selectedTeacher: "",
  viewMode: "class",
  search: "",
  hasGeneratedSchedule: false,
  isGenerating: false,
  scheduleOptions: [],
  selectedOptionId: null,
  backendStatus: "unknown",
};

const $ = (id) => document.getElementById(id);
const create = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};

async function api(path, requestOptions) {
  const options = requestOptions || {};
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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

function notify(message, type = "success") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${type}`;
  setTimeout(() => (el.className = "toast hidden"), 3500);
}

function setLoading(button, isLoading, text) {
  button.disabled = isLoading;
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.textContent = text;
    return;
  }
  button.textContent = button.dataset.originalText || button.textContent;
}

function getUnavailableSlots() {
  return Array.from($("teacher-unavailable-slots").selectedOptions).map((opt) => opt.value);
}

function updateConditionFieldVisibility() {
  const type = $("condition-type").value;
  document.querySelectorAll("[data-condition-field]").forEach((el) => {
    const types = el.dataset.conditionField.split(" ");
    el.style.display = types.includes(type) ? "" : "none";
  });
  buildConditionText();
}

function buildConditionText() {
  const type = $("condition-type").value;
  const teacher = $("condition-teacher-name").value.trim();
  const className = $("condition-class-name").value.trim();
  const subject = $("condition-subject-name").value.trim();
  const slot = $("condition-slot").value;
  let text = "Condition personnalisée";
  if (type === "teacher_unavailable") text = `Professeur ${teacher || "(à définir)"} indisponible sur ${slot || "(créneau à définir)"}`;
  if (type === "class_unavailable") text = `Classe ${className || "(à définir)"} indisponible sur ${slot || "(créneau à définir)"}`;
  if (type === "subject_morning_preference") text = `Placer ${subject || "(matière à définir)"} le matin si possible`;
  if (type === "avoid_subject_repeat") text = `Éviter de répéter ${subject || "(matière à définir)"}${className ? ` pour ${className}` : ""} le même jour`;
  $("condition-text").value = text;
}

function updateUnavailableSlotsSummary() {
  const selected = getUnavailableSlots();
  $("teacher-unavailable-selected").textContent = selected.length
    ? `Créneaux sélectionnés : ${selected.join(", ")}`
    : "Aucun créneau sélectionné.";
}

function renderGenerationBanner(message, level = "info") {
  const el = $("generation-status");
  el.textContent = message;
  el.dataset.level = level;
}

function resetFormWithDefaults(form) {
  form.reset();
  const excluded = (form.dataset.resetExclusions || "").split(",").map((id) => id.trim()).filter(Boolean);
  excluded.forEach((id) => {
    if (id === "class-max-lessons") $(id).value = 6;
    if (id === "teacher-max-lessons") $(id).value = 6;
  });
  if (form.id === "teacher-form") {
    Array.from($("teacher-unavailable-slots").options).forEach((opt) => (opt.selected = false));
  }
  if (form.id === "condition-form") updateConditionFieldVisibility();
  updateUnavailableSlotsSummary();
}

function fillList(id, items) {
  const root = $(id);
  if (!items.length) return root.replaceChildren(create("li", "-"));
  root.replaceChildren(...items.map((x) => create("li", x)));
}

function fillTimeSettingsForm(timeSettings) {
  if (!timeSettings) return;
  $("day-start-time").value = timeSettings.day_start_time;
  $("day-end-time").value = timeSettings.day_end_time;
  $("lesson-duration-minutes").value = timeSettings.lesson_duration_minutes;
  $("break-duration-minutes").value = timeSettings.break_duration_minutes;
  $("working-days").value = timeSettings.working_days.join(",");
  $("lunch-break-start").value = timeSettings.lunch_break_start || "";
  $("lunch-break-end").value = timeSettings.lunch_break_end || "";
}

function populateUnavailableSlots(slots) {
  const select = $("teacher-unavailable-slots");
  const currentSelection = new Set(getUnavailableSlots());
  select.replaceChildren(...slots.map((slot) => {
    const opt = create("option", slot);
    opt.value = slot;
    return opt;
  }));
  Array.from(select.options).forEach((opt) => { opt.selected = currentSelection.has(opt.value); });

  const conditionSlotOptions = $("condition-slot-options");
  const opts = slots.map((slot) => {
    const opt = create("option");
    opt.value = slot;
    return opt;
  });
  conditionSlotOptions.replaceChildren(...opts);
  updateUnavailableSlotsSummary();
}

function renderConditionsList(conditions) {
  const list = $("conditions-list");
  if (!conditions.length) return list.replaceChildren(create("li", "-"));

  const items = conditions.map((condition) => {
    const li = create("li", undefined, "conditions-item");
    const span = create("span", `${condition.text || condition.description || "Condition"} [${condition.condition_type}]${condition.hard === false ? " (préférence)" : " (obligatoire)"}`);
    const btn = create("button", "Supprimer", "danger");
    btn.dataset.id = String(condition.id);
    li.append(span, btn);
    return li;
  });

  list.replaceChildren(...items);
  Array.from(list.querySelectorAll("button[data-id]")).forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/conditions/${btn.dataset.id}`, { method: "DELETE" });
        notify("Condition supprimée.");
        await refresh();
      } catch (error) {
        notify(error.message, "error");
      }
    });
  });
}

function populateScheduleFilters() {
  const classSelect = $("schedule-class-filter");
  const teacherSelect = $("schedule-teacher-filter");

  const classDefault = create("option", "Choisir une classe");
  classDefault.value = "";
  classSelect.replaceChildren(classDefault, ...scheduleState.classes.map((name) => {
    const option = create("option", name);
    option.value = name;
    return option;
  }));

  const teacherDefault = create("option", "Choisir un professeur");
  teacherDefault.value = "";
  teacherSelect.replaceChildren(teacherDefault, ...scheduleState.teachers.map((name) => {
    const option = create("option", name);
    option.value = name;
    return option;
  }));

  if (!scheduleState.classes.includes(scheduleState.selectedClass)) scheduleState.selectedClass = "";
  if (!scheduleState.teachers.includes(scheduleState.selectedTeacher)) scheduleState.selectedTeacher = "";
  classSelect.value = scheduleState.selectedClass;
  teacherSelect.value = scheduleState.selectedTeacher;
  syncScheduleFiltersUI();
}

function syncScheduleFiltersUI() {
  const isClassView = scheduleState.viewMode === "class";
  $("schedule-class-filter").disabled = !isClassView;
  $("schedule-teacher-filter").disabled = isClassView;
}

function renderQualityMetrics(metrics) {
  const card = $("quality-card");
  const hasMetrics = Number.isFinite(metrics?.quality_score);
  if (!hasMetrics) {
    card.className = "quality-card quality-unknown";
    $("quality-score").textContent = "--/100";
    $("quality-conflicts").textContent = "-";
    $("quality-gaps").textContent = "-";
    $("quality-repeats").textContent = "-";
    $("quality-sequences").textContent = "-";
    $("quality-balance").textContent = "-";
    return;
  }

  const score = Number(metrics.quality_score);
  const level = score >= 75 ? "good" : score >= 50 ? "average" : "bad";
  card.className = `quality-card quality-${level}`;
  $("quality-score").textContent = `${score}/100`;
  $("quality-conflicts").textContent = String(metrics.conflicts_count ?? 0);
  $("quality-gaps").textContent = String(metrics.gaps_count ?? 0);
  $("quality-repeats").textContent = String(metrics.repeated_subjects_count ?? 0);
  $("quality-sequences").textContent = String(metrics.long_sequences_count ?? 0);
  $("quality-balance").textContent = String(metrics.load_balance_status ?? "-");
}

async function selectScheduleOption(optionId) {
  await api(`/schedule/options/${encodeURIComponent(optionId)}/select`, { method: "POST" });
  scheduleState.selectedOptionId = optionId;
  const selected = scheduleState.scheduleOptions.find((option) => option.id === optionId);
  if (selected?.schedule) scheduleState.schedule = selected.schedule;
  renderQualityMetrics(selected || {});
  renderScheduleOptions();
  renderScheduleTableFromState();
}

function renderScheduleOptions() {
  const root = $("schedule-options");
  const options = Array.isArray(scheduleState.scheduleOptions) ? scheduleState.scheduleOptions : [];
  if (!options.length) {
    root.replaceChildren();
    return;
  }
  const cards = options.map((option) => {
    const card = create("article", undefined, `schedule-option-card${scheduleState.selectedOptionId === option.id ? " selected" : ""}`);
    card.append(
      create("h4", option.label || option.id || "Option"),
      create("p", option.short_description || "Option de planning générée automatiquement."),
      create("p", `Score qualité : ${option.quality_score ?? "--"}/100`),
    );
    const btn = create("button", scheduleState.selectedOptionId === option.id ? "Option sélectionnée" : "Voir cette option");
    btn.disabled = scheduleState.selectedOptionId === option.id;
    btn.addEventListener("click", () => selectScheduleOption(option.id).catch((error) => notify(error.message, "error")));
    card.append(btn);
    return card;
  });
  root.replaceChildren(...cards);
}

function renderScheduleTableFromState() {
  const table = $("schedule-table");
  const emptyMessage = $("schedule-empty-message");
  const { slots, classes, schedule } = scheduleState;

  const setEmptyMessage = (msg) => {
    emptyMessage.textContent = msg;
    emptyMessage.classList.remove("hidden");
  };
  const hideEmptyMessage = () => emptyMessage.classList.add("hidden");
  const emptyCell = () => create("span", "-", "empty-cell");

  if (!scheduleState.hasGeneratedSchedule) {
    table.replaceChildren();
    setEmptyMessage("Aucun emploi du temps généré pour le moment.");
    return;
  }

  if (!classes.length || !slots.length) {
    table.replaceChildren();
    setEmptyMessage("Ajoutez des classes et des créneaux pour afficher un planning.");
    return;
  }

  const search = scheduleState.search;
  const selected = scheduleState.viewMode === "class" ? scheduleState.selectedClass : scheduleState.selectedTeacher;
  if (!selected) {
    table.replaceChildren();
    setEmptyMessage("Planning généré : choisissez une classe ou un professeur.");
    return;
  }

  if (search && !selected.toLowerCase().includes(search)) {
    table.replaceChildren();
    setEmptyMessage("Aucun résultat avec cette recherche.");
    return;
  }

  const headerRow = create("tr");
  headerRow.append(create("th", "Créneau", "slot-col"), create("th", selected));

  const rows = slots.map((slot) => {
    const tr = create("tr");
    const slotTd = create("td", slot, "slot-col");
    const td = create("td");

    let subject = "";
    let secondary = "";
    if (scheduleState.viewMode === "class") {
      const cell = schedule?.[slot]?.[selected];
      subject = cell?.subject || "";
      secondary = cell?.teacher || "";
    } else {
      const className = classes.find((name) => schedule?.[slot]?.[name]?.teacher === selected);
      const cell = className ? schedule?.[slot]?.[className] : null;
      subject = cell?.subject || "";
      secondary = className ? `Classe: ${className}` : "";
    }

    if (!subject) {
      td.append(emptyCell());
    } else {
      td.append(create("div", subject, "cell-subject"), create("div", secondary, "cell-teacher"));
    }

    tr.append(slotTd, td);
    return tr;
  });

  table.replaceChildren(headerRow, ...rows);
  hideEmptyMessage();
}

async function refreshScheduleTable() {
  const [classes, slots, schedule, teachers, scheduleOptions] = await Promise.all([api("/classes"), api("/slots"), api("/schedule"), api("/teachers"), api("/schedule/options").catch(() => [])]);
  scheduleState.classes = classes.map((c) => c.name);
  scheduleState.slots = slots;
  scheduleState.schedule = schedule || {};
  scheduleState.teachers = teachers.map((t) => t.name);
  scheduleState.hasGeneratedSchedule = Object.keys(scheduleState.schedule).length > 0;
  scheduleState.scheduleOptions = Array.isArray(scheduleOptions) ? scheduleOptions : [];
  scheduleState.selectedOptionId = scheduleState.scheduleOptions[0]?.id || null;
  const selected = scheduleState.scheduleOptions.find((option) => option.id === scheduleState.selectedOptionId);
  renderQualityMetrics(selected || {});
  renderScheduleOptions();
  populateScheduleFilters();
  renderScheduleTableFromState();
}

async function refresh() {
  const [classes, subjects, teachers, slots, schedule, conditions, timeSettings, scheduleOptions] = await Promise.all([
    api("/classes"),
    api("/subjects"),
    api("/teachers"),
    api("/slots"),
    api("/schedule"),
    api("/conditions"),
    api("/time-settings"),
    api("/schedule/options").catch(() => []),
  ]);

  $("count-classes").textContent = classes.length;
  $("count-subjects").textContent = subjects.length;
  $("count-teachers").textContent = teachers.length;
  $("count-slots").textContent = slots.length;

  fillList("classes-list", classes.map((x) => `${x.name} (max/jour: ${x.max_lessons_per_day})`));
  fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`));
  fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")} | max/jour: ${x.max_lessons_per_day} | indisponibilités: ${x.unavailable_slots.join(", ") || "-"}`));
  fillList("slots-list", slots);

  renderConditionsList(conditions);
  fillTimeSettingsForm(timeSettings);
  populateUnavailableSlots(slots);

  scheduleState.slots = slots;
  scheduleState.classes = classes.map((c) => c.name);
  scheduleState.teachers = teachers.map((t) => t.name);
  scheduleState.schedule = schedule || {};
  scheduleState.hasGeneratedSchedule = Object.keys(scheduleState.schedule).length > 0;
  scheduleState.scheduleOptions = Array.isArray(scheduleOptions) ? scheduleOptions : [];
  scheduleState.selectedOptionId = scheduleState.scheduleOptions[0]?.id || null;
  renderScheduleOptions();

  populateScheduleFilters();
  renderScheduleTableFromState();
  renderQualityMetrics({});
  updateConditionFieldVisibility();
}

async function runAction(buttonId, path, loadingLabel) {
  const btn = $(buttonId);
  setLoading(btn, true, loadingLabel);
  try {
    const res = await api(path, { method: "POST" });
    notify(res.message || "Opération terminée.", res.success === false ? "error" : "success");
    await refresh();
    if (path === "/schedule/clear") {
      $("demo-summary").textContent = "Aucune démo volumineuse chargée.";
      renderGenerationBanner("Données effacées. Vous pouvez recharger une démo ou saisir vos données.", "info");
      scheduleState.hasGeneratedSchedule = false;
      renderScheduleTableFromState();
    }
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setLoading(btn, false);
  }
}

async function runLoadLargeDemo() {
  const btn = $("load-large-demo-btn");
  setLoading(btn, true, "Chargement en cours...");
  const startedAt = performance.now();
  try {
    const res = await api("/schedule/load-large-demo", { method: "POST" });
    await refresh();
    const stats = res.stats || {};
    const elapsedMs = Math.round(performance.now() - startedAt);
    $("demo-summary").textContent = `Grosse démo chargée : ${stats.classes || 0} classes, ${stats.teachers || 0} professeurs, ${stats.subjects || 0} matières, ${stats.slots || 0} créneaux (${elapsedMs} ms).`;
    renderGenerationBanner("Démo volumineuse prête. Sélectionnez ensuite une vue classe/professeur après génération.", "success");
    notify("Grosse démo chargée avec succès.");
  } catch (error) {
    renderGenerationBanner(`Erreur de chargement démo : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    setLoading(btn, false);
  }
}

async function runGenerateSchedule() {
  const btn = $("generate-btn");
  setLoading(btn, true, "Génération...");
  scheduleState.isGenerating = true;
  renderGenerationBanner("Génération en cours...", "loading");
  try {
    const res = await api("/schedule/generate", { method: "POST" });
    if (res.success === false) throw new Error(res.message || "Échec de génération");
    renderQualityMetrics(res);
    await refreshScheduleTable();
    scheduleState.hasGeneratedSchedule = true;
    renderGenerationBanner(`Dernière génération réussie le ${new Date().toLocaleString("fr-FR")}.`, "success");
    notify(res.message || "Emploi du temps généré avec succès");
  } catch (error) {
    renderGenerationBanner(`Échec de génération : ${error.message}`, "error");
    notify(`Échec de génération : ${error.message}`, "error");
  } finally {
    scheduleState.isGenerating = false;
    setLoading(btn, false);
  }
}

function bindForms() {
  const bindSubmit = (formId, path, payloadBuilder) => $(formId).addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector("button[type='submit']");
    setLoading(btn, true, "Enregistrement...");
    try {
      await api(path, { method: "POST", body: JSON.stringify(payloadBuilder()) });
      notify(form.dataset.successMessage || "Enregistré.");
      resetFormWithDefaults(form);
      await refresh();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setLoading(btn, false);
    }
  });

  bindSubmit("class-form", "/classes", () => ({ name: $("class-name").value.trim(), max_lessons_per_day: Number($("class-max-lessons").value) }));
  bindSubmit("subject-form", "/subjects", () => ({ name: $("subject-name").value.trim(), hours_per_week: Number($("subject-hours").value) }));
  bindSubmit("teacher-form", "/teachers", () => ({ name: $("teacher-name").value.trim(), subjects: $("teacher-subjects").value.split(",").map((s) => s.trim()).filter(Boolean), unavailable_slots: getUnavailableSlots(), max_lessons_per_day: Number($("teacher-max-lessons").value) }));
  bindSubmit("slot-form", "/slots", () => ({ slot: $("slot-value").value.trim() }));
  bindSubmit("condition-form", "/conditions", () => {
    const condition_type = $("condition-type").value;
    const description = $("condition-text").value.trim();
    const payload = { condition_type, text: description, description, hard: true };

    if (condition_type === "teacher_unavailable") {
      payload.teacher_name = $("condition-teacher-name").value.trim();
      payload.slot = $("condition-slot").value;
      if (!payload.teacher_name) throw new Error("Veuillez saisir un professeur pour cette condition.");
      if (!payload.slot) throw new Error("Veuillez choisir un créneau pour cette condition.");
      payload.target_id = payload.teacher_name;
      payload.slot_id = payload.slot;
    }

    if (condition_type === "class_unavailable") {
      payload.class_name = $("condition-class-name").value.trim();
      payload.slot = $("condition-slot").value;
      if (!payload.class_name) throw new Error("Veuillez saisir une classe pour cette condition.");
      if (!payload.slot) throw new Error("Veuillez choisir un créneau pour cette condition.");
      payload.target_id = payload.class_name;
      payload.slot_id = payload.slot;
    }

    if (condition_type === "subject_morning_preference" || condition_type === "avoid_subject_repeat") {
      payload.subject_name = $("condition-subject-name").value.trim();
      if (!payload.subject_name) throw new Error("Veuillez saisir une matière pour cette condition.");
      payload.target_id = payload.subject_name;
    }

    if (condition_type === "avoid_subject_repeat") payload.class_name = $("condition-class-name").value.trim() || null;
    return payload;
  });
  bindSubmit("time-settings-form", "/time-settings", () => ({
    day_start_time: $("day-start-time").value,
    day_end_time: $("day-end-time").value,
    lesson_duration_minutes: Number($("lesson-duration-minutes").value),
    break_duration_minutes: Number($("break-duration-minutes").value),
    working_days: $("working-days").value.split(",").map((d) => d.trim()).filter(Boolean),
    lunch_break_start: $("lunch-break-start").value || null,
    lunch_break_end: $("lunch-break-end").value || null,
  }));

  $("condition-type").addEventListener("change", updateConditionFieldVisibility);
  ["condition-teacher-name", "condition-class-name", "condition-subject-name", "condition-slot"].forEach((id) => $(id).addEventListener("input", buildConditionText));
  $("teacher-unavailable-slots").addEventListener("change", updateUnavailableSlotsSummary);

  $("generate-btn").addEventListener("click", runGenerateSchedule);
  $("load-demo-btn").addEventListener("click", () => runAction("load-demo-btn", "/schedule/load-demo", "Chargement..."));
  $("load-large-demo-btn").addEventListener("click", runLoadLargeDemo);
  $("clear-btn").addEventListener("click", () => runAction("clear-btn", "/schedule/clear", "Suppression..."));

  $("schedule-view-mode").addEventListener("change", (e) => { scheduleState.viewMode = e.target.value; syncScheduleFiltersUI(); renderScheduleTableFromState(); });
  $("schedule-class-filter").addEventListener("change", (e) => { scheduleState.selectedClass = e.target.value; renderScheduleTableFromState(); });
  $("schedule-teacher-filter").addEventListener("change", (e) => { scheduleState.selectedTeacher = e.target.value; renderScheduleTableFromState(); });
  $("schedule-search").addEventListener("input", (e) => { scheduleState.search = e.target.value.trim().toLowerCase(); renderScheduleTableFromState(); });
}

bindForms();
refresh().catch((error) => {
  renderGenerationBanner(`Erreur au chargement initial : ${error.message}`, "error");
  notify(error.message, "error");
});
