import { useState } from "react";
import { commitExcelImport, loadRepairDemo, previewExcel } from "../api/schoolApi.js";
import { PageHeader } from "../components/PageHeader.jsx";
import { EmptyState } from "../components/EmptyState.jsx";

function previewSummary(preview) {
  const counts = preview?.counts || {};
  return [
    ["כיתות", counts.classes || 0],
    ["מורים", counts.teachers || 0],
    ["מקצועות", counts.subjects || 0],
    ["שעות", counts.slots || 0],
    ["שורות לא תקינות", (preview?.warnings || []).length + (preview?.errors || []).length],
  ];
}

export function ImportExcelPage({ navigate, refreshData, setImportPreview, t }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [commitResult, setCommitResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await previewExcel(file);
      setPreview(result);
      setCommitResult(null);
      setImportPreview(result);
    } catch (err) {
      setError(err.message || t.error);
    } finally {
      setLoading(false);
    }
  };

  const importPreview = async () => {
    if (!preview?.can_commit) return;
    setLoading(true);
    setError("");
    setCommitResult(null);
    try {
      const result = await commitExcelImport({
        import_id: preview.import_id,
        lessons: preview.import_id ? undefined : preview.lessons,
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
          <input type="file" accept=".xlsx" onChange={(event) => setFile(event.target.files?.[0] || null)} />
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
            {previewSummary(preview).map(([label, value]) => (
              <article className="stat-card" key={label}><span>{label}</span><strong>{value}</strong></article>
            ))}
          </section>
          <section className="panel">
            <div className="section-head">
              <h3>Preview</h3>
              <div className="action-row">
                <button className="primary-button" disabled={!preview.can_commit || loading} type="button" onClick={importPreview}>
                  {language === "he" ? "ייבא Planning" : "Importer"}
                </button>
                <button className="secondary-button" type="button" onClick={() => navigate("diagnostic")}>{t.runDiagnostic}</button>
              </div>
            </div>
            {(preview.warnings || []).map((item) => <div className="notice" key={item}>{item}</div>)}
            {(preview.errors || []).map((item) => <div className="notice danger" key={item}>{item}</div>)}
            {commitResult?.success ? <div className="notice">{commitResult.message}</div> : null}
            {(preview.lessons || []).slice(0, 12).map((lesson, index) => (
              <div className="schedule-item" key={`${lesson.row}-${lesson.column}-${index}`}>
                <time>{lesson.day} {lesson.slot_label || lesson.slot}</time>
                <strong>{lesson.class_name || t.unavailable}</strong>
                <span>{lesson.subject || t.unavailable}</span>
                <span>{lesson.teacher || t.unavailable}</span>
              </div>
            ))}
            {!(preview.lessons || []).length ? <EmptyState title="אין שורות Preview להצגה" description="בדמו המסחרי הנתונים נטענים לשרת והאבחון מציג את הבעיות." /> : null}
          </section>
        </>
      ) : null}
    </>
  );
}
