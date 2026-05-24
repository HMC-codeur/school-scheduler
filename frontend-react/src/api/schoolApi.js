import { apiRequest, downloadRequest } from "./client";

export function getClasses() {
  return apiRequest("/classes");
}

export function getTeachers() {
  return apiRequest("/teachers");
}

export function getSubjects() {
  return apiRequest("/subjects");
}

export function getSlots() {
  return apiRequest("/slots");
}

export function getSchedule() {
  return apiRequest("/schedule");
}

export function getConditions() {
  return apiRequest("/conditions");
}

export function getScheduleOptions() {
  return apiRequest("/schedule/options");
}

export function checkHealth() {
  return apiRequest("/health");
}

export function diagnoseSchedule() {
  return apiRequest("/schedule/diagnose");
}

export function createClass(payload) {
  return apiRequest("/classes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createTeacher(payload) {
  return apiRequest("/teachers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createSubject(payload) {
  return apiRequest("/subjects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createSlot(payload) {
  return apiRequest("/slots", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCondition(payload) {
  return apiRequest("/conditions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateSchedule() {
  return apiRequest("/schedule/generate", { method: "POST" });
}

export function loadDemo() {
  return apiRequest("/schedule/load-demo", { method: "POST" });
}

export function loadLargeDemo() {
  return apiRequest("/schedule/load-large-demo", { method: "POST" });
}

export function loadPilotDemo() {
  return apiRequest("/schedule/load-pilot-demo", { method: "POST" });
}

export function loadRepairDemo() {
  return apiRequest("/schedule/load-repair-demo", { method: "POST" });
}

export function clearSchedule() {
  return apiRequest("/schedule/clear", { method: "POST" });
}

export function previewExcel(file) {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest("/imports/analyze", {
    method: "POST",
    body: formData,
  });
}

export function commitExcelImport(payload) {
  return apiRequest("/schedule/import/excel/commit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function validateGridCandidates(candidates) {
  return apiRequest("/imports/validate-grid-candidates", {
    method: "POST",
    body: JSON.stringify({ candidates }),
  });
}

export function repairSchedule(payload) {
  return apiRequest("/schedule/repair", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function previewRepairProposal(proposalId) {
  return apiRequest(`/schedule/repair/proposals/${proposalId}`);
}

export function acceptRepairProposal(proposalId) {
  return apiRequest(`/schedule/repair/proposals/${proposalId}/accept`, { method: "POST" });
}

export function rejectRepairProposal(proposalId) {
  return apiRequest(`/schedule/repair/proposals/${proposalId}`, { method: "DELETE" });
}

export function exportSchedule(format) {
  return downloadRequest(`/schedule/export/${format}`);
}

export function exportRepairProposalPdf(proposalId) {
  return downloadRequest(`/schedule/repair/proposals/${proposalId}/export/pdf`);
}
