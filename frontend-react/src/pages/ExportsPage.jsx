import { useState } from "react";
import { exportRepairProposalPdf, exportSchedule } from "../api/schoolApi.js";
import { PageHeader } from "../components/PageHeader.jsx";

function saveBlob({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function ExportsPage({ activeProposal, t }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  const runExport = async (format) => {
    setBusy(format);
    setMessage("");
    try {
      const result = await exportSchedule(format);
      saveBlob(result);
      setMessage(t.success);
    } catch (err) {
      setMessage(err.message || t.error);
    } finally {
      setBusy("");
    }
  };

  const runProposalPdf = async () => {
    if (!activeProposal?.proposal_id) return;
    setBusy("proposal");
    try {
      saveBlob(await exportRepairProposalPdf(activeProposal.proposal_id));
      setMessage(t.success);
    } catch (err) {
      setMessage(err.message || t.error);
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <PageHeader eyebrow="Export" title="Exports imprimables / WhatsApp-friendly" description="PDF pour impression ou envoi, CSV/JSON pour travail administratif." />
      {message ? <div className="notice">{message}</div> : null}
      <section className="card-grid">
        <article className="option-card">
          <h3>{t.exportPdf}</h3>
          <p>Planning corrigé imprimable.</p>
          <button className="primary-button" disabled={!!busy} onClick={() => runExport("pdf")} type="button">{busy === "pdf" ? t.loading : t.exportPdf}</button>
        </article>
        <article className="option-card">
          <h3>{t.exportCsv}</h3>
          <p>Compatible tableur.</p>
          <button className="secondary-button" disabled={!!busy} onClick={() => runExport("csv")} type="button">{t.exportCsv}</button>
        </article>
        <article className="option-card">
          <h3>{t.exportJson}</h3>
          <p>Données brutes.</p>
          <button className="secondary-button" disabled={!!busy} onClick={() => runExport("json")} type="button">{t.exportJson}</button>
        </article>
        <article className="option-card">
          <h3>{t.exportExcel}</h3>
          <p>TODO: endpoint Excel non disponible dans OpenAPI.</p>
          <button className="secondary-button" disabled type="button">{t.unavailable}</button>
        </article>
        <article className="option-card">
          <h3>PDF proposition</h3>
          <p>Rapport avant acceptation.</p>
          <button className="secondary-button" disabled={!activeProposal?.proposal_id || !!busy} onClick={runProposalPdf} type="button">Exporter proposition</button>
        </article>
      </section>
    </>
  );
}
