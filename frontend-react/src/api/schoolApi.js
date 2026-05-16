import { apiRequest } from "./client";

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

export function clearSchedule() {
  return apiRequest("/schedule/clear", { method: "POST" });
}
