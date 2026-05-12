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
        await refresh();
      } catch (error) {
        notify(error.message, "error");
      } finally {
        setLoading(btn, false);
      }
    });
  };

  bindSubmit("class-form", "/classes", () => ({ name: document.getElementById("class-name").value }));
  bindSubmit("subject-form", "/subjects", () => ({
    name: document.getElementById("subject-name").value,
    hours_per_week: Number(document.getElementById("subject-hours").value),
  }));
  bindSubmit("teacher-form", "/teachers", () => ({
    name: document.getElementById("teacher-name").value,
    subjects: document.getElementById("teacher-subjects").value.split(",").map((s) => s.trim()).filter(Boolean),
  }));
  bindSubmit("slot-form", "/slots", () => ({ slot: document.getElementById("slot-value").value }));

  document.getElementById("generate-btn").addEventListener("click", runGenerateSchedule);
  document.getElementById("load-demo-btn").addEventListener("click", () => runAction("load-demo-btn", "/schedule/load-demo", "Loading..."));
  document.getElementById("clear-btn").addEventListener("click", () => runAction("clear-btn", "/schedule/clear", "Clearing..."));
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
    if (res.success === false) {
      throw new Error(res.message || "Failed to generate schedule");
    }
    await refreshScheduleTable();
    notify(res.message || "Schedule generated successfully");
  } catch (error) {
    notify(`Schedule generation failed: ${error.message}`, "error");
  } finally {
    setLoading(btn, false);
  }
}

async function refresh() {
  const [classes, subjects, teachers, slots, schedule] = await Promise.all([api("/classes"), api("/subjects"), api("/teachers"), api("/slots"), api("/schedule")]);
  document.getElementById("count-classes").textContent = classes.length;
  document.getElementById("count-subjects").textContent = subjects.length;
  document.getElementById("count-teachers").textContent = teachers.length;
  document.getElementById("count-slots").textContent = slots.length;

  fillList("classes-list", classes.map((x) => x.name));
  fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`));
  fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")}`));
  fillList("slots-list", slots);
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
    return `<td>${cell ? `${cell.subject} - ${cell.teacher}` : "-"}</td>`;
  }).join("")}</tr>`).join("");
  table.innerHTML = head + rows;
}

bindForms();
refresh();
