function setActiveView(viewId) {
  const target = $(viewId) ? viewId : "dashboard-view";
  scheduleState.activeView = target;
  document.querySelectorAll(".view-section").forEach((section) => {
    section.classList.toggle("active", section.id === target);
  });
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === target);
  });
  const section = $(target);
  $("page-title").textContent = section?.dataset.title || "Dashboard";
  $("page-subtitle").textContent = section?.dataset.subtitle || "";
}

function initializeNavigation() {
  document.querySelectorAll(".nav-link[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => setActiveView(btn.dataset.view));
  });
  setActiveView(scheduleState.activeView);
}

function renderApiDebugPanel() {
  const debug = scheduleState.apiDebug || {};
  const setText = (id, value) => {
    const el = $(id);
    if (el) el.textContent = value || "-";
  };
  setText("api-debug-url", debug.apiBaseUrl || (typeof getApiBaseUrl === "function" ? getApiBaseUrl() : ""));
  setText("api-debug-status", debug.status || scheduleState.backendStatus || "unknown");
  setText("api-debug-endpoint", debug.lastEndpoint || "");
  setText("api-debug-error", debug.lastError || "");
  setText("api-debug-health-response", debug.healthResponse || "");
}

async function checkBackendHealth() {
  const pill = $("backend-status-pill");
  if (!pill) return;
  const startedAt = Date.now();
  updateApiDebug({ apiBaseUrl: getApiBaseUrl(), status: "checking", lastEndpoint: "/health", lastError: "" });
  try {
    const response = await apiFetch("/health");
    const result = response instanceof Response ? await parseApiPayload(response) : response;
    const status = result?.status || result?.data?.status;
    const connected = status === "ok" || (result?.ok === true && result?.data?.status === "ok");
    updateApiDebug({ healthResponse: formatApiDebugPayload(result) });
    if (!connected) {
      throw new Error(`Réponse /health inattendue: ${formatApiDebugPayload(result) || "vide"}`);
    }
    scheduleState.backendStatus = "ok";
    pill.textContent = "Connecté au serveur";
    pill.className = "status-pill status-success";
    updateApiDebug({ status: "connected", lastEndpoint: "/health", lastError: "" });
  } catch (error) {
    scheduleState.backendStatus = "error";
    const slow = Date.now() - startedAt > 7000;
    const message = slow
      ? "Le serveur Render peut être en train de se réveiller. Réessaie dans quelques secondes."
      : error.message || "Serveur inaccessible";
    pill.textContent = "Serveur inaccessible";
    pill.className = "status-pill status-error";
    updateApiDebug({ status: "error", lastError: message });
  }
}

const refreshBackendStatus = checkBackendHealth;

