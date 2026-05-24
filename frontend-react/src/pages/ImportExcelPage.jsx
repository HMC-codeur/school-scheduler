import { useState } from "react";
import { commitExcelImport, loadRepairDemo, previewExcel } from "../api/schoolApi.js";
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
    ["Besoins", summary.requirements_count ?? 0],
    ["Disponibilités", summary.availability_count ?? 0],
    ["Contraintes", summary.constraints_count ?? 0],
    ["Grille", summary.schedule_grid_preview_count ?? summary.lesson_candidates_count ?? 0],
    ["שורות לא תקינות", asArray(normalized?.warnings).length + asArray(normalized?.errors).length + asArray(normalized?.diagnostics).length],
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
    return "Grille planning analysée en aperçu. Validation humaine obligatoire avant import.";
  }
  if (normalized.status === "needs_review" && normalized.has_importable_data) {
    return "Données détectées, validation humaine recommandée.";
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
    subject: String(candidateValue(candidate, ["subject", "subject_name", "detected_subject"], "")),
    teacher: String(candidateValue(candidate, ["teacher", "teacher_name", "detected_teacher"], "")),
  };
}

function candidateStatusLabel(status) {
  if (status === "accepted") return "accepted preview";
  if (status === "ignored") return "ignored";
  if (status === "low_confidence") return "low confidence";
  return "needs review";
}

