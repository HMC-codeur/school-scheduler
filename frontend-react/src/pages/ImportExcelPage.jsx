import { useState } from "react";
import { commitExcelImport, loadRepairDemo, previewExcel, validateGridCandidates } from "../api/schoolApi.js";
import { PageHeader } from "../components/PageHeader.jsx";
import { EmptyState } from "../components/EmptyState.jsx";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function normalizeImportResult(result) {
  const safe = asObject(result);
  const counts = asObject(safe.counts);
  const summary = asObject(safe.summary || safe.workbook_summary);
  const normalizedPreview = asObject(safe.normalized_preview || safe.preview);
  const previewRequirements = asArray(normalizedPreview.requirements).length
    ? asArray(normalizedPreview.requirements)
    : asArray(normalizedPreview.lessons);
  const previewAvailability = asArray(normalizedPreview.availability);
  const previewConstraints = asArray(normalizedPreview.constraints);
  const previewGridCandidates = asArray(normalizedPreview.schedule_grid_preview).length
    ? asArray(normalizedPreview.schedule_grid_preview)
    : asArray(normalizedPreview.lesson_candidates);
  const normalizedSummary = Object.keys(summary).length
    ? summary
    : {
        classes_count: counts.classes || 0,
        teachers_count: counts.teachers || 0,
        subjects_count: counts.subjects || 0,
        slots_count: counts.slots || 0,
        requirements_count: counts.lessons || 0,
        availability_count: counts.availability || 0,
        constraints_count: counts.constraints || 0,
        schedule_grid_preview_count: counts.schedule_grid_preview || counts.lesson_candidates || 0,
      };
  const requirementsCount = Number(normalizedSummary.requirements_count ?? normalizedSummary.importable_rows ?? previewRequirements.length ?? 0);
  const availabilityCount = Number(normalizedSummary.availability_count ?? previewAvailability.length ?? 0);
  const constraintsCount = Number(normalizedSummary.constraints_count ?? previewConstraints.length ?? 0);
  const scheduleGridPreviewCount = Number(normalizedSummary.schedule_grid_preview_count ?? normalizedSummary.lesson_candidates_count ?? previewGridCandidates.length ?? 0);
  const classesCount = Number(normalizedSummary.classes_count ?? normalizedSummary.detected_classes ?? asArray(normalizedPreview.classes).length ?? 0);
  const teachersCount = Number(normalizedSummary.teachers_count ?? normalizedSummary.detected_teachers ?? asArray(normalizedPreview.teachers).length ?? 0);
  const subjectsCount = Number(normalizedSummary.subjects_count ?? normalizedSummary.detected_subjects ?? asArray(normalizedPreview.subjects).length ?? 0);
  const confidence = safe.global_confidence ?? safe.confidence ?? safe.confidence_score ?? null;
  const hasImportableData = requirementsCount > 0 || availabilityCount > 0 || constraintsCount > 0 || scheduleGridPreviewCount > 0 || classesCount > 0 || teachersCount > 0 || subjectsCount > 0;
  const backendAllowsImport = Boolean(safe.can_apply ?? safe.can_commit);
  const canImport = backendAllowsImport && hasImportableData && Number(confidence ?? 0) > 0;
  return {
    import_id: safe.import_id || safe.importId || null,
    status: safe.status || "unknown",
    filename: safe.filename || safe.file_name || "",
    global_confidence: confidence,
    can_apply: canImport,
    can_commit: canImport,
    has_importable_data: hasImportableData,
    needs_human_review: Boolean(safe.needs_human_review) || !canImport,
    summary: {
      ...normalizedSummary,
      requirements_count: requirementsCount,
      availability_count: availabilityCount,
      constraints_count: constraintsCount,
      schedule_grid_preview_count: scheduleGridPreviewCount,
    },
    sheet_profiles: asArray(safe.sheet_profiles),
    sheet_classifications: asArray(safe.sheet_classifications),
    diagnostics: asArray(safe.diagnostics),
    human_questions: asArray(safe.human_questions),
    normalized_preview: normalizedPreview,
    warnings: asArray(safe.warnings),
    errors: asArray(safe.errors),
    lessons: asArray(safe.lessons),
    raw: safe,
  };
}

function previewSummary(normalized) {
  const summary = asObject(normalized?.summary);
  return [
    ["כיתות", summary.classes_count ?? summary.classes ?? 0],
    ["מורים", summary.teachers_count ?? summary.teachers ?? 0],
    ["מקצועות", summary.subjects_count ?? summary.subjects ?? 0],
    ["צרכים שבועיים", summary.requirements_count ?? 0],
    ["זמינות", summary.availability_count ?? 0],
    ["אילוצים", summary.constraints_count ?? 0],
    ["גריד מערכת שעות", summary.schedule_grid_preview_count ?? summary.lesson_candidates_count ?? 0],
    ["שורות לא תקינות", asArray(normalized?.warnings).length + asArray(normalized?.errors).length + asArray(normalized?.diagnostics).length],
  ];
}

