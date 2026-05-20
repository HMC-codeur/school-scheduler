function getDisplayedSchedule() {
  if (scheduleState.repairViewMode === "proposal" && scheduleState.repairPreview?.proposed_schedule) {
    return scheduleState.repairPreview.proposed_schedule || {};
  }
  return scheduleState.schedule || {};
}

function buildRepairDiffMap() {
  const source = scheduleState.repairPreview || scheduleState.repairProposal || null;
  const changedItems = Array.isArray(source?.changed_items) ? source.changed_items : [];
  const map = {
    class: new Map(),
    teacher: new Map(),
  };
  changedItems.forEach((item) => {
    const className = item?.class_name || item?.class_id || "";
    const subject = item?.subject_name || item?.subject_id || "Cours";
    const sessionId = item?.session_id || "";
    const oldSlot = item?.old_slot || "";
    const newSlot = item?.new_slot || "";
    const oldTeacher = item?.old_teacher_name || item?.old_teacher_id || "";
    const newTeacher = item?.new_teacher_name || item?.new_teacher_id || "";
    const changeType = item?.change_type || "";

    if (oldSlot && className) addRepairDiffEntry(map.class, oldSlot, className, {
      state: changeType === "removed" ? "removed" : "moved removed",
      label: changeType === "removed" ? "Retiré" : "Déplacé depuis ici",
      subject,
      sessionId,
      detail: `${oldSlot} → ${newSlot || "-"}`,
    });
    if (newSlot && className) addRepairDiffEntry(map.class, newSlot, className, {
      state: changeType === "added" ? "added" : "moved added",
      label: changeType === "added" ? "Ajouté" : "Déplacé ici",
      subject,
      sessionId,
      detail: `${oldSlot || "-"} → ${newSlot}`,
    });
    if (oldSlot && oldTeacher) addRepairDiffEntry(map.teacher, oldSlot, oldTeacher, {
      state: changeType === "removed" || changeType === "teacher_changed" ? "removed" : "moved removed",
      label: changeType === "teacher_changed" ? "Professeur changé" : "Déplacé depuis ici",
      subject,
      className,
      sessionId,
      detail: `${oldTeacher || "-"} → ${newTeacher || "-"}`,
    });
    if (newSlot && newTeacher) addRepairDiffEntry(map.teacher, newSlot, newTeacher, {
      state: changeType === "added" || changeType === "teacher_changed" ? "added" : "moved added",
      label: changeType === "teacher_changed" ? "Nouveau professeur" : "Déplacé ici",
      subject,
      className,
      sessionId,
      detail: `${oldTeacher || "-"} → ${newTeacher || "-"}`,
    });
  });
  return map;
}

function addRepairDiffEntry(map, slot, resource, entry) {
  const key = `${slot}||${resource}`;
  const current = map.get(key) || [];
  current.push(entry);
  map.set(key, current);
}

function getRepairCellState(diffMap, slot, selected, viewMode) {
  if (!diffMap || !slot || !selected) return [];
  const bucket = viewMode === "teacher" ? diffMap.teacher : diffMap.class;
  return bucket.get(`${slot}||${selected}`) || [];
}

function renderRepairOverlay(cell, states) {
  const items = Array.isArray(states) ? states : [];
  if (!items.length) return;
  const hasAdded = items.some((item) => item.state.includes("added"));
  const hasRemoved = items.some((item) => item.state.includes("removed"));
  const hasMoved = items.some((item) => item.state.includes("moved"));
  cell.classList.toggle("repair-added", hasAdded);
  cell.classList.toggle("repair-removed", hasRemoved);
  cell.classList.toggle("repair-moved", hasMoved);
  const summary = items.map((item) => {
    const parts = [item.label, item.subject];
    if (item.className) parts.push(item.className);
    if (item.detail) parts.push(item.detail);
    if (item.sessionId) parts.push(item.sessionId);
    return parts.filter(Boolean).join(" · ");
  }).join("\n");
  cell.title = summary;
  const overlay = create("div", undefined, "repair-cell-overlay");
  items.slice(0, 2).forEach((item) => {
    overlay.append(create("span", `${item.label}: ${item.subject || "cours"}`, "repair-chip"));
  });
  cell.append(overlay);
}

