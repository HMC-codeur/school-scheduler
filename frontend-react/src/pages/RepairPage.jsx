import { useState } from "react";
import { acceptRepairProposal, generateSchedule, rejectRepairProposal, repairSchedule } from "../api/schoolApi.js";
import { PageHeader } from "../components/PageHeader.jsx";
import { EmptyState } from "../components/EmptyState.jsx";

export function RepairPage({ data, refreshData, setActiveProposal, navigate, t }) {
  const [proposal, setProposal] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const propose = async () => {
    setBusy(true);
    setMessage("");
    try {
      if (!Object.keys(data.schedule || {}).length) {
        await generateSchedule();
        await refreshData();
      }
      const target = data.classes[0]?.name;
      const result = await repairSchedule({
        repair_type: "repair_class",
        repair_policy: "balanced",
        repair_target: target,
        commit: false,
      });
      setProposal(result);
      setActiveProposal(result);
      setMessage(result.message || t.success);
    } catch (err) {
      setMessage(err.message || t.error);
    } finally {
      setBusy(false);
    }
  };

  const accept = async () => {
    if (!proposal?.proposal_id) return;
    setBusy(true);
    try {
      const result = await acceptRepairProposal(proposal.proposal_id);
      setActiveProposal(result);
      await refreshData();
      setMessage("התיקון התקבל ונשמר");
    } catch (err) {
      setMessage(err.message || t.error);
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!proposal?.proposal_id) return;
    setBusy(true);
    try {
      await rejectRepairProposal(proposal.proposal_id);
      setProposal(null);
      setActiveProposal(null);
      setMessage("ההצעה נדחתה");
    } catch (err) {
      setMessage(err.message || t.error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Repair"
        title="Réparation proposée"
        description="המערכת מציעה תיקון מקומי ושומרת את ההצעה עד לאישור."
        action={<button className="primary-button" disabled={busy} type="button" onClick={propose}>{t.proposeRepair}</button>}
      />
      {message ? <div className={`notice ${message.includes("failed") || message.includes("נכשלה") ? "danger" : ""}`}>{message}</div> : null}
      {!proposal ? <EmptyState title="אין הצעה פעילה" description="לחץ על הצעת תיקון כדי ליצור הצעה לפני/אחרי." /> : null}
      {proposal ? (
        <section className="card-grid">
          <article className="option-card">
            <h3>הצעה 1</h3>
            <strong>{proposal.stability_score ?? t.unavailable}</strong>
            <span>score de stabilité</span>
            <p>{proposal.message}</p>
            <div className="mini-metrics">
              <span>שינויים: {proposal.changed_sessions ?? t.unavailable}</span>
              <span>נפתרו: {proposal.hard_conflicts === 0 ? "כן" : t.unavailable}</span>
              <span>נותרו: {proposal.hard_conflicts ?? t.unavailable}</span>
            </div>
            <div className="action-row">
              <button className="secondary-button" type="button" onClick={() => navigate("compare")}>{t.compareBeforeAfter}</button>
              <button className="primary-button" disabled={busy || !proposal.proposal_id} type="button" onClick={accept}>{t.accept}</button>
              <button className="secondary-button" disabled={busy || !proposal.proposal_id} type="button" onClick={reject}>{t.reject}</button>
            </div>
          </article>
        </section>
      ) : null}
    </>
  );
}