function updateDashboardMetrics(metrics = scheduleState.latestMetrics || {}) {
  const score = Number(metrics?.quality_score);
  const hasScore = Number.isFinite(score);
  const label = scoreLabel(hasScore ? score : null);
  $("dashboard-score").textContent = hasScore ? `${score}/100` : "--";
  $("dashboard-score-badge").textContent = label.label;
  $("dashboard-score-badge").className = `score-badge ${label.className}`;
  $("generation-score-summary").textContent = hasScore ? `${score}/100` : "--/100";
  $("generation-score-label").textContent = label.label;
  $("generation-score-label").className = `score-badge ${label.className}`;
  $("dashboard-conflicts").textContent = String(metrics?.conflicts_count ?? "-");
  const scheduled = metrics?.scheduled_sessions;
  const required = metrics?.required_sessions;
  $("dashboard-sessions").textContent = scheduled != null && required != null ? `${scheduled}/${required}` : "-";
  $("dashboard-generation-time").textContent = metrics?.generation_time_ms != null ? `${metrics.generation_time_ms} ms` : "-";
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
  if (type === "subject_prefer_morning") text = `Placer ${subject || "(matière à définir)"} le matin si possible`;
  if (type === "teacher_prefer_morning") text = `Placer ${teacher || "(professeur à définir)"} le matin si possible`;
  if (type === "avoid_subject_repeat_same_day") text = `Éviter de répéter ${subject || "(matière à définir)"}${className ? ` pour ${className}` : ""} le même jour`;
  if (type === "avoid_long_sequence") text = `Éviter les longues séries de cours consécutifs${className ? ` pour ${className}` : ""}${teacher ? ` pour ${teacher}` : ""}`;
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
  const mirror = $("generation-status-mirror");
  if (mirror) {
    mirror.textContent = message;
    mirror.dataset.level = level;
  }
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

function populateConditionOptions() {
  const fillDatalist = (id, values) => {
    $(id).replaceChildren(...values.map((value) => {
      const opt = create("option");
      opt.value = value;
      return opt;
    }));
  };
  fillDatalist("condition-class-options", scheduleState.classes);
  fillDatalist("condition-teacher-options", scheduleState.teachers);
  fillDatalist("condition-subject-options", scheduleState.subjects);
}

function requireKnownValue(value, values, label) {
  if (!value) throw new Error(`Veuillez saisir ${label}.`);
  if (!values.includes(value)) throw new Error(`${label} inconnu : ${value}`);
}

function describeConditionTarget(condition) {
  const parts = [];
  if (condition.teacher_name) parts.push(`Professeur: ${condition.teacher_name}`);
  if (condition.class_name) parts.push(`Classe: ${condition.class_name}`);
  if (condition.subject_name) parts.push(`Matière: ${condition.subject_name}`);
  if (condition.slot) parts.push(`Créneau: ${condition.slot}`);
  return parts.join(" · ") || "Cible globale";
}

function renderConstraintDiagnosis(diagnosis) {
  const root = $("constraint-diagnosis");
  if (!diagnosis) {
    root.replaceChildren();
    return;
  }
  const constraintIssues = (diagnosis.blocking_issues || []).filter((issue) => issue.toLowerCase().includes("contrainte"));
  if (!constraintIssues.length) {
    root.replaceChildren(create("p", "Diagnostic contraintes : aucun blocage détecté."));
    return;
  }
  root.replaceChildren(...constraintIssues.map((issue) => create("p", issue, "blocking")));
}

function renderDiagnostics(diagnosis) {
  scheduleState.latestDiagnosis = diagnosis || null;
  const summary = $("diagnostics-summary");
  const details = $("diagnostics-details");
  if (!diagnosis) {
    summary.className = "panel diagnostics-summary";
    summary.replaceChildren(create("h3", "Diagnostic"), create("p", "Diagnostic indisponible.", "hint"));
    details.replaceChildren(create("p", "Aucun détail disponible.", "hint"));
    return;
  }

  const canGenerate = diagnosis.can_generate === true;
  const stats = diagnosis.stats || {};
  const blocking = diagnosis.blocking_issues || [];
  const warnings = diagnosis.warnings || [];
  summary.className = `panel diagnostics-summary ${canGenerate ? "ready" : "blocked"}`;
  summary.replaceChildren(
    create("h3", canGenerate ? "Prêt à générer" : "À corriger avant génération"),
    create(
      "p",
      canGenerate
        ? "Les données semblent cohérentes pour générer un planning."
        : `${blocking.length || 1} point${blocking.length > 1 ? "s" : ""} bloque${blocking.length > 1 ? "nt" : ""} la génération.`,
      canGenerate ? "diagnostic-card" : "diagnostic-card blocking",
    ),
  );

  const statsDetails = document.createElement("details");
  statsDetails.open = true;
  statsDetails.append(create("summary", "Synthèse des volumes"));
  const statsList = create("ul");
  [
    `Classes : ${stats.classes ?? 0}`,
    `Professeurs : ${stats.teachers ?? 0}`,
    `Matières : ${stats.subjects ?? 0}`,
    `Créneaux : ${stats.slots ?? 0}`,
    `Conditions : ${stats.conditions ?? 0}`,
    `Sessions requises : ${stats.required_sessions ?? 0}`,
    `Places classe disponibles : ${stats.available_class_sessions ?? 0}`,
  ].forEach((line) => statsList.append(create("li", line)));
  statsDetails.append(statsList);

  const blockingDetails = document.createElement("details");
  blockingDetails.open = !canGenerate;
  blockingDetails.append(create("summary", "Blocages"));
  const blockingList = create("div");
  blockingList.className = "diagnostics-details";
  if (!blocking.length) blockingList.append(create("p", "Aucun blocage détecté.", "diagnostic-card"));
  blocking.forEach((issue) => blockingList.append(create("p", issue, "diagnostic-card blocking")));
  blockingDetails.append(blockingList);

  const warningDetails = document.createElement("details");
  warningDetails.append(create("summary", "Avertissements"));
  const warningList = create("div");
  warningList.className = "diagnostics-details";
  if (!warnings.length) warningList.append(create("p", "Aucun avertissement.", "diagnostic-card"));
  warnings.forEach((warning) => warningList.append(create("p", warning, "diagnostic-card warning")));
  warningDetails.append(warningList);

  details.replaceChildren(statsDetails, blockingDetails, warningDetails);
}

function renderConditionsList(conditions) {
  const list = $("conditions-list");
  if (!conditions.length) return list.replaceChildren(create("p", "Aucune condition ajoutée.", "hint"));

  const items = conditions.map((condition) => {
    const li = create("article", undefined, "conditions-item");
    const isPreference = condition.hard === false || PREFERENCE_CONDITIONS.has(condition.condition_type);
    const main = create("div", undefined, "condition-main");
    const meta = create("div", undefined, "condition-meta");
    const badge = create("span", isPreference ? "Préférence" : "Obligatoire", `condition-badge ${isPreference ? "soft" : "hard"}`);
    meta.append(
      badge,
      create("span", CONDITION_LABELS[condition.condition_type] || condition.condition_type, "hint"),
      create("span", describeConditionTarget(condition), "hint"),
    );
    main.append(
      meta,
      create("strong", condition.text || condition.description || "Condition"),
    );
    const btn = create("button", "Supprimer", "danger");
    btn.dataset.id = String(condition.id);
    li.append(main, btn);
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

  normalizeScheduleFilters();
  classSelect.value = scheduleState.selectedClass;
  teacherSelect.value = scheduleState.selectedTeacher;
  const repairTarget = $("repair-target");
  if (repairTarget && !repairTarget.value) repairTarget.value = getDefaultRepairTarget($("repair-type")?.value || "repair_teacher");
  syncScheduleFiltersUI();
}

function syncScheduleFiltersUI() {
  normalizeScheduleFilters();
  const isClassView = scheduleState.viewMode === "class";
  $("schedule-class-filter").disabled = !isClassView;
  $("schedule-teacher-filter").disabled = isClassView;
}

function normalizeScheduleFilters() {
  if (!["class", "teacher"].includes(scheduleState.viewMode)) scheduleState.viewMode = "class";
  if (!scheduleState.classes.includes(scheduleState.selectedClass)) scheduleState.selectedClass = "";
  if (!scheduleState.teachers.includes(scheduleState.selectedTeacher)) scheduleState.selectedTeacher = "";

  const modeSelect = $("schedule-view-mode");
  const classSelect = $("schedule-class-filter");
  const teacherSelect = $("schedule-teacher-filter");
  if (modeSelect) modeSelect.value = scheduleState.viewMode;
  if (classSelect) classSelect.value = scheduleState.selectedClass;
  if (teacherSelect) teacherSelect.value = scheduleState.selectedTeacher;
}

function renderQualityMetrics(metrics) {
  const card = $("quality-card");
  const hasMetrics = Number.isFinite(metrics?.quality_score);
  scheduleState.latestMetrics = hasMetrics ? { ...(scheduleState.latestMetrics || {}), ...metrics } : null;
  updateDashboardMetrics(scheduleState.latestMetrics || {});
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

function renderScoreBreakdown(option) {
  const root = $("score-breakdown-list");
  const technicalRoot = $("score-technical-list");
  const breakdown = Array.isArray(option?.score_breakdown) ? option.score_breakdown : [];
  $("score-debug-option").textContent = scheduleState.selectedOptionId || "-";
  $("score-debug-options-count").textContent = String(scheduleState.scheduleOptions.length || 0);
  $("score-debug-signature").textContent = option?.schedule_signature || "-";
  $("score-debug-items").textContent = String(breakdown.length);
  $("score-debug-received").textContent = Number.isFinite(Number(option?.quality_score)) ? String(Number(option.quality_score)) : "--";
  $("score-final").textContent = Number.isFinite(Number(option?.quality_score)) ? `${Number(option.quality_score)}/100` : "--/100";
  if (!breakdown.length) {
    root.replaceChildren(create("li", "Aucun détail de score disponible pour cette option.", "hint"));
    technicalRoot.replaceChildren(create("li", "Aucun détail technique disponible.", "hint"));
    return;
  }

  const visibleItems = breakdown.filter((item) => Number(item?.points || 0) !== 0);
  const grouped = summarizeScoreBreakdown(visibleItems);
  const summaryItems = grouped.map((item) => {
    const points = Number(item.points || 0);
    const prefix = points >= 0 ? "+" : "";
    const li = create("li", undefined, points >= 0 ? "score-positive" : "score-negative");
    li.append(
      create("strong", `${prefix}${points} ${item.category}`),
      create("span", item.summary, "score-summary-text"),
    );
    return li;
  });
  root.replaceChildren(...summaryItems.length ? summaryItems : [create("li", "Aucun impact affichable : seuls des ajustements à 0 point ont été reçus.", "hint")]);

  const technicalItems = visibleItems
    .slice()
    .sort((a, b) => Math.abs(Number(b?.points || 0)) - Math.abs(Number(a?.points || 0)))
    .slice(0, 15)
    .map((item) => {
      const points = Number(item?.points || 0);
      const prefix = points >= 0 ? "+" : "";
      const li = create("li", undefined, points >= 0 ? "score-positive" : "score-negative");
      const raw = Number(item?.raw_points ?? points);
      const count = Number(item?.count || 1);
      li.textContent = `${prefix}${points} ${item?.label || item?.rule || "Règle appliquée"} · count=${count} · raw=${raw}`;
      return li;
    });
  technicalRoot.replaceChildren(...technicalItems.length ? technicalItems : [create("li", "Aucun détail non nul à afficher.", "hint")]);
}

function getScoreCategory(item) {
  if (item?.category) return String(item.category);
  const rule = String(item?.rule || "");
  return SCORE_CATEGORY_LABELS[rule] || (Number(item?.points || 0) > 0 ? "Bonus" : "Autres pénalités");
}

function summarizeScoreBreakdown(items) {
  const groups = new Map();
  items.forEach((item) => {
    const category = getScoreCategory(item);
    if (!groups.has(category)) {
      groups.set(category, {
        category,
        points: 0,
        raw_points: 0,
        count: 0,
        labels: [],
        rules: new Set(),
      });
    }
    const group = groups.get(category);
    const points = Number(item?.points || 0);
    group.points += points;
    group.raw_points += Number(item?.raw_points ?? points);
    group.count += Number(item?.count || 1);
    group.rules.add(String(item?.rule || ""));
    if (item?.label && group.labels.length < 3) group.labels.push(String(item.label));
  });

  return Array.from(groups.values())
    .map((group) => ({ ...group, summary: summarizeScoreGroup(group) }))
    .sort((a, b) => {
      const categoryOrder = ["Conflits", "Sessions non placées", "Trous classes", "Trous professeurs", "Longues séries", "Préférences respectées", "Bonus"];
      const aIndex = categoryOrder.indexOf(a.category);
      const bIndex = categoryOrder.indexOf(b.category);
      if (aIndex !== bIndex) return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex);
      return Math.abs(b.points) - Math.abs(a.points);
    });
}

function summarizeScoreGroup(group) {
  const count = Math.max(0, Number(group.count || 0));
  if (group.category === "Trous classes") {
    return `${count} trou${count > 1 ? "s" : ""} détecté${count > 1 ? "s" : ""} côté classes.`;
  }
  if (group.category === "Trous professeurs") {
    return count > 3 ? "Plusieurs trous significatifs détectés côté professeurs." : `${count} trou${count > 1 ? "s" : ""} détecté${count > 1 ? "s" : ""} côté professeurs.`;
  }
  if (group.category === "Longues séries") {
    return `${count} série${count > 1 ? "s" : ""} longue${count > 1 ? "s" : ""} à surveiller.`;
  }
  if (group.category === "Conflits") {
    return `${count} conflit${count > 1 ? "s" : ""} détecté${count > 1 ? "s" : ""}.`;
  }
  if (group.category === "Sessions non placées") {
    return `${count} session${count > 1 ? "s" : ""} non placée${count > 1 ? "s" : ""}.`;
  }
  if (group.category === "Préférences respectées") {
    return group.labels[0] || "Préférence respectée.";
  }
  if (group.category === "Bonus") {
    return group.labels[0] || "Bonus de qualité appliqué.";
  }
  return group.labels[0] || "Règles techniques regroupées.";
}

async function selectScheduleOption(optionId) {
  await api(`/schedule/options/${encodeURIComponent(optionId)}/select`, { method: "POST" });
  const [scheduleOptions, schedule] = await Promise.all([api("/schedule/options"), api("/schedule")]);
  const selected = applyActiveSchedule(schedule, scheduleOptions, "option", optionId);
  resetRepairState();
  renderScheduleOptions();
  renderQualityMetrics(selected || {});
  renderScoreBreakdown(selected);
  renderScheduleTableFromState();
  await loadScheduleVersions();
}

function renderScheduleOptions() {
  const root = $("schedule-options");
  const options = Array.isArray(scheduleState.scheduleOptions) ? scheduleState.scheduleOptions : [];
  if (!options.length) {
    root.replaceChildren(create("p", "Aucune option générée.", "hint"));
    return;
  }
  const cards = options.map((option) => {
    const card = create("article", undefined, `schedule-option-card${scheduleState.selectedOptionId === option.id ? " selected" : ""}`);
    card.append(
      create("h4", option.id || option.label || "Option"),
      create("p", `Score : ${option.quality_score ?? "--"}/100`),
      create("p", `Statut : ${option.selected ? "sélectionnée" : "non sélectionnée"}`),
      create("p", `Signature : ${option.schedule_signature || "-"}`),
      create("p", `Description : ${option.description || "Option générée automatiquement."}`),
    );
    const btn = create("button", scheduleState.selectedOptionId === option.id ? "Option sélectionnée" : "Choisir cette option");
    btn.disabled = scheduleState.selectedOptionId === option.id;
    btn.addEventListener("click", () => selectScheduleOption(option.id).catch((error) => notify(error.message, "error")));
    card.append(btn);
    return card;
  });
  root.replaceChildren(...cards);
}

function formatScheduleVersionReason(reason) {
  const labels = {
    generation: "Génération",
    option_select: "Option sélectionnée",
    repair_commit: "Réparation appliquée",
    accepted_proposal: "Proposition acceptée",
    rollback: "Rollback",
  };
  return labels[reason] || reason || "Version";
}

async function loadScheduleVersions() {
  const versions = await api("/schedule/versions").catch((error) => {
    notify(`Historique indisponible : ${error.message}`, "error");
    return [];
  });
  scheduleState.scheduleVersions = Array.isArray(versions) ? versions : [];
  renderScheduleVersions();
}

function renderScheduleVersions() {
  const root = $("schedule-versions");
  if (!root) return;
  const versions = Array.isArray(scheduleState.scheduleVersions) ? scheduleState.scheduleVersions : [];
  if (!versions.length) {
    root.replaceChildren(create("p", "Aucune version de planning enregistrée.", "hint"));
    return;
  }

  const items = versions.map((version) => {
    const article = create("article", undefined, "schedule-version-item");
    const main = create("div");
    const reason = version.reason || version.type;
    main.append(create("h4", formatScheduleVersionReason(reason)));
    const meta = create("div", undefined, "schedule-version-meta");
    [
      `Date : ${formatDateTime(version.created_at)}`,
      `Actif : ${version.active_schedule_size ?? 0}`,
      `Précédent : ${version.previous_schedule_size ?? 0}`,
      `Rollback : ${version.has_previous_schedule ? "oui" : "non"}`,
      version.option_id ? `Option : ${version.option_id}` : "",
      version.proposal_id ? `Proposal : ${version.proposal_id}` : "",
    ].filter(Boolean).forEach((line) => meta.append(create("span", line)));
    main.append(meta);
    article.append(main);

    if (version.has_previous_schedule) {
      const btn = create("button", "Restaurer");
      btn.dataset.versionId = version.id;
      btn.addEventListener("click", () => rollbackScheduleVersion(version.id, btn));
      article.append(btn);
    } else {
      article.append(create("span", "Non restaurable", "hint"));
    }
    return article;
  });
  root.replaceChildren(...items);
}

async function rollbackScheduleVersion(versionId, button) {
  if (!versionId) return;
  setLoading(button, true, "Restauration...");
  try {
    const res = await api(`/schedule/versions/${encodeURIComponent(versionId)}/rollback`, { method: "POST" });
    resetRepairState();
    await refreshScheduleTable();
    renderGenerationBanner("Planning restauré depuis l'historique.", "success");
    notify(res.message || "Planning restauré.");
  } catch (error) {
    notify(`Rollback impossible : ${error.message}`, "error");
  } finally {
    setLoading(button, false);
  }
}

function renderScheduleTableFromState() {
  const table = $("schedule-table");
  const emptyMessage = $("schedule-empty-message");
  if (!table || !emptyMessage) return;
  normalizeScheduleFilters();
  const { slots, classes } = scheduleState;
  const schedule = getDisplayedSchedule();
  const repairDiffMap = buildRepairDiffMap();

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
  const availableTargets = scheduleState.viewMode === "class" ? scheduleState.classes : scheduleState.teachers;
  const targetLabel = scheduleState.viewMode === "class" ? "classe" : "professeur";
  if (!selected) {
    table.replaceChildren();
    setEmptyMessage("Planning généré : choisissez une classe ou un professeur.");
    return;
  }

  if (!availableTargets.includes(selected)) {
    table.replaceChildren();
    setEmptyMessage(`Le ${targetLabel} sélectionné n'existe plus. Choisissez une autre cible.`);
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

    const repairState = getRepairCellState(repairDiffMap, slot, selected, scheduleState.viewMode);
    if (!subject) {
      td.append(emptyCell());
    } else {
      td.append(create("div", subject, "cell-subject"), create("div", secondary, "cell-teacher"));
    }
    renderRepairOverlay(td, repairState);

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
  scheduleState.teachers = teachers.map((t) => t.name);
  const selected = applyActiveSchedule(schedule, scheduleOptions, "refresh");
  renderScheduleOptions();
  renderQualityMetrics(selected || {});
  renderScoreBreakdown(selected);
  populateScheduleFilters();
  renderScheduleTableFromState();
  await loadScheduleVersions();
}

async function refresh() {
  const [classes, subjects, teachers, slots, schedule, conditions, timeSettings, scheduleOptions, diagnosis] = await Promise.all([
    api("/classes"),
    api("/subjects"),
    api("/teachers"),
    api("/slots"),
    api("/schedule"),
    api("/conditions"),
    api("/time-settings"),
    api("/schedule/options").catch(() => []),
    api("/schedule/diagnose").catch(() => null),
  ]);

  $("count-classes").textContent = classes.length;
  $("count-subjects").textContent = subjects.length;
  $("count-teachers").textContent = teachers.length;
  $("count-slots").textContent = slots.length;
  $("count-conditions").textContent = conditions.length;

  fillList("classes-list", classes.map((x) => `${x.name} (max/jour: ${x.max_lessons_per_day})`));
  fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`));
  fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")} | max/jour: ${x.max_lessons_per_day} | indisponibilités: ${x.unavailable_slots.join(", ") || "-"}`));
  fillList("slots-list", slots);

  renderConditionsList(conditions);
  renderConstraintDiagnosis(diagnosis);
  renderDiagnostics(diagnosis);
  fillTimeSettingsForm(timeSettings);
  populateUnavailableSlots(slots);

  scheduleState.slots = slots;
  scheduleState.classes = classes.map((c) => c.name);
  scheduleState.teachers = teachers.map((t) => t.name);
  scheduleState.subjects = subjects.map((s) => s.name);
  const selected = applyActiveSchedule(schedule, scheduleOptions, "refresh");
  renderScheduleOptions();

  populateScheduleFilters();
  populateConditionOptions();
  renderScheduleTableFromState();
  renderQualityMetrics(selected || {});
  renderScoreBreakdown(selected);
  updateConditionFieldVisibility();
  await loadScheduleVersions();
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
      scheduleState.scheduleOptions = [];
      scheduleState.selectedOptionId = null;
      resetScheduleVersionState();
      resetRepairState();
      renderScheduleTableFromState();
      await loadScheduleVersions();
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

async function runLoadPilotDemo() {
  const btn = $("load-pilot-demo-btn");
  setLoading(btn, true, "Chargement en cours...");
  const startedAt = performance.now();
  try {
    const res = await api("/schedule/load-pilot-demo", { method: "POST" });
    scheduleState.schedule = {};
    scheduleState.hasGeneratedSchedule = false;
    scheduleState.scheduleOptions = [];
    scheduleState.selectedOptionId = null;
    scheduleState.latestMetrics = null;
    scheduleState.scheduleVersions = [];
    resetScheduleVersionState();
    resetRepairState();
    renderScheduleOptions();
    renderScheduleVersions();
    renderScheduleTableFromState();

    await refresh();
    const stats = res.stats || {};
    const elapsedMs = Math.round(performance.now() - startedAt);
    $("demo-summary").textContent = `Démo pilote chargée : ${stats.classes || 0} classes, ${stats.teachers || 0} professeurs, contraintes réalistes (${elapsedMs} ms).`;
    renderGenerationBanner("Démo pilote réaliste prête. Lancez la génération pour produire les options.", "success");
    notify("Démo pilote chargée avec succès.");
  } catch (error) {
    renderGenerationBanner(`Erreur de chargement démo pilote : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    setLoading(btn, false);
  }
}

async function runGenerateSchedule() {
  if (scheduleState.isGenerating) {
    notify("Génération déjà en cours.", "info");
    return;
  }
  const buttons = [$("generate-btn"), $("generate-btn-secondary")];
  setButtonsLoading(buttons, true, "Génération...");
  scheduleState.isGenerating = true;
  renderGenerationBanner("Génération en cours...", "loading");
  try {
    const res = await api("/schedule/generate", { method: "POST" });
    if (res.success === false) throw new Error(res.message || "Échec de génération");
    scheduleState.latestMetrics = res;
    resetRepairState();
    renderQualityMetrics(res);
    await refreshScheduleTable();
    scheduleState.hasGeneratedSchedule = true;
    scheduleState.scheduleVersion.source = "generation";
    renderGenerationBanner(`Dernière génération réussie le ${new Date().toLocaleString("fr-FR")}.`, "success");
    notify(res.message || "Emploi du temps généré avec succès");
  } catch (error) {
    await refreshScheduleTable().catch(() => {});
    scheduleState.hasGeneratedSchedule = false;
    renderQualityMetrics({});
    renderScoreBreakdown(null);
    renderGenerationBanner(`Échec de génération : ${error.message}`, "error");
    notify(`Échec de génération : ${error.message}`, "error");
  } finally {
    scheduleState.isGenerating = false;
    setButtonsLoading(buttons, false);
  }
}

async function exportSchedule(format) {
  const path = format === "pdf" ? "/schedule/export/pdf" : format === "json" ? "/schedule/export/json" : "/schedule/export/csv";
  let response;
  try {
    response = await apiFetch(path);
  } catch (error) {
    throw new Error(error.message || "Aucun planning à exporter.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = format === "pdf" ? "school-schedule.pdf" : format === "json" ? "school-schedule.json" : "school-schedule.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  notify(`Export ${format.toUpperCase()} prêt.`);
}

async function readImportResponse(response) {
  const payload = await response.json().catch(() => null);
  if (response.ok) return payload || {};
  console.error("Excel import request failed", response.status, payload);
  const error = new Error(apiErrorMessage(payload || {}, response.status));
  error.payload = payload;
  error.status = response.status;
  throw error;
}

function selectedExcelFile() {
  const fileInput = $("excel-import-file");
  const file = fileInput.files?.[0];
  if (!file) {
    throw new Error("Sélectionnez un fichier Excel.");
  }
  return file;
}

function excelFormData(includeSheetName = false) {
  const file = selectedExcelFile();
  const formData = new FormData();
  formData.append("file", file);
  const sheetName = $("excel-sheet-name").value.trim();
  if (sheetName) formData.append("sheet_name", sheetName);
  if (includeSheetName) {
    [
      ["layout_type", "excel-layout-type"],
      ["header_row", "excel-header-row"],
      ["day_row", "excel-day-row"],
      ["day_column", "excel-day-column"],
      ["time_row", "excel-time-row"],
      ["time_column", "excel-time-column"],
    ].forEach(([field, id]) => {
      const element = $(id);
      const value = element?.value?.trim();
      if (value && value !== "auto") formData.append(field, value);
    });
  }
  return formData;
}

async function analyzeExcelImport() {
  const event = arguments[0];
  if (event?.preventDefault) event.preventDefault();
  const button = $("excel-analyze-btn");
  setLoading(button, true, "Analyse...");
  $("excel-import-status").textContent = "Analyse du fichier...";
  $("excel-import-status").dataset.level = "loading";
  try {
    const debugCompare = $("excel-debug-compare")?.checked ? "?debug_compare=true" : "";
    const response = await apiFetch(`/imports/excel/analyze${debugCompare}`, {
      method: "POST",
      body: excelFormData(false),
    });
    const analysis = await readImportResponse(response);
    scheduleState.importAnalysis = analysis;
    renderExcelAnalysis(analysis);
    updateExcelMvpCommitControls(analysis);
    const summary = analysis.summary || {};
    $("excel-import-status").textContent = [
      `Lignes lues : ${summary.total_rows_read ?? 0}`,
      `Ligne d'en-tête détectée : ${summary.detected_header_row ?? "-"}`,
      `Lignes de données détectées : ${summary.data_rows_detected ?? 0}`,
      `Lignes importables : ${summary.imported_rows_count ?? 0}`,
      `Lignes ignorées : ${summary.ignored_empty_rows ?? 0}`,
    ].join(" · ");
    $("excel-import-status").dataset.level = (analysis.diagnostics?.blocking || []).length ? "warning" : "success";
    notify("Analyse terminée.");
  } catch (error) {
    scheduleState.importAnalysis = null;
    const message = sanitizeExcelError(error.message);
    renderExcelAnalysis(null, { ...error, message });
    updateExcelMvpCommitControls(null);
    $("excel-import-status").textContent = message;
    $("excel-import-status").dataset.level = "error";
    notify(message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function previewExcelImport(event) {
  event.preventDefault();
  const button = $("excel-preview-btn");

  setLoading(button, true, "Preview...");
  $("excel-import-status").textContent = "Lecture du fichier...";
  $("excel-import-status").dataset.level = "loading";
  try {
    const response = await apiFetch("/schedule/import/excel/preview", {
      method: "POST",
      body: excelFormData(true),
    });
    const preview = await readImportResponse(response);
    scheduleState.importPreview = preview;
    renderExcelPreview(preview);
    notify(preview.can_commit ? "Preview prête." : "Preview avec erreurs.", preview.can_commit ? "success" : "error");
  } catch (error) {
    scheduleState.importPreview = null;
    const message = sanitizeExcelError(error.message);
    renderExcelPreview(null, message);
    notify(message, "error");
  } finally {
    setLoading(button, false);
  }
}

function sanitizeExcelError(message) {
  const text = String(message || "");
  if (text.includes("expected <class") || text.includes("openpyxl.styles.fills.Fill")) {
    return "Impossible de lire ce fichier Excel. Essayez de le réenregistrer en .xlsx depuis Excel ou Google Sheets.";
  }
  return text;
}

async function commitExcelMvpImport(event) {
  const button = event?.currentTarget || $("excel-mvp-commit-btn");
  const analysis = scheduleState.importAnalysis;
  if (!analysis?.import_id) {
    notify("Lancez une analyse avant l'import.", "error");
    return;
  }
  setLoading(button, true, "Import...");
  $("excel-import-status").textContent = "Import des données analysées...";
  $("excel-import-status").dataset.level = "loading";
  try {
    const response = await apiFetch(`/imports/excel/${encodeURIComponent(analysis.import_id)}/commit`, {
      method: "POST",
    });
    const payload = await readImportResponse(response);
    const summary = payload.summary || {};
    const message = `${summary.classes_added ?? 0} classes ajoutées, ${summary.teachers_added ?? 0} professeurs ajoutés, ${summary.subjects_added ?? 0} matières ajoutées, ${summary.requirements_added ?? 0} besoins horaires ajoutés.`;
    $("excel-mvp-commit-summary").textContent = message;
    $("excel-import-status").textContent = message;
    $("excel-import-status").dataset.level = "success";
    notify("Import MVP terminé.");
    await refresh();
  } catch (error) {
    const detail = error.payload?.detail || {};
    const message = detail.message || error.message;
    $("excel-mvp-commit-summary").textContent = message;
    $("excel-import-status").textContent = message;
    $("excel-import-status").dataset.level = "error";
    notify(message, "error");
  } finally {
    setLoading(button, false);
  }
}

function intelligenceFormData() {
  const formData = new FormData();
  const file = $("import-intelligence-file")?.files?.[0];
  if (file) formData.append("file", file);
  return formData;
}

async function analyzeImportIntelligence(event) {
  if (event?.preventDefault) event.preventDefault();
  const button = $("import-intelligence-analyze-btn");
  setLoading(button, true, "Analyse...");
  $("import-intelligence-status").textContent = "Analyse intelligente du fichier...";
  try {
    const response = await apiFetch("/imports/analyze", { method: "POST", body: intelligenceFormData() });
    const analysis = await readImportResponse(response);
    scheduleState.importIntelligence = analysis;
    renderImportIntelligence(analysis);
    $("import-intelligence-status").textContent = `${analysis.status} · confiance ${Math.round((analysis.confidence || 0) * 100)}%`;
    $("import-intelligence-apply-btn").disabled = !analysis.import_id || analysis.status === "blocked" || isEmptyImportAnalysis(analysis) || analysis.can_apply === false || analysis.can_commit === false;
    notify("Analyse intelligence terminée.");
  } catch (error) {
    scheduleState.importIntelligence = null;
    renderImportIntelligence(null, error.message);
    $("import-intelligence-status").textContent = error.message;
    $("import-intelligence-apply-btn").disabled = true;
    notify(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function applyImportIntelligence(event) {
  const button = event?.currentTarget || $("import-intelligence-apply-btn");
  const analysis = scheduleState.importIntelligence;
  if (!analysis?.import_id) {
    notify("Lancez une analyse avant d'appliquer.", "error");
    return;
  }
  setLoading(button, true, "Application...");
  try {
    const response = await apiFetch(`/imports/${encodeURIComponent(analysis.import_id)}/apply`, { method: "POST" });
    const payload = await readImportResponse(response);
    const summary = payload.summary || {};
    $("import-intelligence-status").textContent = `${summary.classes_added ?? 0} classes, ${summary.teachers_added ?? 0} professeurs, ${summary.subjects_added ?? 0} matières appliqués.`;
    notify("Données appliquées.");
    await refresh();
  } catch (error) {
    $("import-intelligence-status").textContent = error.message;
    notify(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

function clearImportIntelligence() {
  scheduleState.importIntelligence = null;
  $("import-intelligence-file").value = "";
  $("import-intelligence-apply-btn").disabled = true;
  $("import-intelligence-status").textContent = "Analyse annulée. Aucune donnée appliquée.";
  renderImportIntelligence(null);
}

function renderImportIntelligence(analysis, error = null) {
  const summaryTarget = $("import-intelligence-summary");
  const sheetsTarget = $("import-intelligence-sheets");
  const previewTarget = $("import-intelligence-preview");
  const reviewTarget = $("import-intelligence-review");
  const diagnosticsTarget = $("import-intelligence-diagnostics");
  [summaryTarget, sheetsTarget, previewTarget, reviewTarget, diagnosticsTarget].forEach((target) => { if (target) target.innerHTML = ""; });
  if (error) {
    diagnosticsTarget.appendChild(create("p", error, "hint"));
    return;
  }
  if (!analysis) {
    summaryTarget.appendChild(create("p", "Sélectionnez un fichier pour démarrer l'analyse.", "hint"));
    return;
  }
  const summary = analysis.summary || {};
  const emptyAnalysis = isEmptyImportAnalysis(analysis);
  [
    ["Statut", analysis.status],
    ["Type", analysis.file_type],
    ["Confiance", `${Math.round((analysis.confidence || 0) * 100)}%`],
    ["Feuilles", summary.sheets_count ?? 0],
    ["Classes", summary.classes_count ?? summary.detected_classes ?? 0],
    ["Professeurs", summary.teachers_count ?? summary.detected_teachers ?? 0],
    ["Matières", summary.subjects_count ?? summary.detected_subjects ?? 0],
    ["Besoins", summary.requirements_count ?? 0],
  ].forEach(([label, value]) => summaryTarget.appendChild(importSummaryCard(label, String(value), "muted")));
  if (emptyAnalysis) {
    const warning = create("div", "", "notice danger");
    warning.appendChild(create("strong", "Aucune donnée importable détectée."));
    warning.appendChild(create("p", "Le fichier a été reçu, mais aucune table exploitable n’a été reconnue.", "hint"));
    summaryTarget.appendChild(warning);
  }

  (analysis.sheet_classifications || []).forEach((sheet) => {
    const details = create("details");
    details.open = sheet.needs_human_review;
    details.appendChild(create("summary", `${sheet.sheet_name} · ${sheet.sheet_type} · ${Math.round((sheet.confidence || 0) * 100)}%`));
    details.appendChild(create("p", (sheet.reasons || []).join(" "), "hint"));
    sheetsTarget.appendChild(details);
  });

  const normalized = analysis.normalized_preview || {};
  ["classes", "teachers", "subjects", "requirements", "availability", "constraints"].forEach((key) => {
    const values = Array.isArray(normalized[key]) ? normalized[key] : [];
    const details = create("details");
    details.open = ["classes", "teachers", "subjects", "requirements"].includes(key);
    details.appendChild(create("summary", `${key} · ${values.length}`));
    const list = create("ul");
    values.slice(0, 12).forEach((item) => list.appendChild(create("li", formatIntelligenceItem(item))));
    details.appendChild(list);
    previewTarget.appendChild(details);
  });

  (analysis.human_review || []).forEach((item) => {
    const details = create("details");
    details.open = item.blocking;
    details.appendChild(create("summary", `${item.blocking ? "Bloquant" : "À confirmer"} · ${item.question}`));
    details.appendChild(create("p", item.recommended_value ? `Suggestion : ${item.recommended_value}` : "Validation humaine recommandée.", "hint"));
    reviewTarget.appendChild(details);
  });
  if (!(analysis.human_review || []).length) reviewTarget.appendChild(create("p", "Aucune question humaine obligatoire détectée.", "hint"));

  (analysis.diagnostics || []).slice(0, 20).forEach((item) => {
    const details = create("details");
    details.open = item.severity === "blocking" || item.severity === "error";
    details.appendChild(create("summary", `${item.severity} · ${item.message}`));
    details.appendChild(create("p", [item.sheet_name, item.row ? `ligne ${item.row}` : "", item.suggestion].filter(Boolean).join(" · "), "hint"));
    diagnosticsTarget.appendChild(details);
  });
}

function isEmptyImportAnalysis(analysis) {
  if (!analysis) return false;
  const summary = analysis.summary || {};
  const normalized = analysis.normalized_preview || {};
  const requirements = Array.isArray(normalized.requirements) ? normalized.requirements.length : 0;
  const classes = Array.isArray(normalized.classes) ? normalized.classes.length : 0;
  const teachers = Array.isArray(normalized.teachers) ? normalized.teachers.length : 0;
  const subjects = Array.isArray(normalized.subjects) ? normalized.subjects.length : 0;
  const importableRows = Number(summary.importable_rows ?? summary.requirements_count ?? requirements);
  const classesCount = Number(summary.classes_count ?? summary.detected_classes ?? classes);
  const teachersCount = Number(summary.teachers_count ?? summary.detected_teachers ?? teachers);
  const subjectsCount = Number(summary.subjects_count ?? summary.detected_subjects ?? subjects);
  const confidence = Number(analysis.confidence ?? analysis.confidence_score ?? 0);
  return importableRows === 0 && classesCount === 0 && teachersCount === 0 && subjectsCount === 0 || confidence === 0 || analysis.can_apply === false || analysis.can_commit === false && importableRows === 0;
}

function formatIntelligenceItem(item) {
  if (item?.name) return item.name;
  if (item?.class_name || item?.subject_name) return `${item.class_name || "Classe ?"} · ${item.subject_name || "Matière ?"} · ${item.teacher_name || "Prof ?"} · ${item.weekly_hours ?? "?"}h`;
  if (item?.teacher_name || item?.availability) return `${item.teacher_name || "Prof ?"} · ${item.day || "Jour ?"} · ${item.time || "Horaire ?"} · ${item.availability || "?"}`;
  if (item?.text) return item.text;
  return JSON.stringify(item);
}

function updateExcelMvpCommitControls(analysis) {
  const button = $("excel-mvp-commit-btn");
  const summary = $("excel-mvp-commit-summary");
  if (!button || !summary) return;
  const blocking = analysis?.diagnostics?.blocking || [];
  const emptyAnalysis = isEmptyImportAnalysis(analysis);
  const canCommit = Boolean(analysis?.import_id) && blocking.length === 0 && !emptyAnalysis && analysis?.can_commit !== false && analysis?.can_apply !== false;
  button.hidden = !analysis;
  button.disabled = !canCommit;
  if (!analysis) {
    summary.textContent = "";
  } else if (blocking.length) {
    summary.textContent = "Import bloqué tant que les diagnostics bloquants ne sont pas corrigés.";
  } else if (emptyAnalysis) {
    summary.textContent = "Aucune donnée importable détectée. Le fichier a été reçu, mais aucune table exploitable n’a été reconnue.";
  } else {
    summary.textContent = "Analyse valide. Vous pouvez importer les données.";
  }
}

async function commitExcelImport(mode, dryRun, button) {
  const preview = scheduleState.importPreview;
  if (!preview?.import_id && !Array.isArray(preview?.lessons)) {
    notify("Lancez une preview avant le commit.", "error");
    return;
  }
  setLoading(button, true, dryRun ? "Simulation..." : "Commit...");
  try {
    const response = await api("/schedule/import/excel/commit", {
      method: "POST",
      body: JSON.stringify({
        import_id: preview.import_id,
        lessons: preview.import_id ? undefined : preview.lessons,
        mode,
        dry_run: dryRun,
      }),
    });
    $("excel-import-status").textContent = response.message || "Import terminé.";
    $("excel-import-status").dataset.level = response.success ? "success" : "error";
    notify(response.message || "Import terminé.", response.success ? "success" : "error");
    if (!dryRun && response.success) await refresh();
  } catch (error) {
    $("excel-import-status").textContent = error.message;
    $("excel-import-status").dataset.level = "error";
    notify(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

function renderExcelPreview(preview, errorMessage = "") {
  const status = $("excel-import-status");
  const summary = $("excel-preview-summary");
  const messages = $("excel-preview-messages");
  const table = $("excel-preview-table");
  const canCommit = Boolean(preview?.can_commit);
  ["excel-commit-replace-btn", "excel-commit-merge-btn", "excel-dry-run-btn"].forEach((id) => {
    const btn = $(id);
    if (btn) btn.disabled = !canCommit;
  });

  if (!preview) {
    status.textContent = errorMessage || "Aucun fichier prévisualisé.";
    status.dataset.level = errorMessage ? "error" : "info";
    summary.textContent = "Sélectionnez un fichier .xlsx ou .xlsm.";
    messages.replaceChildren();
    table.replaceChildren();
    return;
  }

  const counts = preview.counts || {};
  status.textContent = preview.can_commit ? "Preview valide, commit possible." : "Preview avec erreurs, commit bloqué.";
  status.dataset.level = preview.can_commit ? "success" : "error";
  summary.textContent = [
    `Fichier: ${preview.filename || "-"}`,
    `Feuille: ${preview.sheet_name || "-"}`,
    `Layout: ${preview.detected_layout || "-"}`,
    `Confiance: ${preview.confidence_score != null ? Math.round(Number(preview.confidence_score) * 100) + "%" : "-"}`,
    `Lignes: ${counts.rows_total ?? counts.lessons ?? 0}`,
    `Leçons: ${counts.lessons_parsed ?? counts.lessons ?? 0}`,
    "Aperçu limité: maximum 100 lignes affichées",
    `Warnings: ${counts.warnings_count ?? (preview.warnings || []).length}`,
    `Errors: ${counts.errors_count ?? (preview.errors || []).length}`,
  ].join(" · ");

  const warningItems = (preview.warnings || []).map((item) => create("p", item, "diagnostic-card warning"));
  const errorItems = (preview.errors || []).map((item) => create("p", item, "diagnostic-card blocking"));
  messages.replaceChildren(...errorItems, ...warningItems);
  renderMappingSuggestions($("excel-mapping-suggestions"), preview.mapping_suggestions, !preview.can_commit);
  renderExcelTechnical(preview);

  const lessons = (preview.lessons || []).slice(0, 100);
  const header = create("tr");
  ["Ligne", "Jour", "Créneau", "Classe", "Matière", "Professeur", "Salle", "Statut"].forEach((label) => header.append(create("th", label)));
  const rows = lessons.map((lesson) => {
    const tr = create("tr");
    [
      lesson.row_index || lesson.row || "",
      lesson.day || "",
      lesson.slot_label || lesson.slot || "",
      lesson.class_name || "",
      lesson.subject_name || lesson.subject || "",
      lesson.teacher_name || lesson.teacher || "",
      lesson.room_name || lesson.room || "",
      lesson.status || "ok",
    ].forEach((value) => tr.append(create("td", String(value))));
    return tr;
  });
  table.replaceChildren(header, ...rows);
}

function renderExcelAnalysis(analysis, error = null) {
  const summary = $("excel-analysis-summary");
  const messages = $("excel-analysis-messages");
  const suggestions = $("excel-mapping-suggestions");
  if (!analysis) {
    summary.replaceChildren();
    messages.replaceChildren(create("p", translateExcelText(error?.message) || "אין ניתוח זמין.", "diagnostic-card blocking"));
    renderMappingSuggestions(suggestions, null, false);
    renderExcelTechnical(error?.payload || {});
    return;
  }
  const diagnostics = analysis.diagnostics || {};
  const sheets = analysis.sheets_detected || analysis.sheet_names || [];
  const counts = analysis.counts || {};
  const summaryData = analysis.summary || {};
  const entities = analysis.extracted_entities || {};
  summary.replaceChildren(
    importSummaryCard("שורות שנקראו", String(summaryData.total_rows_read ?? counts.rows_total ?? 0), "muted"),
    importSummaryCard("שורת כותרת שזוהתה", summaryData.detected_header_row ? String(summaryData.detected_header_row) : "-", "muted"),
    importSummaryCard("שורות נתונים", String(summaryData.data_rows_detected ?? summaryData.total_data_rows_detected ?? 0), "muted"),
    importSummaryCard("שורות לייבוא", String(summaryData.imported_rows_count ?? 0), "muted"),
    importSummaryCard("שורות שלא יובאו", String(summaryData.ignored_empty_rows ?? 0), "muted"),
    importSummaryCard("גיליונות", sheets.length ? sheets.join(", ") : "-", "muted"),
    importSummaryCard("כיתות", String(summaryData.classes_detected ?? (entities.classes || []).length ?? 0), "muted"),
    importSummaryCard("מורים", String(summaryData.teachers_detected ?? (entities.teachers || []).length ?? 0), "muted"),
    importSummaryCard("מקצועות", String(summaryData.subjects_detected ?? (entities.subjects || []).length ?? 0), "muted"),
    importSummaryCard("דרישות שעות", String(summaryData.requirements_detected ?? (entities.requirements || []).length ?? 0), "muted"),
    importSummaryCard("ביטחון", analysis.confidence_score != null ? `${Math.round(Number(analysis.confidence_score) * 100)}%` : "-", "muted"),
  );
  const blocking = diagnostics.blocking || [];
  const warningDiagnostics = diagnostics.warnings || [];
  const suggestionsDiagnostics = diagnostics.suggestions || [];
  const legacyErrors = (analysis.errors || []).map((item) => ({ message: item }));
  const legacyWarnings = (analysis.warnings || []).map((item) => ({ message: item }));
  const status = blocking.length
    ? create("p", "הניתוח הסתיים עם נקודות שחוסמות ייבוא.", "diagnostic-card warning")
    : create("p", [
      `שורות שנקראו: ${summaryData.total_rows_read ?? 0}`,
      `שורת כותרת: ${summaryData.detected_header_row ?? "-"}`,
      `שורות נתונים: ${summaryData.data_rows_detected ?? 0}`,
      `שורות לייבוא: ${summaryData.imported_rows_count ?? 0}`,
      `שורות שלא יובאו: ${summaryData.ignored_empty_rows ?? 0}`,
    ].join(" · "), "diagnostic-card");
  messages.replaceChildren(
    status,
    renderExcelV2Diagnostics(analysis),
    ...[...blocking, ...legacyErrors].map((item) => create("p", translateExcelText(item.message || item.title || String(item)), "diagnostic-card blocking")),
    ...[...warningDiagnostics, ...legacyWarnings].map((item) => create("p", translateExcelText(item.message || item.title || String(item)), "diagnostic-card warning")),
    ...suggestionsDiagnostics.map((item) => create("p", translateExcelText(item.message || item.title || String(item)), "diagnostic-card")),
    recognizedColumnsBlock(analysis.detected_columns || [], analysis.unmapped_columns || []),
  );
  renderMappingSuggestions(suggestions, analysis.mapping_suggestions, !analysis.can_commit);
  prefillExcelMapping(analysis.mapping_suggestions);
  renderExcelTechnical(analysis);
}

function renderExcelV2Diagnostics(analysis) {
  const compare = analysis?.excel_intelligence_compare;
  const details = document.createElement("details");
  details.className = "mapping-block";
  details.open = Boolean(compare);
  details.append(create("summary", compare ? "אבחון Excel Intelligence v2: השוואה" : "אבחון Excel Intelligence v2"));
  if (!compare) {
    details.append(create("p", "הפעילו מצב בדיקה v1/v2 כדי להשוות סיווג בלי לשנות את ברירת המחדל.", "hint"));
    return details;
  }
  const summary = compare.summary || {};
  const list = create("ul");
  [
    `תוצאה ראשית: ${compare.primary_result_engine || compare.primary_mode || analysis.engine_used || "v1"}`,
    `סוגים v1: ${(summary.v1_detected_formats || []).join(", ") || "-"}`,
    `סוגים v2: ${(summary.v2_detected_formats || []).join(", ") || "-"}`,
    `שיפורים: ${summary.improvements ?? 0}`,
    `נסיגות: ${summary.regressions ?? 0}`,
    `דרישות v1/v2: ${summary.v1_requirements ?? 0}/${summary.v2_requirements ?? 0}`,
    `שיעורי מערכת v1/v2: ${summary.v1_scheduled_lessons ?? 0}/${summary.v2_scheduled_lessons ?? 0}`,
    `זמינות מורים v2: ${summary.v2_availability_entries ?? 0}`,
    `v2 כברירת מחדל: ${compare.v2_default_enabled ? "כן" : "לא"}`,
  ].forEach((line) => list.append(create("li", line)));
  details.append(list);
  (compare.sheets || []).forEach((sheet) => {
    const reasons = (sheet.v2_diagnostic_summary?.top_reasons || []).join(" · ");
    details.append(create("p", `${sheet.sheet_name}: v1 ${sheet.v1_format || "-"} · v2 ${sheet.v2_format || "-"} · ${translateExcelText(sheet.classification_change)} · v2 ${formatExcelConfidence(sheet.v2_confidence)} · ${translateExcelText(reasons || sheet.v2_parser_selection?.reason || "-")}`, "diagnostic-card"));
  });
  return details;
}

function translateExcelText(text) {
  const value = String(text || "");
  const known = {
    same: "ללא שינוי",
    improved: "שיפור",
    regressed: "נסיגה",
    changed: "השתנה",
    "Salle manquante.": "חסר חדר",
    "Extraction incertaine depuis une cellule libre.": "החילוץ מתא חופשי אינו ודאי",
    "Professeur absent ou indétectable.": "חסר מורה או שהמורה לא זוהה",
    "LibreOffice indisponible.": "LibreOffice אינו זמין",
    "Styles ignorés; lecture directe des valeurs XML.": "עיצוב הגיליון לא נקרא; הערכים נקראו ישירות מתוך XML",
    "Lecture read_only: les styles et certaines métadonnées ont été ignorés.": "קריאת Excel במצב read_only: עיצוב וחלק מהמטא-דאטה לא נקראו",
  };
  if (known[value]) return known[value];
  if (value.includes("Créneau approximatif généré")) return "נוצרה שעה משוערת לפי מבנה הגיליון";
  if (value.includes("Cette feuille est lisible")) return "הגיליון קריא אבל סוגו לא זוהה בביטחון מספיק";
  if (value.includes("Je pense que")) return value.replace("Je pense que", "נראה כי");
  if (value.includes("Confirme que")) return value.replace("Confirme que", "אשרו כי");
  if (value.includes("LibreOffice n'a pas pu convertir")) return "LibreOffice לא הצליח להמיר את קובץ ה-Excel";
  if (value.includes("Avertissement lecture Excel")) return "אזהרה בקריאת קובץ Excel";
  return value;
}

function formatExcelConfidence(value) {
  if (value === undefined || value === null) return "-";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${Math.round(numeric > 1 ? numeric : numeric * 100)}%`;
}

function recognizedColumnsBlock(detectedColumns, unmappedColumns) {
  const details = document.createElement("details");
  details.className = "mapping-block";
  details.open = true;
  details.append(create("summary", `עמודות שזוהו / לא זוהו (${detectedColumns.length})`));
  const list = create("ul");
  detectedColumns.forEach((column) => {
    list.append(create("li", `${column.original_name || `עמודה ${column.column_index}`} -> ${column.mapped_field || "לא זוהתה"}`));
  });
  if (unmappedColumns.length) {
    list.append(create("li", `לא זוהו: ${unmappedColumns.map((column) => column.original_name).join(", ")}`));
  }
  details.append(list);
  return details;
}

function prefillExcelMapping(suggestions = {}) {
  const first = (items, key) => Array.isArray(items) && items[0] && items[0][key] ? items[0][key] : "";
  const mappings = [
    ["excel-sheet-name", first(suggestions.possible_sheets, "name")],
    ["excel-day-row", first(suggestions.possible_day_rows, "row")],
    ["excel-time-column", first(suggestions.possible_time_columns, "column")],
    ["excel-day-column", first(suggestions.possible_day_columns, "column")],
    ["excel-time-row", first(suggestions.possible_time_rows, "row")],
    ["excel-header-row", first(suggestions.possible_header_rows, "row")],
  ];
  mappings.forEach(([id, value]) => {
    const element = $(id);
    if (element && !element.value && value) element.value = String(value);
  });
}

function importSummaryCard(label, value, tone = "muted") {
  const card = create("article", undefined, "import-summary-card");
  card.append(create("span", label), create("strong", value), create("em", tone === "good" ? "תקין" : tone === "bad" ? "שגיאה" : "", `score-badge ${tone}`));
  return card;
}

function formatLayoutLabel(layout) {
  const labels = {
    tabular: "table colonnes",
    grid_days_columns: "grille jours en colonnes",
    grid_days_rows: "grille jours en lignes",
    per_class_sheet: "une feuille par classe",
    per_teacher_sheet: "une feuille par professeur",
    unknown: "format non reconnu",
  };
  return labels[layout] || layout || "-";
}

function renderMappingSuggestions(root, suggestions, shouldShow) {
  if (!root) return;
  if (!shouldShow || !suggestions || !Object.keys(suggestions).length) {
    root.replaceChildren();
    return;
  }
  const title = create("h4", "Suggestions de mapping");
  const intro = create("p", suggestions.message || "Le fichier est lisible mais le format n'est pas totalement reconnu.", "hint");
  const blocks = [
    ["Lignes d'en-têtes possibles", suggestions.possible_header_rows],
    ["Lignes de jours possibles", suggestions.possible_day_rows],
    ["Colonnes de jours possibles", suggestions.possible_day_columns],
    ["Lignes d'horaires possibles", suggestions.possible_time_rows],
    ["Colonnes d'horaires possibles", suggestions.possible_time_columns],
    ["Feuilles possibles", suggestions.possible_sheets],
  ].map(([label, items]) => mappingSuggestionBlock(label, items || []));
  root.replaceChildren(title, intro, ...blocks);
}

function mappingSuggestionBlock(label, items) {
  const details = document.createElement("details");
  details.className = "mapping-block";
  details.open = Boolean(items.length);
  details.append(create("summary", `${label} (${items.length})`));
  if (!items.length) {
    details.append(create("p", "Aucune suggestion détectée.", "hint"));
    return details;
  }
  const list = create("ul");
  items.slice(0, 12).forEach((item) => {
    const parts = [];
    if (item.sheet || item.name) parts.push(`Feuille: ${item.sheet || item.name}`);
    if (item.row) parts.push(`Ligne: ${item.row}`);
    if (item.column) parts.push(`Colonne: ${item.column}`);
    if (item.value) parts.push(`Valeur: ${item.value}`);
    if (item.density_score != null) parts.push(`Densité: ${item.density_score}`);
    list.append(create("li", parts.join(" · ")));
  });
  details.append(list);
  return details;
}

function renderExcelTechnical(payload) {
  const target = $("excel-technical-json");
  if (!target) return;
  const safePayload = payload || {};
  target.textContent = JSON.stringify(
    {
      diagnostics: safePayload.diagnostics,
      detected_layout: safePayload.detected_layout,
      confidence_score: safePayload.confidence_score,
      excel_intelligence_compare: safePayload.excel_intelligence_compare,
      sheets: safePayload.sheets,
      parser_results: safePayload.parser_results,
      detail: safePayload.detail,
    },
    null,
    2,
  );
}

function bindForms() {
  const bindExport = (buttonId, format) => {
    const btn = $(buttonId);
    btn.addEventListener("click", async () => {
      setLoading(btn, true, "Export...");
      try {
        await exportSchedule(format);
      } catch (error) {
        notify(error.message, "error");
      } finally {
        setLoading(btn, false);
      }
    });
  };

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
    const hardTypes = new Set(["teacher_unavailable", "class_unavailable"]);
    const payload = { condition_type, text: description, description, hard: hardTypes.has(condition_type) };

    if (condition_type === "teacher_unavailable") {
      payload.teacher_name = $("condition-teacher-name").value.trim();
      payload.slot = $("condition-slot").value;
      requireKnownValue(payload.teacher_name, scheduleState.teachers, "un professeur existant");
      requireKnownValue(payload.slot, scheduleState.slots, "un créneau existant");
      payload.target_id = payload.teacher_name;
      payload.slot_id = payload.slot;
    }

    if (condition_type === "class_unavailable") {
      payload.class_name = $("condition-class-name").value.trim();
      payload.slot = $("condition-slot").value;
      requireKnownValue(payload.class_name, scheduleState.classes, "une classe existante");
      requireKnownValue(payload.slot, scheduleState.slots, "un créneau existant");
      payload.target_id = payload.class_name;
      payload.slot_id = payload.slot;
    }

    if (condition_type === "subject_prefer_morning" || condition_type === "avoid_subject_repeat_same_day") {
      payload.subject_name = $("condition-subject-name").value.trim();
      requireKnownValue(payload.subject_name, scheduleState.subjects, "une matière existante");
      payload.target_id = payload.subject_name;
    }

    if (condition_type === "teacher_prefer_morning") {
      payload.teacher_name = $("condition-teacher-name").value.trim();
      requireKnownValue(payload.teacher_name, scheduleState.teachers, "un professeur existant");
      payload.target_id = payload.teacher_name;
    }

    if (condition_type === "avoid_subject_repeat_same_day") {
      payload.class_name = $("condition-class-name").value.trim() || null;
      if (payload.class_name) requireKnownValue(payload.class_name, scheduleState.classes, "une classe existante");
    }
    if (condition_type === "avoid_long_sequence") {
      payload.class_name = $("condition-class-name").value.trim() || null;
      payload.teacher_name = $("condition-teacher-name").value.trim() || null;
      if (payload.class_name) requireKnownValue(payload.class_name, scheduleState.classes, "une classe existante");
      if (payload.teacher_name) requireKnownValue(payload.teacher_name, scheduleState.teachers, "un professeur existant");
    }
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

  $("excel-import-file").addEventListener("change", () => {
    scheduleState.importAnalysis = null;
    scheduleState.importPreview = null;
    renderExcelAnalysis(null);
    renderExcelPreview(null);
    updateExcelMvpCommitControls(null);
  });
  $("excel-analyze-btn").addEventListener("click", analyzeExcelImport);
  $("excel-import-form").addEventListener("submit", analyzeExcelImport);
  $("excel-preview-btn").addEventListener("click", previewExcelImport);
  $("excel-mvp-commit-btn").addEventListener("click", commitExcelMvpImport);
  $("excel-commit-replace-btn").addEventListener("click", (event) => commitExcelImport("replace", false, event.currentTarget));
  $("excel-commit-merge-btn").addEventListener("click", (event) => commitExcelImport("merge", false, event.currentTarget));
  $("excel-dry-run-btn").addEventListener("click", (event) => commitExcelImport("replace", true, event.currentTarget));
  $("import-intelligence-form").addEventListener("submit", analyzeImportIntelligence);
  $("import-intelligence-apply-btn").addEventListener("click", applyImportIntelligence);
  $("import-intelligence-clear-btn").addEventListener("click", clearImportIntelligence);

  $("condition-type").addEventListener("change", updateConditionFieldVisibility);
  ["condition-teacher-name", "condition-class-name", "condition-subject-name", "condition-slot"].forEach((id) => $(id).addEventListener("input", buildConditionText));
  $("teacher-unavailable-slots").addEventListener("change", updateUnavailableSlotsSummary);
  $("repair-type").addEventListener("change", () => {
    const repairType = $("repair-type").value;
    $("repair-target").value = getDefaultRepairTarget(repairType);
  });
  $("simulate-repair-btn").addEventListener("click", simulateRepairProposal);
  $("repair-view-current-btn").addEventListener("click", () => setRepairViewMode("current"));
  $("repair-view-proposal-btn").addEventListener("click", () => setRepairViewMode("proposal"));

  $("generate-btn").addEventListener("click", runGenerateSchedule);
  $("generate-btn-secondary").addEventListener("click", runGenerateSchedule);
  $("load-demo-btn").addEventListener("click", () => runAction("load-demo-btn", "/schedule/load-demo", "Chargement..."));
  $("load-pilot-demo-btn").addEventListener("click", runLoadPilotDemo);
  $("load-large-demo-btn").addEventListener("click", runLoadLargeDemo);
  $("clear-btn").addEventListener("click", () => runAction("clear-btn", "/schedule/clear", "Suppression..."));
  $("refresh-versions-btn").addEventListener("click", async () => {
    const btn = $("refresh-versions-btn");
    setLoading(btn, true, "Rafraîchissement...");
    try {
      await loadScheduleVersions();
    } finally {
      setLoading(btn, false);
    }
  });
  bindExport("export-json-btn", "json");
  bindExport("export-csv-btn", "csv");
  bindExport("export-pdf-btn", "pdf");

  $("schedule-view-mode").addEventListener("change", (e) => { scheduleState.viewMode = e.target.value; syncScheduleFiltersUI(); renderScheduleTableFromState(); });
  $("schedule-class-filter").addEventListener("change", (e) => { scheduleState.selectedClass = e.target.value; renderScheduleTableFromState(); });
  $("schedule-teacher-filter").addEventListener("change", (e) => { scheduleState.selectedTeacher = e.target.value; renderScheduleTableFromState(); });
  $("schedule-search").addEventListener("input", (e) => { scheduleState.search = e.target.value.trim().toLowerCase(); renderScheduleTableFromState(); });
}

initializeNavigation();
bindForms();
renderRepairProposal(null);
updateRepairViewToggle();
refreshBackendStatus();
refresh().catch((error) => {
  renderGenerationBanner(`Erreur au chargement initial : ${error.message}`, "error");
  notify(error.message, "error");
});