function directorMetrics(normalized, gridValidation) {
  const summary = asObject(normalized?.summary);
  const preview = asObject(normalized?.normalized_preview);
  const validationSummary = asObject(gridValidation?.summary);
  const rejectedCandidates = gridValidation?.error
    ? 0
    : Number(validationSummary.rejected_candidates ?? asArray(gridValidation?.rejected_candidates).length ?? 0);
  const warningRows = asArray(normalized?.warnings).length + asArray(normalized?.errors).length;
  const reviewRows = gridValidation ? rejectedCandidates : warningRows;
  return [
    ["כיתות שנמצאו", summary.classes_count ?? summary.classes ?? summary.detected_classes ?? asArray(preview.classes).length ?? 0],
    ["מורים שנמצאו", summary.teachers_count ?? summary.teachers ?? summary.detected_teachers ?? asArray(preview.teachers).length ?? 0],
    ["מקצועות שנמצאו", summary.subjects_count ?? summary.subjects ?? summary.detected_subjects ?? asArray(preview.subjects).length ?? 0],
    ["שיעורים שזוהו", summary.schedule_grid_preview_count ?? summary.lesson_candidates_count ?? summary.requirements_count ?? 0],
    ["שורות שדורשות תיקון", reviewRows],
  ];
}

function diagnosticText(diagnostic) {
  if (typeof diagnostic === "string") return diagnostic;
  const safe = asObject(diagnostic);
  const severity = safe.severity || safe.level || "info";
  const code = safe.code ? ` [${safe.code}]` : "";
  const message = safe.message || safe.detail || safe.msg || JSON.stringify(safe);
  return `${severity}${code}: ${message}`;
}

function previewRows(normalized) {
  const previewData = normalized?.normalized_preview;
  if (Array.isArray(previewData)) return previewData;
  const safePreview = asObject(previewData);
  return asArray(safePreview.requirements).length
    ? asArray(safePreview.requirements)
    : asArray(safePreview.lessons).length
      ? asArray(safePreview.lessons)
      : asArray(normalized?.lessons);
}

function previewAvailabilityRows(normalized) {
  return asArray(asObject(normalized?.normalized_preview).availability);
}

function previewConstraintRows(normalized) {
  return asArray(asObject(normalized?.normalized_preview).constraints);
}

function previewScheduleGridRows(normalized) {
  const preview = asObject(normalized?.normalized_preview);
  return asArray(preview.lesson_candidates).length
    ? asArray(preview.lesson_candidates)
    : asArray(preview.schedule_grid_preview);
}

function isScheduleGridBlocked(normalized) {
  const classifications = asArray(normalized?.sheet_classifications);
  const diagnostics = asArray(normalized?.diagnostics);
  return classifications.some((item) => asObject(item).sheet_type === "schedule_grid")
    && diagnostics.some((item) => asObject(item).code === "schedule_grid_requires_review" || asObject(item).code === "no_importable_data" || asObject(item).code === "schedule_grid_preview_only");
}

function isEmptyImportAnalysis(normalized) {
  if (!normalized) return false;
  const summary = asObject(normalized.summary);
  const confidence = Number(normalized.global_confidence ?? 0);
  const importableRows = Number(summary.importable_rows ?? summary.requirements_count ?? 0);
  const availabilityCount = Number(summary.availability_count ?? 0);
  const constraintsCount = Number(summary.constraints_count ?? 0);
  const scheduleGridPreviewCount = Number(summary.schedule_grid_preview_count ?? summary.lesson_candidates_count ?? 0);
  const classesCount = Number(summary.classes_count ?? summary.detected_classes ?? 0);
  const teachersCount = Number(summary.teachers_count ?? summary.detected_teachers ?? 0);
  const subjectsCount = Number(summary.subjects_count ?? summary.detected_subjects ?? 0);
  return !normalized.has_importable_data || importableRows === 0 && availabilityCount === 0 && constraintsCount === 0 && scheduleGridPreviewCount === 0 && classesCount === 0 && teachersCount === 0 && subjectsCount === 0 || confidence === 0;
}

function detectedDataMessage(normalized) {
  if (!normalized) return "";
  if (isScheduleGridBlocked(normalized)) {
    return "מערכת שעות זוהתה בתצוגה מקדימה. נדרשת בדיקה ואישור ידני לפני ייבוא אמיתי.";
  }
  if (normalized.status === "needs_review" && normalized.has_importable_data) {
    return "זוהו נתונים, מומלץ לבצע בדיקה ידנית לפני ייבוא אמיתי.";
  }
  return "";
}