function getDefaultRepairTarget(repairType) {
  if (repairType === "repair_class") return scheduleState.selectedClass || scheduleState.classes[0] || "";
  if (repairType === "repair_day") return (scheduleState.slots[0] || "").split("-", 1)[0] || "";
  return scheduleState.selectedTeacher || scheduleState.teachers[0] || "";
}

function repairPayloadFromControls() {
  const repairType = $("repair-type")?.value || "repair_teacher";
  const target = ($("repair-target")?.value || getDefaultRepairTarget(repairType)).trim();
  if (!target) throw new Error("Choisissez une cible de réparation.");
  const payload = {
    repair_type: repairType,
    repair_policy: $("repair-policy")?.value || "balanced",
    repair_target: target,
    time_budget_seconds: 5,
    commit: false,
  };
  if (repairType === "repair_day") payload.day = target;
  return payload;
}

async function simulateRepairProposal() {
  if (scheduleState.isRepairing) {
    notify("Simulation de réparation déjà en cours.", "info");
    return;
  }
  const btn = $("simulate-repair-btn");
  setLoading(btn, true, "Simulation...");
  setRepairActionLoading(true);
  scheduleState.isRepairing = true;
  renderRepairStatus("Simulation de réparation en cours...", "loading");
  try {
    if (!scheduleState.hasGeneratedSchedule || !Object.keys(scheduleState.schedule || {}).length) {
      throw new Error("Générez d'abord un planning avant de simuler une réparation.");
    }
    const payload = repairPayloadFromControls();
    const proposal = await api("/schedule/repair", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    focusRepairTargetInSchedule(payload);
    setRepairProposalState(proposal);
    renderScheduleTableFromState();
    renderRepairStatus("Proposition de réparation créée.", "success");
    notify("Proposition de réparation créée.");
  } catch (error) {
    renderRepairStatus(`Échec de simulation : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    scheduleState.isRepairing = false;
    setRepairActionLoading(false);
    setLoading(btn, false);
  }
}

function focusRepairTargetInSchedule(payload) {
  const target = payload?.repair_target || "";
  if (payload?.repair_type === "repair_class" && target) {
    scheduleState.viewMode = "class";
    scheduleState.selectedClass = target;
  }
  if (payload?.repair_type === "repair_teacher" && target) {
    scheduleState.viewMode = "teacher";
    scheduleState.selectedTeacher = target;
  }
  const modeSelect = $("schedule-view-mode");
  const classSelect = $("schedule-class-filter");
  const teacherSelect = $("schedule-teacher-filter");
  if (modeSelect) modeSelect.value = scheduleState.viewMode;
  if (classSelect && scheduleState.classes.includes(scheduleState.selectedClass)) classSelect.value = scheduleState.selectedClass;
  if (teacherSelect && scheduleState.teachers.includes(scheduleState.selectedTeacher)) teacherSelect.value = scheduleState.selectedTeacher;
  syncScheduleFiltersUI();
}

async function previewRepairProposal() {
  const proposalId = scheduleState.repairProposal?.proposal_id;
  if (!proposalId) {
    renderRepairStatus("Aucune proposition à prévisualiser.", "error");
    notify("Aucune proposition à prévisualiser.", "error");
    return;
  }
  setRepairActionLoading(true);
  try {
    const preview = await api(`/schedule/repair/proposals/${encodeURIComponent(proposalId)}`);
    setRepairProposalState(scheduleState.repairProposal, preview);
    renderScheduleTableFromState();
    renderRepairStatus("Prévisualisation chargée. Le planning actif est inchangé.", "success");
    notify("Prévisualisation chargée.");
  } catch (error) {
    renderRepairStatus(`Échec de prévisualisation : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    setRepairActionLoading(false);
  }
}

async function setRepairViewMode(mode) {
  if (mode === "proposal") {
    const proposalId = scheduleState.repairProposal?.proposal_id;
    if (!proposalId) {
      renderRepairStatus("Aucune proposition à afficher.", "error");
      notify("Aucune proposition à afficher.", "error");
      return;
    }
    if (!scheduleState.repairPreview?.proposed_schedule) {
      await previewRepairProposal();
    }
    if (!scheduleState.repairPreview?.proposed_schedule) return;
  }
  scheduleState.repairViewMode = mode === "proposal" ? "proposal" : "current";
  updateRepairViewToggle();
  renderScheduleTableFromState();
}

function updateRepairViewToggle() {
  const currentBtn = $("repair-view-current-btn");
  const proposalBtn = $("repair-view-proposal-btn");
  if (!currentBtn || !proposalBtn) return;
  currentBtn.classList.toggle("active", scheduleState.repairViewMode === "current");
  proposalBtn.classList.toggle("active", scheduleState.repairViewMode === "proposal");
  proposalBtn.disabled = !scheduleState.repairProposal?.proposal_id;
}

async function acceptRepairProposal() {
  const proposalId = scheduleState.repairProposal?.proposal_id;
  if (!proposalId) {
    renderRepairStatus("Aucune proposition à accepter.", "error");
    notify("Aucune proposition à accepter.", "error");
    return;
  }
  setRepairActionLoading(true);
  try {
    await api(`/schedule/repair/proposals/${encodeURIComponent(proposalId)}/accept`, { method: "POST" });
    scheduleState.scheduleVersion.lastAcceptedProposalId = proposalId;
    resetRepairState("Proposition acceptée. Le planning actif a été mis à jour.", "success");
    await refreshScheduleTable();
    scheduleState.scheduleVersion.source = "accepted_proposal";
    renderScheduleTableFromState();
    notify("Réparation acceptée.");
  } catch (error) {
    renderRepairStatus(`Échec d'acceptation : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    setRepairActionLoading(false);
  }
}

async function rejectRepairProposal() {
  const proposalId = scheduleState.repairProposal?.proposal_id;
  if (!proposalId) {
    renderRepairStatus("Aucune proposition à refuser.", "error");
    notify("Aucune proposition à refuser.", "error");
    return;
  }
  setRepairActionLoading(true);
  try {
    await api(`/schedule/repair/proposals/${encodeURIComponent(proposalId)}`, { method: "DELETE" });
    resetRepairState("Proposition refusée. Le planning actif est inchangé.", "success");
    renderScheduleTableFromState();
    await loadScheduleVersions();
    notify("Proposition refusée.");
  } catch (error) {
    renderRepairStatus(`Échec du refus : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    setRepairActionLoading(false);
  }
}

async function exportRepairProposalPdf() {
  const proposalId = scheduleState.repairProposal?.proposal_id;
  if (!proposalId) {
    renderRepairStatus("Aucune proposition à exporter.", "error");
    notify("Aucune proposition à exporter.", "error");
    return;
  }
  setRepairActionLoading(true);
  try {
    const response = await apiFetch(`/schedule/repair/proposals/${encodeURIComponent(proposalId)}/export/pdf`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `repair-report-${proposalId}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    notify("Export PDF Repair prêt.");
  } catch (error) {
    renderRepairStatus(`Échec export PDF Repair : ${error.message}`, "error");
    notify(error.message, "error");
  } finally {
    setRepairActionLoading(false);
  }
}

function renderRepairStatus(message, level = "info") {
  const el = $("repair-status");
  if (!el) return;
  el.textContent = message;
  el.dataset.level = level;
}

function resetRepairState(message = "Aucune proposition de réparation.", level = "info") {
  scheduleState.repairProposal = null;
  scheduleState.repairPreview = null;
  scheduleState.repairViewMode = "current";
  scheduleState.scheduleVersion.pendingProposalId = null;
  scheduleState.scheduleVersion.previewProposalId = null;
  scheduleState.scheduleVersion.rollbackBase = null;
  renderRepairProposal(null);
  updateRepairViewToggle();
  renderRepairStatus(message, level);
}

function setRepairProposalState(proposal, preview = null) {
  scheduleState.repairProposal = proposal || null;
  scheduleState.repairPreview = preview;
  if (!proposal) scheduleState.repairViewMode = "current";
  scheduleState.scheduleVersion.pendingProposalId = proposal?.proposal_id || null;
  scheduleState.scheduleVersion.previewProposalId = preview?.proposal_id || null;
  if (proposal?.proposal_id && !scheduleState.scheduleVersion.rollbackBase) {
    scheduleState.scheduleVersion.rollbackBase = scheduleState.schedule;
  }
  updateRepairViewToggle();
  renderRepairProposal(scheduleState.repairProposal, scheduleState.repairPreview);
}

function setRepairActionLoading(isLoading) {
  document.querySelectorAll("#repair-proposal button").forEach((button) => {
    button.disabled = isLoading;
  });
}

function renderRepairProposal(proposal, preview = null) {
  const root = $("repair-proposal");
  if (!root) return;
  if (!proposal) {
    root.replaceChildren(create("p", "Aucune proposition simulée.", "hint"));
    return;
  }
  const details = preview || proposal;
  const hasProposalId = Boolean(proposal.proposal_id);
  const metrics = [
    ["Proposal", proposal.proposal_id || "-"],
    ["Type", details.repair_type || proposal.repair_type || "-"],
    ["Policy", details.repair_policy || proposal.repair_policy || "-"],
    ["Changements", String(details.changed_items_count ?? proposal.changed_items_count ?? 0)],
    ["Stabilité", formatScore(details.stability_score ?? proposal.stability_score)],
    ["Qualité", formatScore(details.quality_score ?? proposal.quality_score)],
    ["Conflits hard", String(details.hard_conflicts ?? proposal.hard_conflicts ?? "-")],
  ];
  const summary = create("div", undefined, "repair-summary");
  metrics.forEach(([label, value]) => {
    const item = create("div", undefined, "repair-metric");
    item.append(create("span", label), create("strong", value));
    summary.append(item);
  });

  const actions = create("div", undefined, "repair-actions");
  const previewBtn = create("button", "Prévisualiser");
  const acceptBtn = create("button", "Accepter", "primary");
  const rejectBtn = create("button", "Refuser", "danger");
  const exportBtn = create("button", "Exporter PDF Repair");
  previewBtn.disabled = !hasProposalId;
  acceptBtn.disabled = !hasProposalId;
  rejectBtn.disabled = !hasProposalId;
  exportBtn.disabled = !hasProposalId;
  previewBtn.addEventListener("click", previewRepairProposal);
  acceptBtn.addEventListener("click", acceptRepairProposal);
  rejectBtn.addEventListener("click", rejectRepairProposal);
  exportBtn.addEventListener("click", exportRepairProposalPdf);
  actions.append(previewBtn, exportBtn, acceptBtn, rejectBtn);

  const title = create("h4", preview ? "Détails prévisualisés" : "Proposition simulée");
  const viewHint = create(
    "p",
    scheduleState.repairViewMode === "proposal"
      ? "Le tableau affiche la proposition réparée. Le planning actif reste inchangé tant que vous n'acceptez pas."
      : "Le tableau affiche le planning actuel avec les changements proposés en surbrillance.",
    "hint",
  );
  root.replaceChildren(title, viewHint, summary, renderChangedItems(details.changed_items || proposal.changed_items || []), actions);
}

function renderChangedItems(items) {
  const section = create("div", undefined, "changed-items");
  const list = Array.isArray(items) ? items : [];
  section.append(create("h4", "Cours modifiés"));
  if (!list.length) {
    section.append(create("p", "Aucun changement détaillé retourné.", "hint"));
    return section;
  }
  const entries = list.map((item) => {
    const card = create("article", undefined, "changed-item");
    const title = [
      item?.class_name || item?.class_id || "Classe inconnue",
      item?.subject_name || item?.subject_id || "Matière inconnue",
    ].join(" · ");
    const slotText = `${item?.old_slot || "-"} → ${item?.new_slot || "-"}`;
    const teacherText = `${item?.old_teacher_name || item?.old_teacher_id || "-"} → ${item?.new_teacher_name || item?.new_teacher_id || "-"}`;
    card.append(
      create("strong", title),
      create("span", `Créneau : ${slotText}`, "hint"),
      create("span", `Professeur : ${teacherText}`, "hint"),
      create("span", `Session : ${item?.session_id || "-"}`, "hint"),
      create("span", `Type : ${item?.change_type || "-"}`, "hint"),
    );
    return card;
  });
  section.append(...entries);
  return section;
}
