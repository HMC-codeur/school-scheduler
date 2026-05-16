import { PageHeader } from "../components/PageHeader.jsx";
import { EmptyState } from "../components/EmptyState.jsx";

function flatten(schedule) {
  return Object.entries(schedule || {}).flatMap(([slot, classes]) =>
    Object.entries(classes || {}).map(([className, cell]) => ({
      key: `${slot}-${className}-${cell.subject}-${cell.teacher}`,
      slot,
      className,
      subject: cell.subject,
      teacher: cell.teacher,
    }))
  );
}

export function ComparePage({ data, activeProposal, t }) {
  const before = flatten(data.schedule).slice(0, 30);
  const after = flatten(activeProposal?.schedule || activeProposal?.proposed_schedule || {}).slice(0, 30);
  const changed = activeProposal?.changed_items || [];

  return (
    <>
      <PageHeader eyebrow="Avant / Après" title="Comparaison avant/après" description="Vue simple pour comprendre ce qui change avant acceptation." />
      {!activeProposal ? <EmptyState title="אין הצעה להשוואה" description="צור הצעת תיקון במסך Réparation." /> : null}
      {activeProposal ? (
        <>
          <section className="compare-grid">
            <div className="panel">
              <h3>Planning actuel</h3>
              {before.map((row) => <div className="schedule-item" key={row.key}><time>{row.slot}</time><strong>{row.className}</strong><span>{row.subject}</span><span>{row.teacher}</span></div>)}
            </div>
            <div className="panel">
              <h3>Planning corrigé</h3>
              {after.map((row) => <div className="schedule-item highlighted" key={row.key}><time>{row.slot}</time><strong>{row.className}</strong><span>{row.subject}</span><span>{row.teacher}</span></div>)}
            </div>
          </section>
          <section className="panel">
            <h3>Liste des changements</h3>
            {changed.length ? changed.map((item, index) => (
              <div className="change-row" key={`${item.session_id}-${index}`}>
                <span>{item.class_name || t.unavailable}</span>
                <span>{item.subject_name || t.unavailable}</span>
                <span>{item.old_slot || "-"}</span>
                <span>{item.new_slot || "-"}</span>
                <span>{item.old_teacher_name || item.new_teacher_name || t.unavailable}</span>
                <span>{item.reason || t.unavailable}</span>
              </div>
            )) : <p className="muted">Aucun détail de changement disponible.</p>}
          </section>
        </>
      ) : null}
    </>
  );
}