function candidateValue(candidate, keys, fallback = "") {
  const safeCandidate = asObject(candidate);
  for (const key of keys) {
    const value = safeCandidate[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return fallback;
}

function candidateKey(candidate, index) {
  const safeCandidate = asObject(candidate);
  const trace = asObject(safeCandidate.source_trace);
  return [
    trace.sheet_name || safeCandidate.sheet_name || "grid",
    trace.row ?? safeCandidate.row ?? "row",
    trace.column ?? safeCandidate.column ?? "col",
    index,
  ].join("-");
}

function candidateConfidence(candidate) {
  const value = Number(candidateValue(candidate, ["confidence"], NaN));
  return Number.isFinite(value) ? value : null;
}

function formatConfidence(confidence) {
  if (confidence == null) return "";
  return confidence <= 1 ? `${Math.round(confidence * 100)}%` : `${Math.round(confidence)}%`;
}

function isLowConfidenceCandidate(candidate) {
  const confidence = candidateConfidence(candidate);
  const warnings = asArray(asObject(candidate).warnings);
  return warnings.length > 0 || (confidence != null && confidence < 0.6);
}

function defaultCandidateReview(candidate) {
  return {
    status: isLowConfidenceCandidate(candidate) ? "low_confidence" : "needs_review",
    class_name: String(candidateValue(candidate, ["class_name", "class_group", "class", "group_name", "group"], "")),
    subject: String(candidateValue(candidate, ["subject", "subject_name", "detected_subject"], "")),
    teacher: String(candidateValue(candidate, ["teacher", "teacher_name", "detected_teacher"], "")),
  };
}

function candidateStatusLabel(status) {
  if (status === "accepted") return "אושר לתצוגה מקדימה";
  if (status === "ignored") return "התעלם";
  if (status === "low_confidence") return "אמינות נמוכה";
  return "דורש בדיקה";
}

function reviewedGridCandidatePayload(candidate, index, review) {
  const classGroup = String(review?.class_name ?? candidateValue(candidate, ["class_name", "class_group", "class", "group_name", "group"], ""));
  const rawCell = String(candidateValue(candidate, ["raw_cell", "original_text", "original_cell_text", "cell_text", "text"], ""));
  const slot = String(candidateValue(candidate, ["time", "slot", "slot_label", "period"], ""));
  const subject = String(review?.subject ?? candidateValue(candidate, ["subject", "subject_name", "detected_subject"], ""));
  const teacher = String(review?.teacher ?? candidateValue(candidate, ["teacher", "teacher_name", "detected_teacher"], ""));
  return {
    status: review?.status === "ignored" ? "ignored" : "accepted",
    class_name: classGroup,
    class_group: classGroup,
    day: String(candidateValue(candidate, ["day"], "")),
    slot,
    time: String(candidateValue(candidate, ["time"], slot)),
    subject,
    subject_name: subject,
    teacher,
    teacher_name: teacher,
    confidence: candidateConfidence(candidate),
    raw_cell: rawCell,
    original_text: rawCell,
    source_trace: asObject(candidate).source_trace,
    review_index: index,
  };
}

const VALIDATION_MESSAGE_HEBREW = {
  missing_class_or_group: "כיתה / קבוצה חובה.",
  missing_subject: "מקצוע חובה.",
  missing_day: "יום חובה או לא מזוהה.",
  invalid_day: "יום חובה או לא מזוהה.",
  missing_slot: "שעה חובה או לא מזוהה.",
  invalid_slot: "שעה חובה או לא מזוהה.",
  "Classe ou groupe obligatoire.": "כיתה / קבוצה חובה.",
  "Matière obligatoire.": "מקצוע חובה.",
};

function validationMessageText(issue) {
  const safe = asObject(issue);
  return VALIDATION_MESSAGE_HEBREW[safe.code]
    || VALIDATION_MESSAGE_HEBREW[safe.message]
    || safe.message
    || safe.code
    || String(issue);
}

function formatValidationIssue(issue) {
  const safe = asObject(issue);
  const parts = [];
  if (safe.candidate_index != null) parts.push(`מועמד ${Number(safe.candidate_index) + 1}`);
  if (safe.row != null || safe.column != null) parts.push(`תא ${safe.row ?? "?"}/${safe.column ?? "?"}`);
  parts.push(validationMessageText(issue));
  if (safe.field) parts.push(`שדה ${safe.field}`);
  return parts.filter(Boolean).join(" · ");
}

function rejectedCandidateText(item) {
  const safe = asObject(item);
  const candidate = asObject(safe.candidate);
  const errors = asArray(safe.errors).map(formatValidationIssue).join(" · ");
  const index = safe.index != null ? `מועמד ${Number(safe.index) + 1}` : "מועמד שנדחה";
  const context = [
    candidate.class_name || candidate.class_group,
    candidate.day,
    candidate.slot || candidate.time,
    candidate.raw_cell || candidate.original_text,
  ].filter(Boolean).join(" · ");
  return `${index}${context ? ` · ${context}` : ""}: ${errors || "שגיאת אימות."}`;
}

function suggestionProblemText(item) {
  const safe = asObject(item);
  const candidate = asObject(safe.candidate);
  const trace = asObject(candidate.source_trace);
  const errors = asArray(safe.errors);
  const firstError = asObject(errors[0]);
  const parts = [];
  if (safe.index != null) parts.push(`מועמד ${Number(safe.index) + 1}`);
  if (trace.row != null || trace.column != null || firstError.row != null || firstError.column != null) {
    parts.push(`תא ${trace.row ?? firstError.row ?? "?"}/${trace.column ?? firstError.column ?? "?"}`);
  }
  const raw = candidate.raw_cell || candidate.original_text || candidate.cell_text || candidate.text;
  if (raw) parts.push(String(raw));
  return parts.join(" · ") || "שורה שדורשת בדיקה";
}

function suggestedActionLabel(suggestion) {
  const safe = asObject(suggestion);
  return safe.label_he || {
    fill_missing_class: "השלמת כיתה",
    ignore_as_non_lesson: "התעלמות משורה שאינה שיעור",
    edit_subject: "השלמת מקצוע",
    edit_day_or_slot: "תיקון יום או שעה",
    manual_review: "בדיקה ידנית",
  }[safe.action] || "בדיקה ידנית";
}

function gridValidationCounts(result) {
  if (!result || result.error) return { validCount: null, rejectedCount: null };
  const summary = asObject(result.summary);
  return {
    validCount: Number(summary.valid_candidates ?? asArray(result.valid_candidates).length ?? 0),
    rejectedCount: Number(summary.rejected_candidates ?? asArray(result.rejected_candidates).length ?? 0),
  };
}

function DirectorResultCard({
  normalized,
  scheduleGridRows,
  gridValidation,
  gridValidationLoading,
  candidateReviews,
  onValidate,
  onAcceptSuggestion,
  onIgnoreSuggestion,
  onOpenEdit,
}) {
  const statusNeedsReview = normalized.status === "blocked" || normalized.status === "needs_review" || isScheduleGridBlocked(normalized);
  const { validCount, rejectedCount } = gridValidationCounts(gridValidation);
  const hasRejectedCandidates = Number(rejectedCount ?? 0) > 0;
  const hasScheduleGrid = scheduleGridRows.length > 0;
  const title = statusNeedsReview
    ? "הקובץ נותח — נדרש אישור לפני ייבוא"
    : "הקובץ נותח בהצלחה";
  let gridMessage = "";
  if (gridValidation?.error) {
    gridMessage = gridValidation.error;
  } else if (gridValidation && validCount != null) {
    gridMessage = hasRejectedCandidates
      ? `שורות שנעצרו לבדיקה: ${rejectedCount}`
      : "כל השיעורים שנבדקו תקינים.";
  } else if (hasScheduleGrid) {
    gridMessage = "מצאנו מערכת שעות קיימת בתוך קובץ האקסל. ניתן לבדוק את השיעורים שזוהו לפני ייבוא.";
  }
  const summaryMessages = gridValidation
    ? hasRejectedCandidates
      ? [
          "המערכת זיהתה שורות שאינן מוכנות לייבוא אוטומטי.",
          "חלק מהשורות נראות כמו זמינות מורים, הערות או מידע חסר — ולכן הן נעצרו לבדיקה במקום להיכנס למערכת כשיעורים.",
          "ניתן לפתוח את השורות שדורשות בדיקה, לאשר, להתעלם או לתקן אותן לפני ייבוא אמיתי.",
          validCount > 0 ? "שיעורים תקינים מוכנים לשלב הבא לאחר אישור אנושי." : "",
        ].filter(Boolean)
      : gridValidation.error
        ? ["בדיקת השיעורים לא הושלמה. הפרטים הטכניים זמינים למפתחים."]
        : ["כל השיעורים שנבדקו תקינים.", "שיעורים תקינים מוכנים לשלב הבא לאחר אישור אנושי."]
    : [
        hasScheduleGrid
          ? "הייבוא האמיתי עדיין כבוי עד בדיקה ואישור."
          : "אפשר לעבור על הסיכום לפני כל ייבוא אמיתי.",
      ];
  const rejectedSuggestions = asArray(gridValidation?.rejected_candidates).filter((item) => asObject(item).suggestion.action);

  return (
    <section className="director-result-card">
      <div className="section-head">
        <div>
          <span className="eyebrow">סיכום למנהל/ת</span>
          <h3>{title}</h3>
          {normalized.filename ? <p>{normalized.filename}</p> : null}
        </div>
        {hasScheduleGrid ? (
          <button className="primary-button" disabled={gridValidationLoading} type="button" onClick={onValidate}>
            {gridValidationLoading ? "מאמת..." : "אמת שיעורים שזוהו"}
          </button>
        ) : null}
      </div>
      <div className="director-metrics">
        {directorMetrics(normalized, gridValidation).map(([label, value]) => (
          <article className="director-metric" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </div>
      {gridMessage ? <div className={gridValidation?.error || hasRejectedCandidates ? "notice warning" : "notice"}>{gridMessage}</div> : null}
      <div className={hasRejectedCandidates ? "notice warning" : "notice"}>
        {summaryMessages.map((message) => (
          <p key={message}>{message}</p>
        ))}
      </div>
      {rejectedSuggestions.length ? (
        <section className="repair-suggestions" aria-label="הצעות תיקון">
          <div className="section-head compact-head">
            <h3>הצעות תיקון</h3>
            <span>{rejectedSuggestions.length} שורות לבדיקה</span>
          </div>
          <div className="repair-suggestion-grid">
            {rejectedSuggestions.slice(0, 6).map((item) => {
              const safe = asObject(item);
              const suggestion = asObject(safe.suggestion);
              const candidate = scheduleGridRows[Number(safe.index)] || asObject(safe.candidate);
              const review = candidateReviews[candidateKey(candidate, Number(safe.index) || 0)];
              const locallyHandled = review?.status === "ignored" || review?.status === "accepted";
              return (
                <article className="repair-suggestion-card" key={`suggestion-${safe.index}`}>
                  <span className="suggestion-problem">{suggestionProblemText(item)}</span>
                  <strong>{suggestedActionLabel(suggestion)}</strong>
                  <p>{suggestion.explanation_he || "נדרשת בדיקה ידנית."}</p>
                  {suggestion.confidence != null ? <small>ביטחון: {formatConfidence(Number(suggestion.confidence))}</small> : null}
                  {locallyHandled ? <small>עודכן מקומית. אפשר להריץ אימות מחדש.</small> : null}
                  <div className="row-actions">
                    <button className="secondary-button compact-button" type="button" onClick={() => onAcceptSuggestion(safe)}>
                      קבל הצעה
                    </button>
                    <button className="secondary-button compact-button" type="button" onClick={() => onIgnoreSuggestion(safe)}>
                      התעלם
                    </button>
                    <button className="secondary-button compact-button" type="button" onClick={() => onOpenEdit(safe)}>
                      פתח לעריכה
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function GridValidationResult({ result }) {
  if (!result) {
    return (
      <div className="notice">
        ייבוא אמיתי עדיין כבוי בשלב זה.
      </div>
    );
  }
  if (result.error) {
    return <div className="notice danger">{result.error}</div>;
  }
  const summary = asObject(result.summary);
  const validCount = summary.valid_candidates ?? asArray(result.valid_candidates).length;
  const rejectedCount = summary.rejected_candidates ?? asArray(result.rejected_candidates).length;
  const warnings = asArray(result.warnings);
  const blockingErrors = asArray(result.blocking_errors);
  const rejected = asArray(result.rejected_candidates);
  return (
    <div className="grid-validation-result">
      <div className={blockingErrors.length || rejected.length ? "notice warning" : "notice"}>
        <strong>{blockingErrors.length || rejected.length ? "בדיקת המועמדים הסתיימה עם שורות שדורשות תיקון. אף שיעור עדיין לא יובא." : "בדיקה בלבד — אף שיעור עדיין לא יובא למערכת."}</strong>
      </div>
      <div className="stat-grid compact">
        <article className="stat-card"><span>שיעורים תקינים</span><strong>{validCount}</strong></article>
        <article className="stat-card"><span>שורות שנדחו</span><strong>{rejectedCount}</strong></article>
        <article className="stat-card"><span>אזהרות</span><strong>{warnings.length}</strong></article>
        <article className="stat-card"><span>שגיאות חוסמות</span><strong>{blockingErrors.length}</strong></article>
      </div>
      <div className="notice">ייבוא אמיתי עדיין כבוי בשלב זה.</div>
      {warnings.map((warning, index) => (
        <div className="notice warning" key={`grid-warning-${index}`}>{formatValidationIssue(warning)}</div>
      ))}
      {blockingErrors.map((issue, index) => (
        <div className="notice danger" key={`grid-blocking-${index}`}>{formatValidationIssue(issue)}</div>
      ))}
      {rejected.map((item, index) => (
        <div className="notice danger" key={`grid-rejected-${index}`}>{rejectedCandidateText(item)}</div>
      ))}
    </div>
  );
}

export function ImportExcelPage({ navigate, refreshData, setImportPreview, t, language }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [commitResult, setCommitResult] = useState(null);
  const [candidateReviews, setCandidateReviews] = useState({});
  const [gridValidation, setGridValidation] = useState(null);
  const [gridValidationLoading, setGridValidationLoading] = useState(false);
  const [showCandidateDetails, setShowCandidateDetails] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const normalized = preview ? normalizeImportResult(preview) : null;
  const rows = previewRows(normalized);
  const availabilityRows = previewAvailabilityRows(normalized);
  const constraintRows = previewConstraintRows(normalized);
  const scheduleGridRows = previewScheduleGridRows(normalized);
  const previewKeys = Object.keys(asObject(normalized?.normalized_preview));
  const hasMinimalResponse = normalized && !previewKeys.length && !rows.length;
  const emptyImportAnalysis = isEmptyImportAnalysis(normalized);
  const productLimitMessage = detectedDataMessage(normalized);

  const submit = async (event) => {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await previewExcel(file);
      setPreview(result);
      setCommitResult(null);
      setCandidateReviews({});
      setGridValidation(null);
      setShowCandidateDetails(false);
      setImportPreview(normalizeImportResult(result));
    } catch (err) {
      setError(err.message || t.error);
    } finally {
      setLoading(false);
    }
  };

  const importPreview = async () => {
    if (!normalized?.can_commit && !normalized?.can_apply) return;
    setLoading(true);
    setError("");
    setCommitResult(null);
    try {
      const result = await commitExcelImport({
        import_id: normalized.import_id,
        lessons: normalized.import_id ? undefined : rows,
        mode: "replace",
        dry_run: false,
        create_missing_entities: true,
        selected: true,
        synthesize_schedule_option: true,
        fail_on_conflict: true,
      });
      setCommitResult(result);
      await refreshData();
    } catch (err) {
      setError(err.message || t.error);
    } finally {
      setLoading(false);
    }
  };

  const loadDemo = async () => {
    setLoading(true);
    setError("");
    try {
      await loadRepairDemo();
      await refreshData();
      const demoPreview = {
        filename: "demo-repair-pilot.xlsx",
        counts: { classes: 12, teachers: 22, subjects: 10, slots: 30, lessons: 216 },
        warnings: ["12 בעיות דמו יוצגו במסך האבחון"],
        lessons: [],
      };
      setPreview(demoPreview);
      setCandidateReviews({});
      setGridValidation(null);
      setShowCandidateDetails(false);
      setImportPreview(demoPreview);
    } catch (err) {
      setError(err.message || t.error);
    } finally {
      setLoading(false);
    }
  };

  const validateReviewedCandidates = async () => {
    if (!scheduleGridRows.length) return;
    setGridValidationLoading(true);
    setGridValidation(null);
    setError("");
    try {
      const candidates = scheduleGridRows.map((candidate, index) => {
        const key = candidateKey(candidate, index);
        const review = candidateReviews[key] || defaultCandidateReview(candidate);
        return reviewedGridCandidatePayload(candidate, index, review);
      });
      const result = await validateGridCandidates(candidates);
      setGridValidation(result);
    } catch (err) {
      setGridValidation({ error: err.message || t.error });
    } finally {
      setGridValidationLoading(false);
    }
  };

  const updateCandidateReview = (candidate, index, patch, { clearValidation = false } = {}) => {
    const key = candidateKey(candidate, index);
    if (clearValidation) setGridValidation(null);
    setCandidateReviews((current) => ({
      ...current,
      [key]: { ...defaultCandidateReview(candidate), ...current[key], ...patch },
    }));
  };

  const acceptSuggestion = (rejectedItem) => {
    const index = Number(asObject(rejectedItem).index);
    const candidate = scheduleGridRows[index] || asObject(rejectedItem).candidate;
    const suggestion = asObject(asObject(rejectedItem).suggestion);
    const proposed = asObject(suggestion.proposed_values);
    if (suggestion.action === "ignore_as_non_lesson") {
      updateCandidateReview(candidate, index, { status: "ignored" });
      return;
    }
    if (suggestion.action === "fill_missing_class" && proposed.class_name) {
      updateCandidateReview(candidate, index, { status: "accepted", class_name: String(proposed.class_name) });
      return;
    }
    if (suggestion.action === "edit_subject" && proposed.subject) {
      updateCandidateReview(candidate, index, { status: "accepted", subject: String(proposed.subject) });
      return;
    }
    setShowCandidateDetails(true);
  };

  const ignoreSuggestion = (rejectedItem) => {
    const index = Number(asObject(rejectedItem).index);
    const candidate = scheduleGridRows[index] || asObject(rejectedItem).candidate;
    updateCandidateReview(candidate, index, { status: "ignored" });
  };

  const openSuggestionForEdit = () => {
    setShowCandidateDetails(true);
  };

  return (
    <div className="import-excel-page" dir="rtl">
      <PageHeader
        eyebrow="Excel"
        title="ייבוא מערכת שעות מאקסל"
        description="העלה קובץ Excel קיים, והמערכת תנתח את הכיתות, המורים, המקצועות, הצרכים והשגיאות לפני כל ייבוא אמיתי."
      />
      <section className="upload-zone">
        <form onSubmit={submit}>
          <input type="file" accept=".xlsx,.xlsm,.csv" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <div className="action-row">
            <button className="primary-button" disabled={!file || loading} type="submit">בדוק קובץ</button>
            <button className="secondary-button" disabled={loading} type="button" onClick={loadDemo}>טען דמו תיקון</button>
          </div>
        </form>
        {loading ? <div className="notice">{t.loading}</div> : null}
        {error ? <div className="notice danger">{error}</div> : null}
      </section>
      {preview ? (
        <>
          <DirectorResultCard
            normalized={normalized}
            scheduleGridRows={scheduleGridRows}
            gridValidation={gridValidation}
            gridValidationLoading={gridValidationLoading}
            candidateReviews={candidateReviews}
            onValidate={validateReviewedCandidates}
            onAcceptSuggestion={acceptSuggestion}
            onIgnoreSuggestion={ignoreSuggestion}
            onOpenEdit={openSuggestionForEdit}
          />
          <section className="panel">
            <div className="section-head">
              <h3>תצוגה מקדימה</h3>
              <div className="action-row">
                <button className="primary-button" disabled={(!normalized.can_commit && !normalized.can_apply) || emptyImportAnalysis || loading} type="button" onClick={importPreview}>
                  ייבוא אמיתי
                </button>
                <button className="secondary-button" type="button" onClick={() => navigate("diagnostic")}>{t.runDiagnostic}</button>
              </div>
            </div>
            {hasMinimalResponse ? <div className="notice">הניתוח התקבל. תצוגה מקדימה בסיסית זמינה.</div> : null}
            {productLimitMessage ? <div className="notice">{productLimitMessage}</div> : null}
            {emptyImportAnalysis ? (
              <div className="notice danger">
                <strong>לא זוהו נתונים שניתן לייבא.</strong>
                <span>{isScheduleGridBlocked(normalized) ? "מערכת שעות זוהתה בתצוגה מקדימה. נדרשת בדיקה ואישור ידני לפני ייבוא אמיתי." : "הקובץ התקבל, אך לא זוהתה בו טבלה שניתן לייבא."}</span>
              </div>
            ) : null}
            {normalized.errors.length ? <div className="notice warning">המערכת זיהתה שורות שאינן מוכנות לייבוא אוטומטי.</div> : null}
            {!normalized.errors.length && gridValidation && !gridValidation.error && !gridValidationCounts(gridValidation).rejectedCount ? <div className="notice">כל השיעורים שנבדקו תקינים.</div> : null}
            {commitResult?.success ? <div className="notice">{commitResult.message}</div> : null}
            {rows.length || availabilityRows.length || constraintRows.length ? (
              <details className="disclosure-panel">
                <summary>הצג נתונים שזוהו בקובץ</summary>
                {rows.length ? (
                  <section className="stack-form">
                    <h3>צרכים שבועיים שזוהו</h3>
                    {rows.slice(0, 12).map((lesson, index) => {
                      const safeLesson = asObject(lesson);
                      return (
                        <div className="schedule-item" key={`${safeLesson.row || "row"}-${safeLesson.column || "col"}-${index}`}>
                          <time>{safeLesson.day || ""} {safeLesson.slot_label || safeLesson.slot || ""}</time>
                          <strong>{safeLesson.class_name || safeLesson.class || t.unavailable}</strong>
                          <span>{safeLesson.subject || safeLesson.subject_name || t.unavailable}</span>
                          <span>{safeLesson.teacher || safeLesson.teacher_name || t.unavailable}</span>
                        </div>
                      );
                    })}
                  </section>
                ) : null}
                {availabilityRows.length ? (
                  <section className="stack-form">
                    <h3>זמינות מורים שזוהתה</h3>
                    {availabilityRows.slice(0, 12).map((availability, index) => {
                      const safeAvailability = asObject(availability);
                      return (
                        <div className="schedule-item" key={`availability-${safeAvailability.teacher_name || safeAvailability.teacher || "teacher"}-${index}`}>
                          <time>{safeAvailability.day || ""} {safeAvailability.time || safeAvailability.slot || safeAvailability.slot_label || ""}</time>
                          <strong>{safeAvailability.teacher_name || safeAvailability.teacher || t.unavailable}</strong>
                          <span>{safeAvailability.availability || safeAvailability.status || t.unavailable}</span>
                          <span>{safeAvailability.confidence != null ? safeAvailability.confidence : ""}</span>
                        </div>
                      );
                    })}
                  </section>
                ) : null}
                {constraintRows.length ? (
                  <section className="stack-form">
                    <h3>אילוצים שזוהו</h3>
                    {constraintRows.slice(0, 12).map((constraint, index) => {
                      const safeConstraint = asObject(constraint);
                      return (
                        <div className="schedule-item" key={`constraint-${index}`}>
                          <time>{safeConstraint.type || safeConstraint.kind || ""}</time>
                          <strong>{safeConstraint.text || safeConstraint.description || t.unavailable}</strong>
                          <span>{safeConstraint.target || safeConstraint.teacher_name || safeConstraint.class_name || ""}</span>
                          <span>{safeConstraint.confidence != null ? safeConstraint.confidence : ""}</span>
                        </div>
                      );
                    })}
                  </section>
                ) : null}
              </details>
            ) : null}
            {scheduleGridRows.length ? (
              <section className="stack-form schedule-grid-review director-disclosure">
                <div className="section-head">
                  <div>
                    <h3>שיעורים שזוהו מתוך מערכת השעות</h3>
                    <p>בדיקה בלבד — אף שיעור עדיין לא יובא למערכת.</p>
                  </div>
                  <button className="primary-button" disabled={gridValidationLoading} type="button" onClick={validateReviewedCandidates}>
                    {gridValidationLoading ? "מאמת..." : "אמת שיעורים שזוהו"}
                  </button>
                </div>
                <button className="secondary-button director-toggle" type="button" onClick={() => setShowCandidateDetails((current) => !current)}>
                  {showCandidateDetails ? "הסתר שורות שדורשות בדיקה" : "פתח שורות לבדיקה"}
                </button>
                {showCandidateDetails ? (
                  <div className="stack-form">
                    <GridValidationResult result={gridValidation} />
                    <div className="table-wrap">
                      <table className="review-table">
                        <thead>
                          <tr>
                            <th>סטטוס</th>
                            <th>כיתה / קבוצה</th>
                            <th>יום</th>
                            <th>שעה</th>
                            <th>הטקסט המקורי</th>
                            <th>מקצוע שזוהה</th>
                            <th>מורה שזוהה</th>
                            <th>רמת אמון</th>
                            <th>פעולות</th>
                          </tr>
                        </thead>
                        <tbody>
                          {scheduleGridRows.map((candidate, index) => {
                            const key = candidateKey(candidate, index);
                            const review = candidateReviews[key] || defaultCandidateReview(candidate);
                            const confidence = candidateConfidence(candidate);
                            const lowConfidence = isLowConfidenceCandidate(candidate);
                            const updateReview = (patch) => {
                              setGridValidation(null);
                              setCandidateReviews((current) => ({
                                ...current,
                                [key]: { ...defaultCandidateReview(candidate), ...current[key], ...patch },
                              }));
                            };
                            return (
                              <tr className={`review-row ${review.status}`} key={key}>
                                <td>
                                  <span className={`review-status ${review.status}`}>{candidateStatusLabel(review.status)}</span>
                                  {lowConfidence ? <span className="review-warning">דורש בדיקה</span> : null}
                                </td>
                                <td>
                                  <input
                                    aria-label="עריכת הכיתה או הקבוצה"
                                    disabled={review.status === "ignored"}
                                    value={review.class_name}
                                    onChange={(event) => updateReview({ class_name: event.target.value })}
                                  />
                                </td>
                                <td>{candidateValue(candidate, ["day"], t.unavailable)}</td>
                                <td>{candidateValue(candidate, ["slot_label", "time", "slot"], t.unavailable)}</td>
                                <td className="raw-cell">{candidateValue(candidate, ["raw_cell", "original_cell_text", "cell_text", "text"], t.unavailable)}</td>
                                <td>
                                  <input
                                    aria-label="עריכת המקצוע שזוהה"
                                    disabled={review.status === "ignored"}
                                    value={review.subject}
                                    onChange={(event) => updateReview({ subject: event.target.value })}
                                  />
                                </td>
                                <td>
                                  <input
                                    aria-label="עריכת המורה שזוהה"
                                    disabled={review.status === "ignored"}
                                    value={review.teacher}
                                    onChange={(event) => updateReview({ teacher: event.target.value })}
                                  />
                                </td>
                                <td>{formatConfidence(confidence) || t.unavailable}</td>
                                <td>
                                  <div className="row-actions">
                                    <button className="secondary-button compact-button" type="button" onClick={() => updateReview({ status: "accepted" })}>
                                      אשר
                                    </button>
                                    <button className="secondary-button compact-button" type="button" onClick={() => updateReview({ status: "ignored" })}>
                                      התעלם
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : null}
              </section>
            ) : null}
            {!rows.length && !availabilityRows.length && !constraintRows.length && !scheduleGridRows.length ? <EmptyState title="אין שורות תצוגה מקדימה להצגה" description="בדמו המסחרי הנתונים נטענים לשרת והאבחון מציג את הבעיות." /> : null}
            <details className="disclosure-panel">
              <summary>אבחון מתקדם</summary>
              <div className="schedule-item">
                <time>{normalized.status}</time>
                <strong>{normalized.filename || t.unavailable}</strong>
                <span>{normalized.import_id || t.unavailable}</span>
                <span>{normalized.global_confidence ?? t.unavailable}</span>
              </div>
              {normalized.warnings.map((item, index) => <div className="notice" key={`warning-${index}`}>{String(item)}</div>)}
              {normalized.errors.map((item, index) => <div className="notice danger" key={`error-${index}`}>{String(item)}</div>)}
              {normalized.diagnostics.map((item, index) => <div className="notice" key={`diagnostic-${index}`}>{diagnosticText(item)}</div>)}
            </details>
            <details className="disclosure-panel">
              <summary>פרטים טכניים למפתחים</summary>
              <pre>{JSON.stringify(normalized.raw, null, 2)}</pre>
            </details>
          </section>
        </>
      ) : null}
    </div>
  );
}
