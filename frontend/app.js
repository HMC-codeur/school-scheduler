const API = "";

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Request failed");
  }
  return response.json().catch(() => ({}));
}

function notify(message, type = "success") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast ${type}`;
  setTimeout(() => (el.className = "toast hidden"), 3000);
}

function setLoading(button, isLoading, text) {
  button.disabled = isLoading;
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.textContent = text;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
  }
}

function getUnavailableSlots() {
  return Array.from(document.getElementById("teacher-unavailable-slots").selectedOptions).map((opt) => opt.value);
}

function validateNonEmpty(value, field) {
  if (!value || !value.trim()) {
    throw new Error(`${field} is required.`);
  }
}

function bindForms() {
  const bindSubmit = (formId, path, payloadBuilder) => {
    document.getElementById(formId).addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button[type='submit']");
      setLoading(btn, true, "Saving...");
      try {
        await api(path, { method: "POST", body: JSON.stringify(payloadBuilder()) });
        notify("Saved successfully");
        e.target.reset();
        document.getElementById("class-max-lessons").value = 6;
        document.getElementById("teacher-max-lessons").value = 6;
        updateUnavailableSlotsSummary();
        await refresh();
      } catch (error) {
        notify(error.message, "error");
      } finally {
        setLoading(btn, false);
      }
    });
  };

  bindSubmit("class-form", "/classes", () => {
    const name = document.getElementById("class-name").value;
    const max = Number(document.getElementById("class-max-lessons").value);
    validateNonEmpty(name, "Class name");
    if (!Number.isInteger(max) || max < 1) throw new Error("Class max lessons/day must be at least 1.");
    return { name: name.trim(), max_lessons_per_day: max };
  });

  bindSubmit("subject-form", "/subjects", () => {
    const name = document.getElementById("subject-name").value;
    const hours = Number(document.getElementById("subject-hours").value);
    validateNonEmpty(name, "Subject name");
    if (!Number.isInteger(hours) || hours < 1) throw new Error("Subject hours/week must be at least 1.");
    return { name: name.trim(), hours_per_week: hours };
  });

  bindSubmit("teacher-form", "/teachers", () => {
    const name = document.getElementById("teacher-name").value;
    const subjectsRaw = document.getElementById("teacher-subjects").value;
    const max = Number(document.getElementById("teacher-max-lessons").value);
    validateNonEmpty(name, "Teacher name");
    validateNonEmpty(subjectsRaw, "Teacher subjects");
    if (!Number.isInteger(max) || max < 1) throw new Error("Teacher max lessons/day must be at least 1.");
    return {
      name: name.trim(),
      subjects: subjectsRaw.split(",").map((s) => s.trim()).filter(Boolean),
      unavailable_slots: getUnavailableSlots(),
      max_lessons_per_day: max,
    };
  });

  bindSubmit("slot-form", "/slots", () => {
    const slot = document.getElementById("slot-value").value;
    validateNonEmpty(slot, "Slot value");
    return { slot: slot.trim() };
  });

  document.getElementById("teacher-unavailable-slots").addEventListener("change", updateUnavailableSlotsSummary);
  document.getElementById("generate-btn").addEventListener("click", runGenerateSchedule);
  document.getElementById("load-demo-btn").addEventListener("click", () => runAction("load-demo-btn", "/schedule/load-demo", "Loading..."));
  document.getElementById("clear-btn").addEventListener("click", () => runAction("clear-btn", "/schedule/clear", "Clearing..."));
}

function updateUnavailableSlotsSummary() {
  const selected = getUnavailableSlots();
  document.getElementById("teacher-unavailable-selected").textContent = selected.length
    ? `Selected: ${selected.join(", ")}`
    : "No unavailable slots selected.";
}

async function runAction(buttonId, path, loadingLabel) {
  const btn = document.getElementById(buttonId);
  setLoading(btn, true, loadingLabel);
  try {
    const res = await api(path, { method: "POST" });
    notify(res.message || "Done", res.success === false ? "error" : "success");
    await refresh();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setLoading(btn, false);
  }
}

async function runGenerateSchedule() {
  const btn = document.getElementById("generate-btn");
  setLoading(btn, true, "Generating...");
  try {
    const res = await api("/schedule/generate", { method: "POST" });
    if (res.success === false) throw new Error(res.message || "Failed to generate schedule");
    await refreshScheduleTable();
    notify(res.message || "Schedule generated successfully");
  } catch (error) {
    notify(`Schedule generation failed: ${error.message}`, "error");
  } finally {
    setLoading(btn, false);
  }
}

function populateUnavailableSlots(slots) {
  const select = document.getElementById("teacher-unavailable-slots");
  const currentSelection = new Set(getUnavailableSlots());
  select.innerHTML = slots.map((slot) => `<option value="${slot}">${slot}</option>`).join("");
  Array.from(select.options).forEach((opt) => {
    opt.selected = currentSelection.has(opt.value);
  });
  updateUnavailableSlotsSummary();
}

async function refresh() {
  const [classes, subjects, teachers, slots, schedule] = await Promise.all([api("/classes"), api("/subjects"), api("/teachers"), api("/slots"), api("/schedule")]);
  document.getElementById("count-classes").textContent = classes.length;
  document.getElementById("count-subjects").textContent = subjects.length;
  document.getElementById("count-teachers").textContent = teachers.length;
  document.getElementById("count-slots").textContent = slots.length;

  fillList("classes-list", classes.map((x) => `${x.name} (max/day: ${x.max_lessons_per_day})`));
  fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`));
  fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")} | max/day: ${x.max_lessons_per_day} | unavailable: ${x.unavailable_slots.join(", ") || "-"}`));
  fillList("slots-list", slots);
  populateUnavailableSlots(slots);
  renderScheduleTable(slots, classes.map((c) => c.name), schedule);
}

async function refreshScheduleTable() {
  const [classes, slots, schedule] = await Promise.all([api("/classes"), api("/slots"), api("/schedule")]);
  renderScheduleTable(slots, classes.map((c) => c.name), schedule);
}

function fillList(id, items) {
  document.getElementById(id).innerHTML = items.map((x) => `<li>${x}</li>`).join("") || "<li>-</li>";
}

function renderScheduleTable(slots, classes, schedule) {
  const table = document.getElementById("schedule-table");
  if (!classes.length || !slots.length) {
    table.innerHTML = "<tr><td>Add classes and slots to view schedule table.</td></tr>";
    return;
  }
  const head = `<tr><th>Slot</th>${classes.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  const rows = slots.map((slot) => `<tr><td>${slot}</td>${classes.map((className) => {
    const cell = schedule?.[slot]?.[className];
    return `<td>${cell ? `<div class='cell-subject'>${cell.subject}</div><div class='cell-teacher'>${cell.teacher}</div>` : "<span class='empty-cell'>-</span>"}</td>`;
  }).join("")}</tr>`).join("");
  table.innerHTML = head + rows;
}

bindForms();
refresh();
