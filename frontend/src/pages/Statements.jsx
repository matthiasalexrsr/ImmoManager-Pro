import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

/** Inline toast-style notification hook. */
function useToast() {
  const [toast, setToast] = useState(null);
  const timerRef = useRef(null);
  const show = (message, type = 'error') => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setToast({ message, type });
    timerRef.current = setTimeout(() => setToast(null), 5000);
  };
  const dismiss = () => { setToast(null); if (timerRef.current) clearTimeout(timerRef.current); };
  const Toast = toast ? (
    <div
      className={`toast toast-${toast.type}`}
      onClick={dismiss}
      style={{ position: 'fixed', bottom: '1.5rem', right: '1.5rem', zIndex: 9999,
               padding: '0.75rem 1.25rem', borderRadius: '8px', cursor: 'pointer',
               background: toast.type === 'success' ? 'var(--teal, #0d9488)' : 'var(--color-error, #dc2626)',
               color: '#fff', boxShadow: '0 4px 12px rgba(0,0,0,0.15)', maxWidth: '400px' }}
    >
      {toast.message}
    </div>
  ) : null;
  return { show, Toast };
}

/** Simple prompt modal to replace window.prompt. */
function PromptModal({ title, defaultValue, onConfirm, onCancel }) {
  const [value, setValue] = useState(defaultValue || '');
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '450px' }}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="btn btn-sm" onClick={onCancel}>&times;</button>
        </div>
        <div className="modal-body">
          <input
            className="form-input"
            value={value}
            onChange={e => setValue(e.target.value)}
            autoFocus
            style={{ width: '100%' }}
          />
        </div>
        <div className="modal-footer" style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', padding: '0.75rem 1rem' }}>
          <button className="btn btn-sm btn-secondary" onClick={onCancel}>Abbrechen</button>
          <button className="btn btn-sm btn-primary" onClick={() => onConfirm(value)}>OK</button>
        </div>
      </div>
    </div>
  );
}

