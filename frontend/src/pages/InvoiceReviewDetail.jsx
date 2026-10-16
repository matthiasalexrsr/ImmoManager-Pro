import NotificationArrival from '../components/NotificationArrival';
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import FileViewer from '../components/FileViewer';
import PdfPreview from '../components/PdfPreview';
import { fileKind, resolveFileUrl } from '../features/partyWorkspace/files';
import { formatMoney } from '../utils/format';
import { Pill } from '../features/maintenanceProject/ProjectUi';
import { STATUS_TONE, reviewApi } from '../features/invoiceReview/reviewApi';
import {
  Checks, Decision, Dispute, Findings, History, Payment, ReceiptForm, Summary, Transfer,
} from '../features/invoiceReview/ReviewPanels';
import { useReviewText } from '../features/invoiceReview/text';
import '../features/maintenanceProject/maintenanceProject.css';
import '../features/invoiceReview/invoiceReview.css';

const INTEGRITY_TONE = { unchanged: 'green', changed: 'red', unavailable: 'orange', unverified: 'gray' };

// One invoice under review: the original document beside the checks, the decision and the history.
export default function InvoiceReviewDetail() {
  const { id } = useParams();
  return <InvoiceReviewSession key={id} id={id} />;
}

function InvoiceReviewSession({ id }) {
  const { tx } = useReviewText();
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [properties, setProperties] = useState([]);
  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    reviewApi.load(id, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setView(value); })
      .catch(failure => { if (failure.name !== 'AbortError') setError(failure.message || tx.loadFailed); });
    return () => controller.abort();
  }, [id, revision, tx]);

  useEffect(() => {
    if (!view || view.review) return undefined;
    const controller = new AbortController();
    api.list('/properties', { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setProperties(value); }).catch(() => {});
    return () => controller.abort();
  }, [view]);

  if (error) {
    return (
      <div className="page ir-page">
        <Link to="/invoice-review" className="btn btn-ghost btn-sm">{tx.back}</Link>
        <div className="alert-error" role="alert">{error}
          <button type="button" className="btn btn-ghost btn-sm" onClick={reload}>{tx.retry}</button></div>
      </div>
    );
  }
  if (!view) return <div className="page ir-page"><p className="text-muted" role="status">{tx.loading}</p></div>;

  const { invoice, abilities } = view;
  const readOnly = !Object.entries(abilities).some(([key, value]) => value && !['decide_above_limit', 'settings'].includes(key));
  return (
    <div className="page ir-page">
      <Link to="/invoice-review" className="btn btn-ghost btn-sm ir-back">{tx.back}</Link>
      <div className="page-header ir-header">
        <NotificationArrival record={invoice} ready={!error} /><h1>{invoice.supplier} {invoice.invoice_number ? `· ${invoice.invoice_number}` : ''}</h1>
        <div className="ir-row-state">
          <Pill tone={STATUS_TONE[view.status]}>{view.kind === 'credit_note' ? tx.creditNote : tx[`status_${view.status}`]}</Pill>
          <strong>{formatMoney(invoice.gross_amount)}</strong>
        </div>
      </div>
      {readOnly && <p className="ir-note">{tx.readOnly}</p>}
      <div className="ir-review">
        <DocumentPane document={view.document} />
        <div className="ir-panels">
          <Summary view={view} />
          <Findings view={view} />
          {!view.review && abilities.receive && <ReceiptForm view={view} properties={properties} onChanged={reload} />}
          {view.review && <Checks key={`checks-${revision}`} view={view} onChanged={reload} />}
          <Decision key={`decision-${revision}`} view={view} onChanged={reload} />
          <Payment key={`payment-${revision}`} view={view} onChanged={reload} />
          <Dispute key={`dispute-${revision}`} view={view} onChanged={reload} />
          <Transfer key={`transfer-${revision}`} view={view} onChanged={reload} />
          <History view={view} />
        </div>
      </div>
    </div>
  );
}

function DocumentPane({ document }) {
  const { tx } = useReviewText();
  const [open, setOpen] = useState(false);
  if (!document) {
    return <aside className="ir-document panel" aria-label={tx.document}><p className="text-muted">{tx.noDocument}</p></aside>;
  }
  const kind = fileKind(document.file_url);
  return (
    <aside className="ir-document panel" aria-label={tx.document}>
      <div className="ir-document-head">
        <strong>{document.title}</strong>
        <Pill tone={INTEGRITY_TONE[document.integrity]}>{tx[`integrity_${document.integrity}`]}</Pill>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setOpen(true)}>{tx.openDocument}</button>
      </div>
      {kind === 'pdf' && <div className="ir-document-view"><PdfPreview url={resolveFileUrl(document.file_url)} title={document.title} /></div>}
      {open && <FileViewer fileUrl={document.file_url} title={document.title} onClose={() => setOpen(false)} />}
    </aside>
  );
}
