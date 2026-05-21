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
  const normalizedPreview = safe.normalized_preview || safe.preview || {};
  return {
    import_id: safe.import_id || safe.importId || null,
    status: safe.status || "unknown",
    filename: safe.filename || safe.file_name || "",
    global_confidence: safe.global_confidence ?? safe.confidence ?? safe.confidence_score ?? null,
    can_apply: Boolean(safe.can_apply ?? safe.can_commit),
    can_commit: Boolean(safe.can_commit ?? safe.can_apply),
    summary: Object.keys(summary).length
      ? summary
      : {
          classes_count: counts.classes || 0,
          teachers_count: counts.teachers || 0,
          subjects_count: counts.subjects || 0,
          slots_count: counts.slots || 0,
          requirements_count: counts.lessons || 0,
        },
    sheet_profiles: asArray(safe.sheet_profiles),
    sheet_classifications: asArray(safe.sheet_classifications),
    diagnostics: asArray(safe.diagnostics),
    human_questions: asArray(safe.human_questions),
    normalized_preview: normalizedPreview || {},
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
    ["שעות", summary.slots_count ?? summary.slots ?? 0],
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

export function ImportExcelPage({ navigate, refreshData, setImportPreview, t, language }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [commitResult, setCommitResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const normalized = preview ? normalizeImportResult(preview) : null;
  const rows = previewRows(normalized);
  const previewKeys = Object.keys(asObject(normalized?.normalized_preview));
  const hasMinimalResponse = normalized && !previewKeys.length && !rows.length;

  const submit = async (event) => {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await previewExcel(file);
      setPreview(result);
      setCommitResult(null);
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
                <button className="primary-button" disabled={(!normalized.can_commit && !normalized.can_apply) || loading} type="button" onClick={importPreview}>
                  {language === "he" ? "ייבא Planning" : "Importer"}
                </button>
                <button className="secondary-button" type="button" onClick={() => navigate("diagnostic")}>{t.runDiagnostic}</button>
              </div>
            </div>
            {hasMinimalResponse ? <div className="notice">Analyse reçue. Aperçu minimal disponible.</div> : null}
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
            {!rows.length ? <EmptyState title="אין שורות Preview להצגה" description="בדמו המסחרי הנתונים נטענים לשרת והאבחון מציג את הבעיות." /> : null}
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