export function ImportExcelPage({ navigate, refreshData, setImportPreview, t, language }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [commitResult, setCommitResult] = useState(null);
  const [candidateReviews, setCandidateReviews] = useState({});
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
      setImportPreview(demoPreview);
    } catch (err) {
      setError(err.message || t.error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Excel"
        title="יבוא Planning Excel"
        description="העלה קובץ קיים מ-Excel/Mashov/Shahaf/EduPage וקבל תצוגה מקדימה לפני אבחון."
      />
      <section className="upload-zone">
        <form onSubmit={submit}>
          <input type="file" accept=".xlsx,.xlsm,.csv" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <div className="action-row">
            <button className="primary-button" disabled={!file || loading} type="submit">בדוק קובץ</button>
            <button className="secondary-button" disabled={loading} type="button" onClick={loadDemo}>Charger démo réparation</button>
          </div>
        </form>
        {loading ? <div className="notice">{t.loading}</div> : null}
        {error ? <div className="notice danger">{error}</div> : null}
      </section>
      {preview ? (
        <>
          <section className="stat-grid compact">
            {previewSummary(normalized).map(([label, value]) => (
              <article className="stat-card" key={label}><span>{label}</span><strong>{value}</strong></article>
            ))}
          </section>
          <section className="panel">
            <div className="section-head">
              <h3>Preview</h3>
              <div className="action-row">
                <button className="primary-button" disabled={(!normalized.can_commit && !normalized.can_apply) || emptyImportAnalysis || loading} type="button" onClick={importPreview}>
                  {language === "he" ? "ייבא Planning" : "Importer"}
                </button>
                <button className="secondary-button" type="button" onClick={() => navigate("diagnostic")}>{t.runDiagnostic}</button>
              </div>
            </div>
            {hasMinimalResponse ? <div className="notice">Analyse reçue. Aperçu minimal disponible.</div> : null}
            {productLimitMessage ? <div className="notice">{productLimitMessage}</div> : null}
            {emptyImportAnalysis ? (
              <div className="notice danger">
                <strong>Aucune donnée importable détectée.</strong>
                <span>{isScheduleGridBlocked(normalized) ? "La grille est reconnue, mais son extraction automatique n’est pas encore disponible." : "Le fichier a été reçu, mais aucune table exploitable n’a été reconnue."}</span>
              </div>
            ) : null}
            <div className="schedule-item">
              <time>{normalized.status}</time>
              <strong>{normalized.filename || t.unavailable}</strong>
              <span>{normalized.import_id || t.unavailable}</span>
              <span>{normalized.global_confidence ?? t.unavailable}</span>
            </div>
            {normalized.warnings.map((item, index) => <div className="notice" key={`warning-${index}`}>{String(item)}</div>)}
            {normalized.errors.map((item, index) => <div className="notice danger" key={`error-${index}`}>{String(item)}</div>)}
            {normalized.diagnostics.map((item, index) => <div className="notice" key={`diagnostic-${index}`}>{diagnosticText(item)}</div>)}
            {commitResult?.success ? <div className="notice">{commitResult.message}</div> : null}
            {rows.length ? (
              <section className="stack-form">
                <h3>Besoins horaires détectés</h3>
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
                <h3>Disponibilités professeurs détectées</h3>
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
                <h3>Contraintes détectées</h3>
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
            {scheduleGridRows.length ? (
              <section className="stack-form schedule-grid-review">
                <div className="section-head">
                  <div>
                    <h3>Grille planning en aperçu</h3>
                    <p>Ces cours sont détectés depuis une grille. Confirmez-les avant import réel.</p>
                  </div>
                </div>
                <div className="table-wrap">
                  <table className="review-table">
                    <thead>
                      <tr>
                        <th>Statut</th>
                        <th>Classe / groupe</th>
                        <th>Jour</th>
                        <th>Créneau</th>
                        <th>Cellule originale</th>
                        <th>Matière détectée</th>
                        <th>Prof détecté</th>
                        <th>Confiance</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scheduleGridRows.map((candidate, index) => {
                        const key = candidateKey(candidate, index);
                        const review = candidateReviews[key] || defaultCandidateReview(candidate);
                        const confidence = candidateConfidence(candidate);
                        const lowConfidence = isLowConfidenceCandidate(candidate);
                        const updateReview = (patch) => {
                          setCandidateReviews((current) => ({
                            ...current,
                            [key]: { ...defaultCandidateReview(candidate), ...current[key], ...patch },
                          }));
                        };
                        return (
                          <tr className={`review-row ${review.status}`} key={key}>
                            <td>
                              <span className={`review-status ${review.status}`}>{candidateStatusLabel(review.status)}</span>
                              {lowConfidence ? <span className="review-warning">À vérifier</span> : null}
                            </td>
                            <td>{candidateValue(candidate, ["class_name", "class", "group_name", "group"], t.unavailable)}</td>
                            <td>{candidateValue(candidate, ["day"], t.unavailable)}</td>
                            <td>{candidateValue(candidate, ["slot_label", "time", "slot"], t.unavailable)}</td>
                            <td className="raw-cell">{candidateValue(candidate, ["raw_cell", "original_cell_text", "cell_text", "text"], t.unavailable)}</td>
                            <td>
                              <input
                                aria-label="Modifier la matière détectée"
                                disabled={review.status === "ignored"}
                                value={review.subject}
                                onChange={(event) => updateReview({ subject: event.target.value })}
                              />
                            </td>
                            <td>
                              <input
                                aria-label="Modifier le professeur détecté"
                                disabled={review.status === "ignored"}
                                value={review.teacher}
                                onChange={(event) => updateReview({ teacher: event.target.value })}
                              />
                            </td>
                            <td>{formatConfidence(confidence) || t.unavailable}</td>
                            <td>
                              <div className="row-actions">
                                <button className="secondary-button compact-button" type="button" onClick={() => updateReview({ status: "accepted" })}>
                                  Accepter
                                </button>
                                <button className="secondary-button compact-button" type="button" onClick={() => updateReview({ status: "ignored" })}>
                                  Ignorer
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
            {!rows.length && !availabilityRows.length && !constraintRows.length && !scheduleGridRows.length ? <EmptyState title="אין שורות Preview להצגה" description="בדמו המסחרי הנתונים נטענים לשרת והאבחון מציג את הבעיות." /> : null}
            <details className="notice">
              <summary>Raw response</summary>
              <pre>{JSON.stringify(normalized.raw, null, 2)}</pre>
            </details>
          </section>
        </>
      ) : null}
    </>
  );
}
