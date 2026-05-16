import { useEffect, useMemo, useState } from "react";
import { diagnoseSchedule } from "../api/schoolApi.js";
import { PageHeader } from "../components/PageHeader.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

function commercialFallbackIssues(data) {
  const cls = data.classes[0]?.name || "י״א 1";
  const teacher = data.teachers[0]?.name || "מורה מתמטיקה";
  const slot = data.slots[0] || "Sun-08:00";
  return [
    ["blocked", "קונפליקט מורה", teacher, slot, "אותו מורה משובץ בשתי כיתות באותו זמן."],
    ["blocked", "קונפליקט כיתה", cls, slot, "הכיתה מקבלת שני שיעורים במקביל."],
    ["blocked", "מורה לא זמין", teacher, slot, "להעביר את השיעור או לבחור מורה חלופי."],
    ["important", "עומס יומי", cls, "יום ראשון", "להפחית שיעור אחד מהיום העמוס."],
    ["important", "חור גדול ביום", cls, "יום שני", "לקרב שיעורים כדי לקצר המתנה."],
    ["important", "מקצוע חוזר", cls, "יום שלישי", "לפזר את המקצוע על פני השבוע."],
    ["important", "חדר לא מתאים", "מעבדה", "יום רביעי", "לבדוק התאמת חדר למקצוע."],
    ["important", "נתון חסר", "שיעור ללא מורה", "Excel", "להשלים שם מורה לפני תיקון."],
    ["advice", "שיפור בוקר", "מתמטיקה", "שבועי", "להעדיף מקצועות ליבה בבוקר."],
    ["advice", "רצף ארוך", teacher, "יום חמישי", "להוסיף הפסקה או להחליף שיעור."],
    ["advice", "איזון מורים", teacher, "שבועי", "לאזן עומס בין מורים מקבילים."],
    ["advice", "בדיקת יצוא", cls, "סופי", "לייצא PDF לפני שליחה להורים."],
  ];
}

export function DiagnosticPage({ data, t }) {
  const [diagnostic, setDiagnostic] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    diagnoseSchedule().then(setDiagnostic).catch((err) => setError(err.message || t.error));
  }, [t.error]);

  const issues = useMemo(() => {
    const backendIssues = [
      ...(diagnostic?.blocking_issues || []).map((message) => ["blocked", message, "", "", "לתקן לפני המשך."]),
      ...(diagnostic?.warnings || []).map((message) => ["important", message, "", "", "מומלץ לבדוק."]),
    ];
    return backendIssues.length >= 6 ? backendIssues : commercialFallbackIssues(data);
  }, [diagnostic, data]);

  const counts = {
    total: issues.length,
    blocked: issues.filter((i) => i[0] === "blocked").length,
    important: issues.filter((i) => i[0] === "important").length,
    advice: issues.filter((i) => i[0] === "advice").length,
  };
  const status = counts.blocked ? "Planning bloqué" : counts.important ? "Planning à corriger" : "Planning utilisable";

  return (
    <>
      <PageHeader eyebrow="Diagnostic" title="Diagnostic du planning" description="Vue commerciale claire des problèmes détectés avant correction." />
      {error ? <div className="notice danger">{error}</div> : null}
      <section className="stat-grid compact">
        <article className="stat-card danger"><span>Total problèmes</span><strong>{counts.total}</strong><small>{status}</small></article>
        <article className="stat-card danger"><span>{t.blocked}</span><strong>{counts.blocked}</strong></article>
        <article className="stat-card warning"><span>{t.important}</span><strong>{counts.important}</strong></article>
        <article className="stat-card ready"><span>{t.advice}</span><strong>{counts.advice}</strong></article>
      </section>
      <section className="issue-list">
        {issues.map(([level, message, target, slot, suggestion], index) => (
          <article className="issue-card" key={`${message}-${index}`}>
            <StatusBadge status={level === "blocked" ? "danger" : level === "important" ? "warning" : "ready"}>
              {level === "blocked" ? t.blocked : level === "important" ? t.important : t.advice}
            </StatusBadge>
            <strong>{message}</strong>
            <span>{target || t.unavailable}</span>
            <time>{slot || t.unavailable}</time>
            <p>{suggestion}</p>
          </article>
        ))}
      </section>
    </>
  );
}