function getColumns(t) {
  return [
    { key: 'property_name', label: t('pages.statements.colProperty') || 'Immobilie', filterType: 'text' },
    { key: 'period_label', label: t('pages.statements.colPeriod') || 'Abrechnungszeitraum', filterType: 'text' },
    { key: 'total_costs', label: t('pages.statements.colTotalCosts') || 'Gesamtkosten (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'units_count', label: t('pages.statements.colUnits') || 'Einheiten', type: 'number' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];
}

function getCostColumns(t) {
  return [
    { key: 'description', label: t('pages.statements.colCostType') || 'Kostenart', filterType: 'text' },
    { key: 'amount', label: t('pages.statements.colAmount') || 'Betrag (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'allocation_key_name', label: t('pages.statements.colAllocationKey') || 'Verteilerschlüssel' },
  ];
}

function getStmtColumns(t, onError) {
  return [
    { key: 'unit_label', label: t('pages.statements.colUnit') || 'Einheit' },
    { key: 'total_cost', label: t('pages.statements.colShare') || 'Anteil (€)', type: 'number', align: 'right',
      render: v => `${Number(v || 0).toFixed(2)} €` },
    { key: 'advance_paid', label: t('pages.statements.colAdvancePaid') || 'Vorauszahlung (€)', type: 'number', align: 'right',
      render: v => `${Number(v || 0).toFixed(2)} €` },
    { key: 'balance', label: t('pages.statements.colBalance') || 'Saldo (€)', type: 'number', align: 'right',
      render: (v) => {
        const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
        return <span className={cls}>{Number(v || 0).toFixed(2)} €</span>;
      }},
    { key: 'delivery_status', label: t('pages.statements.colDelivery') || 'Zustellung',
      render: v => v ? <StatusBadge status={v} /> : <span className="text-muted">—</span> },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status' },
    { key: 'pdf_action', label: '',
      render: (_, row) => (
        <button
          className="btn btn-sm btn-secondary"
          title={t('pages.statements.pdfDownload') || 'PDF herunterladen'}
          onClick={(e) => { e.stopPropagation(); downloadStatementPdf(row.id, onError); }}
        >
          PDF
        </button>
      )},
  ];
}

/** Trigger browser download of a single statement PDF. */
function downloadStatementPdf(statementId, onError) {
  const token = localStorage.getItem('access_token');
  fetch(`/api/v1/billing/statements/${statementId}/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(res => {
    if (!res.ok) throw new Error('PDF-Download fehlgeschlagen');
    return res.blob();
  }).then(blob => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `abrechnung_${statementId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  }).catch(err => onError?.(err.message) || console.error(err.message));
}

/** Helper: is a period in a mutable (editable) state? */
function isMutable(status) {
  return status === 'draft' || status === 'review';
}

export default function Statements() {
  const { t } = useTranslation();
  const toast = useToast();
  const [periods, setPeriods] = useState([]);
  const [costItems, setCostItems] = useState([]);
  const [statements, setStatements] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [allocationKeys, setAllocationKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [, setLoadError] = useState(null);
  const [modal, setModal] = useState(null);
  const [selectedPeriod, setSelectedPeriod] = useState(null);
  const [costModal, setCostModal] = useState(null);
  const [view, setView] = useState('list');
  const [preflight, setPreflight] = useState(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [submittingReview, setSubmittingReview] = useState(false);
  const [creatingRevision, setCreatingRevision] = useState(false);
  const [creatingReceivables, setCreatingReceivables] = useState(false);
  const [markingDelivered, setMarkingDelivered] = useState(false);
  const [ocrDraft, setOcrDraft] = useState(null);
  const [ocrUploading, setOcrUploading] = useState(false);
  const [disputing, setDisputing] = useState(false);
  const [, setPromptModal] = useState(null);

  const loadData = () => {
    setLoadError(null);
    Promise.all([
      api.get('/billing/periods'),
      api.get('/billing/cost-items'),
      api.get('/billing/statements'),
      api.get('/properties'),
      api.get('/units'),
      api.get('/billing/allocation-keys'),
    ]).then(([bp, ci, us, props, u, ak]) => {
      setPeriods(bp || []);
      setCostItems(ci || []);
      setStatements(us || []);
      setProperties(props || []);
      setUnits(u || []);
      setAllocationKeys(ak || []);
    }).catch(err => {
      setLoadError(err.message || 'Daten konnten nicht geladen werden');
      toast.show(err.message || 'Daten konnten nicht geladen werden');
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- loadData is stable, called on mount only

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const akMap = Object.fromEntries(allocationKeys.map(k => [k.id, k]));

  const enriched = periods.map(bp => {
    const costs = costItems.filter(ci => ci.billing_period_id === bp.id);
    const totalCosts = costs.reduce((s, c) => s + (c.amount || 0), 0);
    const stmts = statements.filter(s => s.billing_period_id === bp.id);
    return {
      ...bp,
      property_name: propMap[bp.property_id]?.name || '—',
      period_label: `${bp.start_date || '?'} – ${bp.end_date || '?'}`,
      total_costs: totalCosts,
      units_count: stmts.length,
    };
  });

  const fields = [
    { key: 'property_id', label: t('pages.statements.formProperty') || 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: t('pages.statements.formLabel') || 'Bezeichnung', required: true, placeholder: 'z.B. NK-Abrechnung 2025' },
    { key: 'start_date', label: t('pages.statements.formStart') || 'Beginn', type: 'date', required: true },
    { key: 'end_date', label: t('pages.statements.formEnd') || 'Ende', type: 'date', required: true },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'draft', options: [
      { value: 'draft', label: t('ui.filterChips.draft') || 'Entwurf' },
      { value: 'review', label: t('status.contract.inReview') || 'In Prüfung' },
      { value: 'finalized', label: t('status.general.completed') || 'Abgeschlossen' },
      { value: 'disputed', label: t('pages.statements.dispute') || 'Widerspruch' },
    ]},
  ];

  const costFields = [
    { key: 'billing_period_id', label: t('pages.statements.formPeriod') || 'Abrechnungsperiode', type: 'select', required: true,
      options: periods.map(p => ({ value: p.id, label: p.label || `${p.start_date} – ${p.end_date}` })) },
    { key: 'description', label: t('pages.statements.formCostType') || 'Kostenart', required: true, placeholder: 'z.B. Wasser, Heizung, Müll' },
    { key: 'amount', label: t('pages.statements.formAmount') || 'Betrag (€)', type: 'number', required: true },
    { key: 'allocation_key_id', label: t('pages.statements.formAllocationKey') || 'Verteilerschlüssel', type: 'select', required: true,
      options: allocationKeys.map(k => ({ value: k.id, label: `${k.name} (${k.key_type})` })) },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/billing/periods', data);
    } else if (modal === 'copy') {
      const newPeriod = await api.post('/billing/periods', data);
      if (newPeriod && selectedPeriod) {
        const prevCosts = costItems.filter(ci => ci.billing_period_id === selectedPeriod.id);
        for (const cost of prevCosts) {
          await api.post('/billing/cost-items', {
            billing_period_id: newPeriod.id,
            description: cost.description,
            amount: 0,
            allocation_key_id: cost.allocation_key_id,
          }).catch(() => { toast.show('Kostenposition konnte nicht kopiert werden'); });
        }
      }
    } else {
      await api.put(`/billing/periods/${modal.id}`, data);
    }
    loadData();
  };

  const handleSaveCost = async (data) => {
    if (costModal === 'create') {
      await api.post('/billing/cost-items', data);
    } else {
      await api.put(`/billing/cost-items/${costModal.id}`, data);
    }
    loadData();
  };

  const handleGenerateStatements = async () => {
    if (!selectedPeriod) return;
    setGenerating(true);
    try {
      await api.post(`/billing/periods/${selectedPeriod.id}/generate`, {});
      await loadData();
      const pf = await api.get(`/billing/periods/${selectedPeriod.id}/preflight`).catch(() => null);
      setPreflight(pf);
    } catch (err) {
      toast.show(err.message || 'Generierung fehlgeschlagen');
    } finally {
      setGenerating(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!selectedPeriod) return;
    setSubmittingReview(true);
    try {
      const updated = await api.post(`/billing/periods/${selectedPeriod.id}/submit-review`, {});
      setSelectedPeriod(updated);
      await loadData();
    } catch (err) {
      toast.show(err.message || 'Statuswechsel fehlgeschlagen');
    } finally {
      setSubmittingReview(false);
    }
  };

  const handleRevertDraft = async () => {
    if (!selectedPeriod) return;
    try {
      const updated = await api.post(`/billing/periods/${selectedPeriod.id}/revert-draft`, {});
      setSelectedPeriod(updated);
      await loadData();
    } catch (err) {
      toast.show(err.message || 'Zurücksetzen fehlgeschlagen');
    }
  };

  const handleFinalizePeriod = async () => {
    if (!selectedPeriod || !isMutable(selectedPeriod.status)) return;
    setFinalizing(true);
    try {
      const updated = await api.post(`/billing/periods/${selectedPeriod.id}/finalize`, {});
      setSelectedPeriod(updated);
      await loadData();
      const pf = await api.get(`/billing/periods/${selectedPeriod.id}/preflight`).catch(() => null);
      setPreflight(pf);
    } catch (err) {
      toast.show(err.message || 'Finalisierung fehlgeschlagen');
    } finally {
      setFinalizing(false);
    }
  };

  const handleMarkDelivered = async () => {
    if (!selectedPeriod) return;
    setMarkingDelivered(true);
    try {
      const periodStatements = (statements || []).filter(s => s.billing_period_id === selectedPeriod.id);
      for (const stmt of periodStatements) {
        if (stmt.status !== 'delivered') {
          await api.post(`/billing/statements/${stmt.id}/mark-delivered`, {});
        }
      }
      await loadData();
      const refreshedPeriod = await api.get(`/billing/periods/${selectedPeriod.id}`).catch(() => selectedPeriod);
      setSelectedPeriod(refreshedPeriod || selectedPeriod);
    } catch (err) {
      toast.show(err.message || 'Zustellstatus konnte nicht gesetzt werden');
    } finally {
      setMarkingDelivered(false);
    }
  };

  const handleCreateReceivables = async () => {
    if (!selectedPeriod) return;
    setCreatingReceivables(true);
    try {
      const res = await api.post(`/billing/periods/${selectedPeriod.id}/create-receivables`, {});
      toast.show(`Forderungen erzeugt: ${res?.created_receivables ?? 0}`, 'success');
    } catch (err) {
      toast.show(err.message || 'Forderungen konnten nicht erzeugt werden');
    } finally {
      setCreatingReceivables(false);
    }
  };

  const handleCreateRevision = () => {
    if (!selectedPeriod) return;
    setPromptModal({
      title: t('pages.statements.revisionReason') || 'Grund für Korrektur (optional):',
      onConfirm: async (notes) => {
        setPromptModal(null);
        setCreatingRevision(true);
        try {
          const res = await api.post(
            `/billing/periods/${selectedPeriod.id}/revisions?revision_notes=${encodeURIComponent(notes)}`,
            {}
          );
          await loadData();
          if (res?.new_period_id) {
            const allPeriods = await api.get('/billing/periods').catch(() => []);
            const newPeriod = (allPeriods || []).find(p => p.id === res.new_period_id);
            if (newPeriod) handleSelectPeriod(newPeriod);
          }
        } catch (err) {
          toast.show(err.message || t('pages.statements.revisionError') || 'Korrektur konnte nicht erstellt werden');
        } finally {
          setCreatingRevision(false);
        }
      },
    });
  };

  const handleDispute = () => {
    if (!selectedPeriod) return;
    setPromptModal({
      title: t('pages.statements.disputeReason') || 'Grund für Widerspruch:',
      onConfirm: async (reason) => {
        setPromptModal(null);
        setDisputing(true);
        try {
          const updated = await api.post(
            `/billing/periods/${selectedPeriod.id}/dispute?reason=${encodeURIComponent(reason)}`,
            {}
          );
          setSelectedPeriod(updated);
          await loadData();
        } catch (err) {
          toast.show(err.message || 'Widerspruch konnte nicht eingelegt werden');
        } finally {
          setDisputing(false);
        }
      },
    });
  };

  const handleOcrUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !selectedPeriod) return;
    setOcrUploading(true);
    setOcrDraft(null);
    try {
      // Step 1: Upload file
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('access_token');
      const uploadRes = await fetch('/api/v1/files/upload?folder=billing-ocr', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!uploadRes.ok) throw new Error('Datei-Upload fehlgeschlagen');
      const uploadData = await uploadRes.json();

      // Step 2: Call OCR import endpoint
      const ocrRes = await api.post(
        `/billing/cost-items/import-ocr?billing_period_id=${selectedPeriod.id}&file_url=${encodeURIComponent(uploadData.file_url)}`,
        {}
      );

      if (ocrRes?.success) {
        setOcrDraft(ocrRes);
      } else {
        toast.show(ocrRes?.error || 'OCR-Erkennung fehlgeschlagen');
      }
    } catch (err) {
      toast.show(err.message || 'Import fehlgeschlagen');
    } finally {
      setOcrUploading(false);
      // Reset file input
      e.target.value = '';
    }
  };

  const handleAcceptOcrDraft = async () => {
    if (!ocrDraft?.draft) return;
    const draft = ocrDraft.draft;
    try {
      await api.post('/billing/cost-items', {
        billing_period_id: draft.billing_period_id,
        description: draft.description || 'Importierte Kostenposition',
        amount: draft.amount || 0,
        allocation_key_id: draft.allocation_key_id || allocationKeys[0]?.id,
        cost_category: draft.cost_category,
        source_document_id: draft.source_document_id,
      });
      setOcrDraft(null);
      loadData();
    } catch (err) {
      toast.show(err.message || 'Kostenposition konnte nicht gespeichert werden');
    }
  };

  const handleExportPeriod = async () => {
    if (!selectedPeriod) return;
    setExporting(true);
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`/api/v1/billing/periods/${selectedPeriod.id}/export?format=csv`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        let message = 'Export fehlgeschlagen';
        try {
          const body = await res.json();
          message = body?.detail || message;
        } catch { /* ignore */ }
        throw new Error(message);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `abrechnung_${selectedPeriod.id}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast.show(err.message || 'Export fehlgeschlagen');
    } finally {
      setExporting(false);
    }
  };

  const handleExportZip = async () => {
    if (!selectedPeriod) return;
    setExporting(true);
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`/api/v1/billing/periods/${selectedPeriod.id}/export-zip`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        let message = 'ZIP-Export fehlgeschlagen';
        try {
          const body = await res.json();
          message = body?.detail || message;
        } catch { /* ignore */ }
        throw new Error(message);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `abrechnungen_${selectedPeriod.id}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast.show(err.message || 'ZIP-Export fehlgeschlagen');
    } finally {
      setExporting(false);
    }
  };

  const handleSelectPeriod = (period) => {
    setSelectedPeriod(period);
    setView('detail');
    setPreflight(null);
    setPreflightLoading(true);
    api.get(`/billing/periods/${period.id}/preflight`)
      .then(setPreflight)
      .catch(() => setPreflight(null))
      .finally(() => setPreflightLoading(false));
  };

  // Build revision history for the selected period (periods with same property + date range)
  const getRevisionHistory = () => {
    if (!selectedPeriod) return [];
    return periods
      .filter(p =>
        p.property_id === selectedPeriod.property_id &&
        p.start_date === selectedPeriod.start_date &&
        p.end_date === selectedPeriod.end_date
      )
      .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  };

  const COLUMNS = getColumns(t);
  const COST_COLUMNS = getCostColumns(t);
  const STMT_COLUMNS = getStmtColumns(t, msg => toast.show(msg));

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  if (view === 'detail' && selectedPeriod) {
    const periodCosts = costItems.filter(ci => ci.billing_period_id === selectedPeriod.id)
      .map(ci => ({ ...ci, allocation_key_name: akMap[ci.allocation_key_id]?.name || '—' }));
    const periodStmts = statements.filter(s => s.billing_period_id === selectedPeriod.id)
      .map(s => ({ ...s, unit_label: unitMap[s.unit_id]?.label || '—' }));
    const totalCosts = periodCosts.reduce((s, c) => s + (c.amount || 0), 0);
    const editable = isMutable(selectedPeriod.status);
    const isFinalized = selectedPeriod.status === 'finalized';
    const revisionHistory = getRevisionHistory();

    return (
      <div className="page">
        <div className="detail-header">
          <button className="btn btn-sm btn-secondary" onClick={() => setView('list')}>
            &larr; {t('pages.statements.back') || 'Zurück'}
          </button>
          <div className="detail-title">
            <h1>{selectedPeriod.label || t('pages.statements.defaultLabel') || 'Abrechnung'}</h1>
            <span className="text-muted">
              {propMap[selectedPeriod.property_id]?.name || '—'} · {selectedPeriod.start_date} – {selectedPeriod.end_date}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <StatusBadge status={selectedPeriod.status} />

            {/* Workflow buttons based on status */}
            {selectedPeriod.status === 'draft' && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleSubmitReview}
                disabled={submittingReview}
              >
                {submittingReview ? t('pages.statements.submitting') : t('pages.statements.submitReview')}
              </button>
            )}
            {selectedPeriod.status === 'review' && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleRevertDraft}
              >
                {t('pages.statements.revertDraft')}
              </button>
            )}

            {editable && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleGenerateStatements}
                disabled={generating || preflightLoading || preflight?.has_blockers}
                title={preflight?.has_blockers ? t('pages.statements.preflightBlockers') : ''}
              >
                {generating ? t('pages.statements.generating') : t('pages.statements.generate')}
              </button>
            )}

            <button
              className="btn btn-sm btn-secondary"
              onClick={handleCreateRevision}
              disabled={creatingRevision}
            >
              {creatingRevision ? t('pages.statements.creating') : t('pages.statements.startCorrection')}
            </button>
            <button
              className="btn btn-sm btn-secondary"
              onClick={handleCreateReceivables}
              disabled={creatingReceivables || !isFinalized}
            >
              {creatingReceivables ? t('pages.statements.creatingReceivables') : t('pages.statements.createReceivables')}
            </button>
            <button
              className="btn btn-sm btn-secondary"
              onClick={handleExportPeriod}
              disabled={exporting}
            >
              {exporting ? t('pages.statements.exporting') : t('pages.statements.csvExport')}
            </button>
            {periodStmts.length > 0 && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleExportZip}
                disabled={exporting}
              >
                {exporting ? t('pages.statements.exporting') : t('pages.statements.zipExport')}
              </button>
            )}
            <button
              className="btn btn-sm btn-secondary"
              onClick={handleMarkDelivered}
              disabled={markingDelivered || !isFinalized}
            >
              {markingDelivered ? t('pages.statements.markingDelivered') : t('pages.statements.markDelivered')}
            </button>
            {(isFinalized || selectedPeriod.status === 'delivered') && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleDispute}
                disabled={disputing}
                style={{ color: 'var(--color-warning, #c57600)' }}
              >
                {disputing ? t('pages.statements.submitting') : t('pages.statements.dispute')}
              </button>
            )}
            <button
              className="btn btn-sm btn-primary"
              onClick={handleFinalizePeriod}
              disabled={!editable || finalizing || preflightLoading || preflight?.has_blockers}
            >
              {finalizing ? t('pages.statements.finalizing') : (isFinalized ? t('pages.statements.finalized') : t('pages.statements.finalize'))}
            </button>
          </div>
        </div>

        <div className="stats-grid" style={{ marginBottom: '1rem' }}>
          <div className="stat-card">
            <div className="stat-label">{t('pages.statements.totalCosts')}</div>
            <div className="stat-value">{totalCosts.toFixed(2)} €</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">{t('pages.statements.costItems')}</div>
            <div className="stat-value">{periodCosts.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">{t('pages.statements.individualStatements')}</div>
            <div className="stat-value">{periodStmts.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">{t('ui.form.status') || 'Status'}</div>
            <div className="stat-value"><StatusBadge status={selectedPeriod.status} /></div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: '1rem' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>{t('pages.statements.preflight')}</strong>
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => {
                setPreflightLoading(true);
                api.get(`/billing/periods/${selectedPeriod.id}/preflight`)
                  .then(setPreflight)
                  .catch(() => setPreflight(null))
                  .finally(() => setPreflightLoading(false));
              }}
            >
              {t('pages.statements.recheck')}
            </button>
          </div>
          <div className="card-body">
            {preflightLoading && <span className="text-muted">{t('pages.statements.checking')}</span>}
            {!preflightLoading && !preflight && <span className="text-muted">{t('pages.statements.noPreflightData')}</span>}
            {!preflightLoading && preflight && (
              <div style={{ display: 'grid', gap: '0.75rem' }}>
                <div>
                  <span className={`badge ${preflight.has_blockers ? 'badge-danger' : 'badge-success'}`}>
                    {preflight.has_blockers ? t('pages.statements.blocked') : t('pages.statements.readyToGenerate')}
                  </span>
                </div>
                {preflight.blockers?.length > 0 && (
                  <div>
                    <strong>{t('pages.statements.blockers')}</strong>
                    <ul>
                      {preflight.blockers.map((i) => (
                        <li key={`${i.code}-${i.context || ''}`}>{i.message}{i.context ? ` (${i.context})` : ''}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {preflight.warnings?.length > 0 && (
                  <div>
                    <strong>{t('pages.statements.warnings')}</strong>
                    <ul>
                      {preflight.warnings.map((i) => (
                        <li key={`${i.code}-${i.context || ''}`}>{i.message}{i.context ? ` (${i.context})` : ''}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div>
                  <strong>{t('pages.statements.metrics')}</strong>
                  <div className="text-muted" style={{ fontSize: '0.9rem' }}>
                    {t('pages.statements.metricsContracts')}: {preflight.metrics?.contracts_in_period ?? 0} · {t('pages.statements.metricsCostItems')}: {preflight.metrics?.cost_items ?? 0} ·
                    {t('pages.statements.metricsMissingKeys')}: {preflight.metrics?.allocation_keys_missing ?? 0} · {t('pages.statements.metricsMissingArea')}: {preflight.metrics?.area_missing_units ?? 0}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Revision History */}
        {revisionHistory.length > 1 && (
          <div className="card" style={{ marginBottom: '1rem' }}>
            <div className="card-header"><strong>{t('pages.statements.revisionHistory')}</strong></div>
            <div className="card-body">
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color, #ddd)' }}>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('pages.statements.colLabel')}</th>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('ui.form.status') || 'Status'}</th>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>{t('pages.statements.colCreated')}</th>
                    <th style={{ padding: '4px 8px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {revisionHistory.map(rev => (
                    <tr
                      key={rev.id}
                      style={{
                        borderBottom: '1px solid var(--border-color, #eee)',
                        background: rev.id === selectedPeriod.id ? 'var(--highlight-bg, #f0f4ff)' : undefined,
                      }}
                    >
                      <td style={{ padding: '4px 8px' }}>{rev.label}</td>
                      <td style={{ padding: '4px 8px' }}><StatusBadge status={rev.status} /></td>
                      <td style={{ padding: '4px 8px' }}>{rev.created_at ? new Date(rev.created_at).toLocaleDateString('de-DE') : '—'}</td>
                      <td style={{ padding: '4px 8px' }}>
                        {rev.id !== selectedPeriod.id && (
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={() => handleSelectPeriod(rev)}
                          >
                            {t('pages.statements.show')}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div style={{ marginBottom: '1.5rem' }}>
          {editable && (
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem', justifyContent: 'flex-end' }}>
              <label className="btn btn-sm btn-secondary" style={{ cursor: 'pointer', margin: 0 }}>
                {ocrUploading ? t('pages.statements.ocrRunning') : t('pages.statements.ocrImport')}
                <input
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
                  style={{ display: 'none' }}
                  onChange={handleOcrUpload}
                  disabled={ocrUploading}
                />
              </label>
            </div>
          )}
          <DataTable
            title={t('pages.statements.costItems')}
            columns={COST_COLUMNS}
            data={periodCosts}
            onAdd={editable ? () => setCostModal('create') : undefined}
            onEdit={editable ? (row => setCostModal(row)) : undefined}
          />
        </div>

        {/* OCR Import Preview Dialog */}
        {ocrDraft && (
          <div className="modal-overlay" onClick={() => setOcrDraft(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
              <div className="modal-header">
                <h3>OCR-Ergebnis prüfen</h3>
                <button className="btn btn-sm" onClick={() => setOcrDraft(null)}>&times;</button>
              </div>
              <div className="modal-body" style={{ display: 'grid', gap: '0.75rem' }}>
                {ocrDraft.ocr_fields && (
                  <div>
                    <strong>Erkannte Felder</strong>
                    <table style={{ width: '100%', fontSize: '0.9rem', borderCollapse: 'collapse' }}>
                      <tbody>
                        {ocrDraft.ocr_fields.supplier && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Lieferant</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.supplier}</td>
                            <td style={{ padding: '4px 8px', color: '#888' }}>{Math.round((ocrDraft.confidence?.description || 0) * 100)}%</td></tr>
                        )}
                        {ocrDraft.ocr_fields.total_amount != null && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Betrag</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.total_amount.toFixed(2)} &euro;</td>
                            <td style={{ padding: '4px 8px', color: '#888' }}>{Math.round((ocrDraft.confidence?.amount || 0) * 100)}%</td></tr>
                        )}
                        {ocrDraft.ocr_fields.cost_category && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Kostenart</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.cost_category}</td>
                            <td style={{ padding: '4px 8px', color: '#888' }}>{Math.round((ocrDraft.confidence?.cost_category || 0) * 100)}%</td></tr>
                        )}
                        {ocrDraft.ocr_fields.invoice_number && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Rechnungsnr.</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.invoice_number}</td>
                            <td></td></tr>
                        )}
                        {ocrDraft.ocr_fields.invoice_date && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Datum</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.invoice_date}</td>
                            <td></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
                {ocrDraft.ocr_text_preview && (
                  <div>
                    <strong>Textvorschau</strong>
                    <pre style={{ fontSize: '0.8rem', background: 'var(--bg-secondary, #f5f5f5)', padding: '8px', borderRadius: '4px', maxHeight: '150px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                      {ocrDraft.ocr_text_preview}
                    </pre>
                  </div>
                )}
                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => setOcrDraft(null)}>
                    Abbrechen
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={handleAcceptOcrDraft}>
                    Als Kostenposition übernehmen
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {periodStmts.length > 0 && (
          <DataTable
            title="Einzelabrechnungen pro Einheit"
            columns={STMT_COLUMNS}
            data={periodStmts}
          />
        )}

        {costModal && editable && (
          <FormModal
            title={costModal === 'create' ? 'Kostenposition hinzufügen' : 'Kostenposition bearbeiten'}
            fields={costFields}
            initial={costModal === 'create' ? { billing_period_id: selectedPeriod.id } : costModal}
            onSave={handleSaveCost}
            onClose={() => setCostModal(null)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        {selectedPeriod && (
          <button className="btn btn-sm btn-secondary" onClick={() => setModal('copy')}>
            Vorjahr kopieren
          </button>
        )}
      </div>
      <DataTable
        title="Nebenkostenabrechnungen"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={handleSelectPeriod}
      />
      {(modal === 'create' || modal === 'copy') && (
        <FormModal
          title={modal === 'copy' ? 'Abrechnung kopieren (neuer Zeitraum)' : 'Abrechnung erstellen'}
          fields={fields}
          initial={modal === 'copy' && selectedPeriod ? {
            property_id: selectedPeriod.property_id,
            label: `${selectedPeriod.label} (Kopie)`,
          } : null}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {modal && modal !== 'create' && modal !== 'copy' && modal.id && (
        <FormModal
          title="Abrechnung bearbeiten"
          fields={fields}
          initial={modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
