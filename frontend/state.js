const scheduleState = {
  slots: [],
  classes: [],
  teachers: [],
  subjects: [],
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
  latestMetrics: null,
  latestDiagnosis: null,
  scheduleVersions: [],
  repairProposal: null,
  repairPreview: null,
  repairViewMode: "current",
  scheduleVersion: {
    activeId: null,
    source: "empty",
    pendingProposalId: null,
    previewProposalId: null,
    lastAcceptedProposalId: null,
    rollbackBase: null,
  },
  isRepairing: false,
  activeView: "dashboard-view",
};

const CONDITION_LABELS = {
  teacher_unavailable: "Professeur indisponible",
  class_unavailable: "Classe indisponible",
  subject_morning_preference: "Matière le matin",
  subject_prefer_morning: "Matière le matin",
  teacher_prefer_morning: "Professeur le matin",
  avoid_subject_repeat: "Éviter répétition",
  avoid_subject_repeat_same_day: "Éviter répétition",
  avoid_long_sequence: "Éviter longues séries",
};

const PREFERENCE_CONDITIONS = new Set(["subject_morning_preference", "subject_prefer_morning", "teacher_prefer_morning", "avoid_subject_repeat", "avoid_subject_repeat_same_day", "avoid_long_sequence"]);

const SCORE_CATEGORY_LABELS = {
  class_gap: "Trous classes",
  teacher_gap: "Trous professeurs",
  class_long_sequence: "Longues séries",
  teacher_long_sequence: "Longues séries",
  avoid_long_sequence: "Longues séries",
  teacher_conflict: "Conflits",
  class_conflict: "Conflits",
  unplaced_sessions: "Sessions non placées",
  subject_morning_preference: "Préférences respectées",
  teacher_morning_preference: "Préférences respectées",
  class_load_balance: "Bonus",
  teacher_load_balance: "Bonus",
  global_distribution: "Bonus",
};

function getSelectedScheduleOption() {
  const options = Array.isArray(scheduleState.scheduleOptions) ? scheduleState.scheduleOptions : [];
  if (!options.length) return null;
  return options.find((option) => option.selected === true)
    || options.find((option) => option.id === scheduleState.selectedOptionId)
    || options[0]
    || null;
}

function syncSelectedScheduleOption(preferredOptionId = null) {
  const options = Array.isArray(scheduleState.scheduleOptions) ? scheduleState.scheduleOptions : [];
  const selected = options.find((option) => option.selected === true)
    || options.find((option) => option.id === preferredOptionId)
    || options.find((option) => option.id === scheduleState.selectedOptionId)
    || options[0]
    || null;
  scheduleState.selectedOptionId = selected?.id || null;
  scheduleState.scheduleVersion.activeId = selected?.id || null;
  return selected;
}

function resetScheduleVersionState() {
  scheduleState.scheduleVersion = {
    activeId: null,
    source: "empty",
    pendingProposalId: null,
    previewProposalId: null,
    lastAcceptedProposalId: null,
    rollbackBase: null,
  };
}

function applyActiveSchedule(schedule, scheduleOptions = scheduleState.scheduleOptions, source = "refresh", preferredOptionId = null) {
  scheduleState.schedule = schedule || {};
  scheduleState.hasGeneratedSchedule = Object.keys(scheduleState.schedule).length > 0;
  scheduleState.scheduleOptions = Array.isArray(scheduleOptions) ? scheduleOptions : [];
  const selected = syncSelectedScheduleOption(preferredOptionId);
  scheduleState.scheduleVersion.source = scheduleState.hasGeneratedSchedule ? source : "empty";
  if (!scheduleState.hasGeneratedSchedule) {
    scheduleState.latestMetrics = null;
    scheduleState.scheduleVersion.rollbackBase = null;
    resetRepairState();
    return null;
  }
  if (selected) scheduleState.latestMetrics = { ...(scheduleState.latestMetrics || {}), ...selected };
  return selected;
}
