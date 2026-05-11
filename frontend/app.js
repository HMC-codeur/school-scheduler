const API = "";

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Request failed");
  }
  return response.json();
}

function bindForms() {
  document.getElementById("class-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleSubmit("/classes", { name: document.getElementById("class-name").value });
    e.target.reset();
  });

  document.getElementById("subject-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleSubmit("/subjects", {
      name: document.getElementById("subject-name").value,
      hours_per_week: Number(document.getElementById("subject-hours").value),
    });
    e.target.reset();
  });

  document.getElementById("teacher-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const subjects = document.getElementById("teacher-subjects").value.split(",").map((s) => s.trim()).filter(Boolean);
    await handleSubmit("/teachers", { name: document.getElementById("teacher-name").value, subjects });
    e.target.reset();
  });

  document.getElementById("slot-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleSubmit("/slots", { slot: document.getElementById("slot-value").value });
    e.target.reset();
  });

  document.getElementById("generate-btn").addEventListener("click", generateSchedule);
}

async function handleSubmit(path, payload) {
  try {
    await api(path, { method: "POST", body: JSON.stringify(payload) });
    setMessage("Saved", false);
    await refresh();
  } catch (e) {
    setMessage(e.message, true);
  }
}

function setMessage(text, isError) {
  const el = document.getElementById("message");
  el.textContent = text;
  el.style.color = isError ? "#dc2626" : "#16a34a";
}

async function generateSchedule() {
  try {
    const res = await api("/schedule/generate", { method: "POST" });
    setMessage(res.message, !res.success);
    await refresh();
  } catch (e) {
    setMessage(e.message, true);
  }
}

async function refresh() {
  const [classes, subjects, teachers, slots, schedule] = await Promise.all([
    api("/classes"),
    api("/subjects"),
    api("/teachers"),
    api("/slots"),
    api("/schedule"),
  ]);

  fillList("classes-list", classes.map((x) => x.name));
  fillList("subjects-list", subjects.map((x) => `${x.name} (${x.hours_per_week}h)`));
  fillList("teachers-list", teachers.map((x) => `${x.name}: ${x.subjects.join(", ")}`));
  fillList("slots-list", slots);
  renderScheduleTable(slots, classes.map((c) => c.name), schedule);
}

function fillList(id, items) {
  document.getElementById(id).innerHTML = items.map((x) => `<li>${x}</li>`).join("");
}

function renderScheduleTable(slots, classes, schedule) {
  const table = document.getElementById("schedule-table");
  const head = `<tr><th>Slot</th>${classes.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  const rows = slots
    .map((slot) => {
      const cells = classes
        .map((className) => {
          const item = schedule?.[slot]?.[className];
          return `<td>${item ? `${item.subject}<br/><small>${item.teacher}</small>` : "-"}</td>`;
        })
        .join("");
      return `<tr><td>${slot}</td>${cells}</tr>`;
    })
    .join("");
  table.innerHTML = head + rows;
}

bindForms();
refresh();
