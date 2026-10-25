import NotificationArrival from '../components/NotificationArrival';
import { useAuth } from '../contexts/AuthContext';
import { mayWrite } from '../utils/permissions';
import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import StatementLetterDialog from '../features/billing/StatementLetterDialog';
import StatementBreakdown from '../features/billing/StatementBreakdown';
import { codeLabel } from '../utils/codeLabels';
import { formatMoney } from '../utils/format';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { FileText, FolderOpen, ListChecks, Pencil } from 'lucide-react';
import MeterDocumentImport from '../features/meterDocuments/MeterDocumentImport';
import './statements.css';

const sumMoney = (rows, key) => rows.reduce((sum, row) => sum + Math.round(Number(row[key] || 0) * 100), 0) / 100;
const COST_SUGGESTIONS = [
  ['Grundsteuer', 'property_tax'], ['Wasser und Abwasser', 'water'], ['Müllabfuhr', 'garbage'],
  ['Gebäudeversicherung', 'insurance'], ['Allgemeinstrom', 'electricity'],
  ['Gebäudereinigung', 'cleaning'], ['Gartenpflege', 'garden'], ['Heizkosten', 'heating'],
];

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
               color: '#fff', boxShadow: '0 4px 12px rgba(0,0,0,0.15)', maxWidth: 'min(400px, calc(100vw - 3rem))' }}
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
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()} style={{ maxWidth: '450px' }}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="btn-close" onClick={onCancel} aria-label="Schließen">&times;</button>
        </div>
        <div className="modal-body">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <input
              value={value}
              onChange={e => setValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') onConfirm(value); }}
              aria-label={title}
              autoFocus
            />
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel}>Abbrechen</button>
          <button className="btn btn-primary" onClick={() => onConfirm(value)}>OK</button>
        </div>
      </div>
    </div>
  );
}

function RejectionDialog({ objection, action, onConfirm, onCancel, busy }) {
  const title = action === 'revise' ? 'Abrechnung begründet überarbeiten' : 'Widerspruch begründet zurückweisen';
  const [reason, setReason] = useState('');
  const valid = reason.trim().length >= 12;
  return <div className="modal-overlay" onClick={() => { if (!busy) onCancel(); }}>
    <div className="modal objection-dialog" role="dialog" aria-modal="true" aria-label={title}
      onClick={event => event.stopPropagation()} style={{ maxWidth: '550px', minWidth: 0 }}>
      <div className="modal-header">
        <h3>{title}</h3>
        <button className="btn-close" aria-label="Schließen" onClick={onCancel} disabled={busy}>&times;</button>
      </div>
      <div className="modal-body">
        <p>Der ursprüngliche Einwand und die ausgestellte Abrechnung bleiben unverändert.
          Die Entscheidung wird getrennt und nachvollziehbar gespeichert.</p>
        <p><strong>Einwand:</strong> {objection.reason}</p>
        {action === 'revise' && <p>Eine neue Korrekturfassung wird als Entwurf geöffnet. Alle offenen Widersprüche dieser Fassung werden dieser Überarbeitung zugeordnet. Forderungen und Zahlungen ändern sich erst durch die gesonderten Arbeitsschritte.</p>}
        <label htmlFor="objection-decision-reason">Sachliche Begründung (mindestens 12 Zeichen)</label>
        <textarea id="objection-decision-reason" value={reason} maxLength={2000} rows={4}
          onChange={event => setReason(event.target.value)} disabled={busy} autoFocus
          style={{ width: '100%', maxWidth: '100%' }} />
      </div>
      <div className="modal-footer">
        <button type="button" className="btn btn-secondary" onClick={onCancel}
          disabled={busy}>Abbrechen</button>
        <button type="button" className="btn btn-primary" disabled={!valid || busy}
          onClick={() => onConfirm(reason)}>
          {busy ? 'Entscheidung wird gespeichert …' : action === 'revise' ? 'Überarbeitung mit Begründung starten' : 'Ablehnung mit Begründung bestätigen'}
        </button>
      </div>
    </div>
  </div>;
}


function ObjectionDialog({ statements, unitMap, onConfirm, onCancel, busy }) {
  const [reason, setReason] = useState('');
  const commandKey = useRef(null);
  const [statementId, setStatementId] = useState('');
  const [receivedOn, setReceivedOn] = useState(() => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  });
  return <div className="modal-overlay" onClick={() => { if (!busy) onCancel(); }}>
    <div className="modal objection-dialog" role="dialog" aria-modal="true" aria-label="Widerspruch erfassen" onClick={event => event.stopPropagation()}>
      <div className="modal-header"><h3>Widerspruch erfassen</h3>
        <button className="btn-close" aria-label="Schließen" disabled={busy} onClick={onCancel}>&times;</button></div>
      <div className="modal-body" style={{ display: 'grid', gap: '0.75rem' }}>
        <label>Betroffene Abrechnung<select value={statementId} onChange={event => setStatementId(event.target.value)} disabled={busy}>
          <option value="">Gesamter Abrechnungszeitraum</option>
          {statements.filter(row => row.party !== 'vacancy').map(row => <option key={row.id} value={row.id}>
            {unitMap[row.unit_id]?.label || row.unit_id} · {row.tenant_name || row.contract_id || row.id}
          </option>)}
        </select></label>
        <label>Eingangsdatum<input type="date" value={receivedOn} onChange={event => setReceivedOn(event.target.value)} disabled={busy} /></label>
        <label>Begründung des Widerspruchs<textarea value={reason} rows={4} maxLength={2000} autoFocus
          onChange={event => setReason(event.target.value)} disabled={busy} /></label>
        <small>Bei unklarer Antwort mit unveränderten Angaben erneut speichern. Änderungen nach einem Versuch
          benötigen einen neuen Vorgang: zuerst den gespeicherten Stand prüfen, dann abbrechen und neu öffnen.</small>
      </div>
      <div className="modal-footer"><button type="button" className="btn btn-secondary" disabled={busy} onClick={onCancel}>Abbrechen</button>
        <button type="button" className="btn btn-primary" disabled={busy || !reason.trim() || !receivedOn}
          onClick={() => {
            commandKey.current ||= crypto.randomUUID();
            onConfirm({ reason: reason.trim(), statement_id: statementId || null, received_on: receivedOn,
              idempotency_key: commandKey.current });
          }}>
          {busy ? 'Widerspruch wird gespeichert …' : 'Widerspruch speichern'}
        </button></div>
    </div>
  </div>;
}


function getColumns(t) {
  return [
    { key: 'property_name', label: t('pages.statements.colProperty') || 'Immobilie', filterType: 'text', link: 'property' },
    { key: 'period_label', label: t('pages.statements.colPeriod') || 'Abrechnungszeitraum', filterType: 'text' },
    { key: 'total_costs', label: t('pages.statements.colTotalCosts') || 'Gesamtkosten (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'cost_item_count', label: 'Kostenpositionen', type: 'number' },
    { key: 'units_count', label: t('pages.statements.colUnits') || 'Einzelabrechnungen', type: 'number' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];
}

function getCostColumns(t) {
  return [
    { key: 'description', label: t('pages.statements.colCostType') || 'Kostenart', filterType: 'text' },
    { key: 'amount', label: t('pages.statements.colAmount') || 'Betrag (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'allocation_key_name', label: t('pages.statements.colAllocationKey') || 'Verteilerschlüssel' },
    { key: 'is_recoverable', label: t('pages.statements.colRecoverable') || 'Umlagefähig',
      render: v => (v === false
        ? <span className="text-muted">{t('pages.statements.notRecoverable') || 'nein (trägt der Eigentümer)'}</span>
        : (t('pages.statements.recoverable') || 'ja')) },
  ];
}

/** dd.mm.yyyy from an ISO date string. */
function formatDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
}

function getStmtColumns(t, onError, onLetter) {
  return [
    { key: 'unit_label', label: t('pages.statements.colUnit') || 'Einheit', link: 'unit' },
    { key: 'tenant_name', label: t('pages.statements.colParty') || 'Mieter',
      render: (v, row) => (row.party === 'vacancy'
        ? <span className="text-muted">{t('pages.statements.vacancyParty') || 'Leerstand (Eigentümer)'}</span>
        : row.tenant_id && v !== '—' ? <PartyLink tenantId={row.tenant_id}>{v}</PartyLink> : v) },
    { key: 'usage_start', label: t('pages.statements.colUsage') || 'Nutzungszeitraum',
      render: (_, row) => (row.usage_start
        ? `${formatDate(row.usage_start)} – ${formatDate(row.usage_end)}`
        : '—') },
    { key: 'usage_days', label: t('pages.statements.colDays') || 'Tage', type: 'number', align: 'right',
      render: v => (v != null ? v : '—') },
    { key: 'total_cost', label: t('pages.statements.colShare') || 'Anteil (€)', type: 'number', align: 'right',
      render: v => formatMoney(v || 0) },
    { key: 'advance_paid', label: t('pages.statements.colAdvancePaid') || 'Vorauszahlung (€)', type: 'number', align: 'right',
      render: v => formatMoney(v || 0) },
    { key: 'balance', label: t('pages.statements.colBalance') || 'Saldo (€)', type: 'number', align: 'right',
      render: (v, row) => {
        // A vacancy row is the landlord's cost, not a balance anybody owes.
        if (row.party === 'vacancy') return <span className="text-muted">—</span>;
        const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
        return <span className={cls}>{formatMoney(v || 0)}</span>;
      }},
    { key: 'delivery_status', label: t('pages.statements.colDelivery') || 'Zustellung',
      render: v => v ? <StatusBadge status={v} /> : <span className="text-muted">—</span> },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status' },
    { key: 'pdf_action', label: '',
      render: (_, row) => row.party !== 'vacancy' && (
        <div className="billing-document-actions">
          <Link className="btn btn-sm btn-secondary" to={`/receivables?${new URLSearchParams({ statement_id: row.id })}`}
            onClick={event => event.stopPropagation()}>Forderungen & Guthaben</Link>
          <button type="button" className="btn btn-sm btn-primary" onClick={event => { event.stopPropagation(); onLetter(row); }}>Anschreiben & PDF</button>
        <button
          className="btn btn-sm btn-secondary"
          title={t('pages.statements.pdfDownload') || 'PDF herunterladen'}
          onClick={(e) => { e.stopPropagation(); downloadStatementPdf(row.id, onError); }}
        >
          PDF
        </button>
        </div>
      )},
  ];
}

/** Trigger browser download of a single statement PDF. */
async function downloadStatementPdf(statementId, onError) {
  try {
    const current = api.captureSession();
    const blob = await api.getBlob(`/billing/statements/${statementId}/pdf`);
    current();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `abrechnung_${statementId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) { onError?.(err.message) || console.error(err.message); }
}

/** Helper: is a period in a mutable (editable) state? */
function isMutable(status) {
  return status === 'draft' || status === 'review';
}

/** Statuses of an issued version: it is only answered by a correction (a new version). */
const CORRECTABLE = ['finalized', 'delivered', 'disputed'];

/** Determine the current workflow step (1-6) based on period state. */
function getWorkflowStep(period, costCount, stmtCount) {
  if (['delivered', 'disputed', 'corrected'].includes(period.status)) return 6;
  if (period.status === 'finalized') return 5;
  if (period.status === 'review') return 4;
  // draft status
  if (stmtCount > 0) return 3;
  if (costCount > 0) return 2;
  return 2;
}

const WORKFLOW_STEPS = [
  { num: 1, key: 'create' },
  { num: 2, key: 'costs' },
  { num: 3, key: 'preflight' },
  { num: 4, key: 'generate' },
  { num: 5, key: 'finalize' },
  { num: 6, key: 'deliver' },
];

function StepIndicator({ currentStep, t: tr }) {
  const labels = {
    create: tr('pages.statements.stepCreate') || 'Erstellen',
    costs: tr('pages.statements.stepCosts') || 'Kosten',
    preflight: tr('pages.statements.stepPreflight') || 'Prüfung',
    generate: tr('pages.statements.stepGenerate') || 'Generieren',
    finalize: tr('pages.statements.stepFinalize') || 'Finalisieren',
    deliver: tr('pages.statements.stepDeliver') || 'Zustellen',
  };
  return (
    <div className="step-indicator">
      {WORKFLOW_STEPS.map((step, i) => {
        let cls = 'step-indicator-item';
        if (step.num < currentStep) cls += ' step-completed';
        else if (step.num === currentStep) cls += ' step-active';
        return (
          <span key={step.num}>
            {i > 0 && <span className="step-indicator-sep"> → </span>}
            <span className={cls}>{step.num}. {labels[step.key]}</span>
          </span>
        );
      })}
    </div>
  );
}

export default function Statements() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const sourceFilter = ['preflight_blockers', 'statements'].includes(params.get('filter')) ? params.get('filter') : 'all';
  const [sourceRows, setSourceRows] = useState({ items: [], loading: false, error: null });
  const [sourceAttempt, setSourceAttempt] = useState(0);
  const [drilldown, setDrilldown] = useState(0);
  const costSources = useRef(null);
  const statementSourceTable = useRef(null);
  const [costSourceFilter, setCostSourceFilter] = useState('all');
  const [statementSourceFilter, setStatementSourceFilter] = useState('all');
  const [sourceDrilldown, setSourceDrilldown] = useState(0);
  const requestedFocus = useRef(null);
  const openCostSources = filter => { requestedFocus.current = 'costs'; setCostSourceFilter(filter); setSourceDrilldown(value => value + 1); };
  const openStatementSources = filter => { requestedFocus.current = 'statements'; setStatementSourceFilter(filter); setSourceDrilldown(value => value + 1); };
  const { t } = useTranslation();
  const auth = useAuth();
  const confirm = useConfirm();
  const canManagePeriods = !auth?.user || mayWrite(auth.write, '/billing/periods');
  const canEditCosts = !auth?.user || mayWrite(auth.write, '/billing/cost-items');
  const canRejectObjections = ['eigentuemer', 'verwalter'].includes(auth?.user?.role)
    && mayWrite(auth?.write, '/billing/objections');
  const canRecordObjections = !auth?.user || canRejectObjections;
  const toast = useToast();
  const [periods, setPeriods] = useState([]);
  const [costItems, setCostItems] = useState([]);
  const [statements, setStatements] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [allocationKeys, setAllocationKeys] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [modal, setModal] = useState(null);
  const [selectedPeriod, setSelectedPeriod] = useState(null);
  const listReturnSearch = useRef('');
  const [letterStatement, setLetterStatement] = useState(null);
  const [breakdown, setBreakdown] = useState(null);
  const [costPrefill, setCostPrefill] = useState(null);
  const [copyResult, setCopyResult] = useState(null);
  const [preflightError, setPreflightError] = useState(null);
  const dataRequest = useRef(0);
  const dataController = useRef(null);
  const preflightRequest = useRef(0);
  const currentPeriod = useRef(null);
  currentPeriod.current = selectedPeriod?.id;
  useEffect(() => { currentPeriod.current = selectedPeriod?.id; return () => { currentPeriod.current = null; }; }, [selectedPeriod?.id]);
  const [costModal, setCostModal] = useState(null);
  const [view, setView] = useState('list');
  useEffect(() => {
    if (view !== 'detail' || breakdown || !requestedFocus.current) return;
    const target = requestedFocus.current === 'costs' ? costSources.current : statementSourceTable.current;
    if (target) { requestedFocus.current = null; target.focus(); target.scrollIntoView?.({ block: 'center' }); }
  }, [sourceDrilldown, view, breakdown]);
  const [preflight, setPreflight] = useState(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [submittingReview, setSubmittingReview] = useState(false);
  const [creatingRevision, setCreatingRevision] = useState(false);
  const [creatingReceivables, setCreatingReceivables] = useState(false);
  const [markingDelivered, setMarkingDelivered] = useState(false);
  const [deliveryModal, setDeliveryModal] = useState(false);
  const [ocrDraft, setOcrDraft] = useState(null);
  const [ocrUploading, setOcrUploading] = useState(false);
  const [disputing, setDisputing] = useState(false);
  const [promptModal, setPromptModal] = useState(null);
  const [objections, setObjections] = useState([]);
  const [rejectingObjection, setRejectingObjection] = useState(null);
  const [rejectingBusy, setRejectingBusy] = useState(false);
  const rejectionCommands = useRef(new Map());
  const [creatingObjection, setCreatingObjection] = useState(false);
  const [objectionsError, setObjectionsError] = useState(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const objectionsRequest = useRef(0);
  const decisionRequest = useRef(0);

  useEffect(() => {
    rejectionCommands.current.clear();
    setRejectingObjection(null);
    setCreatingObjection(false);
    decisionRequest.current += 1;
    setDecisionLoading(false);
  }, [selectedPeriod?.id, auth?.user?.id, auth?.user?.role, canRejectObjections]);

  const loadObjections = async (periodId) => {
    const request = ++objectionsRequest.current;
    const session = api.captureSession();
    setObjectionsError(null);
    try {
      const list = await api.get(`/billing/objections?billing_period_id=${encodeURIComponent(periodId)}`);
      session();
      if (currentPeriod.current === periodId && request === objectionsRequest.current) {
        setObjections(Array.isArray(list) ? list : []);
      }
    } catch (error) {
      if (currentPeriod.current === periodId && request === objectionsRequest.current) {
        setObjectionsError(error.message || 'Widersprüche konnten nicht geladen werden');
      }
    }
  };

  const loadData = async () => {
    const request = ++dataRequest.current;
    const selectedAtStart = selectedPeriod;
    dataController.current?.abort();
    const controller = new AbortController(); dataController.current = controller;
    const session = api.captureSession();
    setLoadError(null);
    setSourceAttempt(value => value + 1);
    try {
      const rows = await Promise.all(['/billing/periods', '/billing/cost-items', '/billing/statements',
        '/properties', '/units', '/billing/allocation-keys', '/contracts', '/tenants']
        .map(path => api.list(path, { signal: controller.signal })));
      session();
      if (request !== dataRequest.current || controller.signal.aborted) return false;
      if (rows.some(value => !Array.isArray(value))) throw new Error('Die Abrechnungsdaten sind unvollständig. Bitte erneut laden.');
      const [bp, ci, us, props, u, ak, ctr, tn] = rows;
      setPeriods(bp); setCostItems(ci); setStatements(us); setProperties(props);
      setUnits(u); setAllocationKeys(ak); setContracts(ctr); setTenants(tn);
      // A later explicit detail read/decision wins over a list request that
      // started before it. Never replace a newly opened correction with old data.
      setSelectedPeriod(current => current && current === selectedAtStart ? bp.find(row => row.id === current.id) || current : current);
      return true;
    } catch (err) {
      if (request !== dataRequest.current || controller.signal.aborted) return false;
      setLoadError(err.message || 'Daten konnten nicht geladen werden');
      toast.show(err.message || 'Daten konnten nicht geladen werden');
      return false;
    } finally { if (request === dataRequest.current && !controller.signal.aborted) setLoading(false); }
  };

  useEffect(() => { loadData(); return () => { dataRequest.current += 1; dataController.current?.abort(); preflightRequest.current += 1; }; }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load, guarded against stale responses
  useEffect(() => {
    setView('list'); setSelectedPeriod(null); setDrilldown(value => value + 1);
  }, [sourceFilter]);
  useEffect(() => {
    if (sourceFilter !== 'preflight_blockers') return;
    const request = new AbortController(); setSourceRows(current => ({ ...current, loading: true, error: null }));
    api.list('/billing/periods?workflow_filter=preflight_blockers', { signal: request.signal }).then(rows => {
      if (!Array.isArray(rows)) throw new Error('Die Abrechnungsquelle konnte nicht gelesen werden.');
      if (!request.signal.aborted) setSourceRows({ items: rows, loading: false, error: null });
    }).catch(failure => { if (!request.signal.aborted) setSourceRows(current => ({ ...current, loading: false, error: failure.message })); });
    return () => request.abort();
  }, [sourceFilter, sourceAttempt]);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const akMap = Object.fromEntries(allocationKeys.map(k => [k.id, k]));
  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));
  const enrichStatement = statement => {
    const contract = contractMap[statement.contract_id];
    return { ...statement, unit_label: unitMap[statement.unit_id]?.label || '—',
      tenant_id: contract?.tenant_id || null, tenant_name: contract ? (tenantMap[contract.tenant_id] || '—') : '—' };
  };

  const matchesPeriod = bp => (!params.get('period_id') || bp.id === params.get('period_id'))
    && (!params.get('property_id') || bp.property_id === params.get('property_id'))
    && (!params.get('year') || (bp.start_date <= `${params.get('year')}-12-31` && bp.end_date >= `${params.get('year')}-01-01`))
    && (!params.get('status') || bp.status === params.get('status'));

  const enriched = (sourceFilter === 'preflight_blockers' ? sourceRows.items : periods).filter(matchesPeriod).map(bp => {
    const costs = costItems.filter(ci => ci.billing_period_id === bp.id);
    const totalCosts = sumMoney(costs, 'amount');
    const stmts = statements.filter(s => s.billing_period_id === bp.id);
    return {
      ...bp,
      property_name: propMap[bp.property_id]?.name || '—',
      period_label: `${formatDate(bp.start_date)} – ${formatDate(bp.end_date)}`,
      total_costs: totalCosts,
      cost_item_count: costs.length,
      units_count: stmts.length,
    };
  });

  const fields = [
    { key: 'property_id', label: t('pages.statements.formProperty') || 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: t('pages.statements.formLabel') || 'Bezeichnung', required: true, placeholder: 'z.B. NK-Abrechnung 2025' },
    { key: 'start_date', label: t('pages.statements.formStart') || 'Beginn', type: 'date', required: true },
    { key: 'end_date', label: t('pages.statements.formEnd') || 'Ende', type: 'date', required: true,
      validate: (value, values) => value && values.start_date && value < values.start_date ? 'Das Ende darf nicht vor dem Beginn liegen.' : null },
    // No status field: the status changes only through the workflow (review, finalize, objection, correction).
  ];

  const costFields = [
    { key: 'description', label: t('pages.statements.formCostType') || 'Kostenart', required: true, placeholder: 'z.B. Wasser, Heizung, Müll' },
    { key: 'amount', label: t('pages.statements.formAmount') || 'Betrag (€)', type: 'number', required: true },
    { key: 'allocation_key_id', label: t('pages.statements.formAllocationKey') || 'Verteilerschlüssel', type: 'select', required: true, autoSelect: false,
      options: allocationKeys.filter(k => !k.property_id || k.property_id === selectedPeriod?.property_id)
        .map(k => ({ value: k.id, label: `${k.name} (${codeLabel(k.key_type)})` })) },
    { key: 'is_recoverable', label: t('pages.statements.formRecoverable') || 'Umlagefähig', type: 'select', required: true,
      default: 'true', options: [
        { value: 'true', label: t('pages.statements.recoverableYes') || 'Ja – wird auf die Mieter verteilt' },
        { value: 'false', label: t('pages.statements.recoverableNo') || 'Nein – trägt der Eigentümer' },
      ]},
    // HeizkostenV § 7: 50–70 % by consumption (the key above), the rest as fixed costs by area
    { key: 'consumption_share', label: 'Verbrauchsanteil Heizkosten (%)', type: 'number', step: '1',
      validate: value => value !== '' && value != null && (Number(value) < 50 || Number(value) > 70)
        ? 'Nach der Heizkostenverordnung 50 bis 70 %.' : null,
      hint: 'Nur für Heiz- und Warmwasserkosten mit einem Verbrauchsschlüssel: dieser Anteil nach Verbrauch, der Rest als Grundkosten.' },
    { key: 'fixed_key_id', label: 'Schlüssel der Grundkosten', type: 'select',
      options: [{ value: '', label: 'Fläche des Objekts (Standard)' },
        ...allocationKeys.filter(k => k.property_id === selectedPeriod?.property_id && k.key_type !== 'consumption')
          .map(k => ({ value: k.id, label: `${k.name} (${codeLabel(k.key_type)})` }))] },
  ];

  const handleSave = async (data) => {
    if (!canManagePeriods) throw new Error('Für Änderungen an Abrechnungszeiträumen fehlt die Berechtigung.');
    const periodData = modal === 'create' ? data : { ...data,
      property_id: modal === 'copy' ? selectedPeriod.property_id : modal.property_id };
    if (modal === 'create') {
      await api.post('/billing/periods', periodData);
    } else if (modal === 'copy') {
      if (!canEditCosts) throw new Error('Zum Kopieren der Kostenpositionen fehlt die Berechtigung.');
      const newPeriod = await api.post('/billing/periods', periodData);
      if (newPeriod && selectedPeriod) {
        const prevCosts = costItems.filter(ci => ci.billing_period_id === selectedPeriod.id);
        const failures = [];
        for (const cost of prevCosts) {
          try {
            await api.post('/billing/cost-items', {
              billing_period_id: newPeriod.id,
              description: cost.description,
              amount: 0,
              allocation_key_id: cost.allocation_key_id,
              is_recoverable: cost.is_recoverable !== false,
              cost_category: cost.cost_category,
            });
          } catch (error) { failures.push({ description: cost.description, message: error.message || 'Kopieren fehlgeschlagen' }); }
        }
        // The period already exists. Report partial results without throwing:
        // retrying the whole form would create another period and duplicate costs.
        setCopyResult({ period: newPeriod, total: prevCosts.length, copied: prevCosts.length - failures.length, failures });
      }
    } else {
      const saved = await api.put(`/billing/periods/${modal.id}`, periodData);
      setSelectedPeriod(current => current?.id === saved.id ? saved : current);
    }
    await loadData();
  };

  const handleSaveCost = async (form) => {
    if (!selectedPeriod || !isMutable(selectedPeriod.status) || !canEditCosts) throw new Error('Diese Abrechnung kann nicht bearbeitet werden.');
    const data = { ...(costModal !== 'create' ? costModal : costPrefill), ...form,
      billing_period_id: selectedPeriod.id, is_recoverable: form.is_recoverable !== 'false' && form.is_recoverable !== false };
    if (costModal === 'create') {
      await api.post('/billing/cost-items', data);
    } else {
      await api.put(`/billing/cost-items/${costModal.id}`, data);
    }
    await loadData();
    await refreshPreflight(selectedPeriod.id);
  };

  const handleDeleteCost = async row => {
    if (!selectedPeriod || !isMutable(selectedPeriod.status) || !canEditCosts || !confirm) return;
    if (!await confirm(`Kostenposition „${row.description}“ (${formatMoney(row.amount)}) löschen?`, { action: 'delete' })) return;
    try {
      await api.del(`/billing/cost-items/${encodeURIComponent(row.id)}`);
      await loadData();
      await refreshPreflight(selectedPeriod.id);
    } catch (error) { toast.show(error.message || 'Kostenposition konnte nicht gelöscht werden.'); }
  };

  const refreshPreflight = async periodId => {
    if (currentPeriod.current !== periodId) return;
    const request = ++preflightRequest.current;
    const current = api.captureSession();
    setPreflightLoading(true); setPreflightError(null); setPreflight(null);
    try {
      const result = await api.get(`/billing/periods/${encodeURIComponent(periodId)}/preflight`);
      current();
      if (request === preflightRequest.current && currentPeriod.current === periodId) {
        if (!result || typeof result.has_blockers !== 'boolean') throw new Error('Die Abrechnungsprüfung ist unvollständig.');
        setPreflight(result);
      }
    } catch (error) {
      if (request === preflightRequest.current && currentPeriod.current === periodId) setPreflightError(error.message || 'Abrechnung konnte nicht geprüft werden.');
    } finally { if (request === preflightRequest.current && currentPeriod.current === periodId) setPreflightLoading(false); }
  };

  const handleGenerateStatements = async () => {
    if (!selectedPeriod) return;
    setGenerating(true);
    try {
      await api.post(`/billing/periods/${selectedPeriod.id}/generate`, {});
      await loadData();
      await refreshPreflight(selectedPeriod.id);
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
      setSelectedPeriod(current => current?.id === updated.id ? updated : current);
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
      setSelectedPeriod(current => current?.id === updated.id ? updated : current);
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
      setSelectedPeriod(current => current?.id === updated.id ? updated : current);
      await loadData();
      await refreshPreflight(selectedPeriod.id);
    } catch (err) {
      toast.show(err.message || 'Finalisierung fehlgeschlagen');
    } finally {
      setFinalizing(false);
    }
  };

  const handleMarkDelivered = async ({ channel }) => {
    if (!selectedPeriod) return;
    setMarkingDelivered(true);
    try {
      const periodStatements = statements.filter(s => s.billing_period_id === selectedPeriod.id && s.party !== 'vacancy');
      for (const stmt of periodStatements) {
        if (stmt.status !== 'delivered') {
          await api.post(`/billing/statements/${stmt.id}/mark-delivered?channel=${encodeURIComponent(channel)}`, {});
        }
      }
      await loadData();
      const refreshedPeriod = await api.get(`/billing/periods/${selectedPeriod.id}`).catch(() => selectedPeriod);
      setSelectedPeriod(current => current?.id === selectedPeriod.id ? refreshedPeriod || selectedPeriod : current);
      if (currentPeriod.current === selectedPeriod.id) setDeliveryModal(false);
    } catch (err) {
      toast.show(err.message || 'Zustellstatus konnte nicht gesetzt werden');
      throw err;
    } finally {
      setMarkingDelivered(false);
    }
  };

  const handleCreateReceivables = async () => {
    if (!selectedPeriod) return;
    setCreatingReceivables(true);
    try {
      const url = `/billing/periods/${selectedPeriod.id}/create-receivables`;
      let res = await api.post(url, {});
      let created = res?.created_receivables ?? 0;
      // a back payment is due from the delivery of its statement (R12-19): without a delivery note it waits
      if (res?.awaiting_delivery?.length && await confirm(
        `${res.awaiting_delivery.length} Nachzahlung(en) ohne Zustellvermerk: Die Abrechnung hat den Mieter vielleicht noch nicht erreicht. `
        + 'Besser erst die Zustellung vermerken – dann ist die Nachzahlung 30 Tage danach fällig. Trotzdem jetzt anlegen (Zugang heute angenommen)?',
        { title: 'Nachzahlungen ohne Zustellung', confirmLabel: 'Trotzdem anlegen' })) {
        const confirmed = await api.post(`${url}?undelivered_confirmed=true`, {});
        created += confirmed?.created_receivables ?? 0;
        res = { ...confirmed, awaiting_delivery: [] };
      }
      const skipped = res?.skipped_existing ? ` (${res.skipped_existing} bereits vorhanden)` : '';
      const late = res?.excluded_late?.length
        ? ` · ${res.excluded_late.length} Nachzahlung(en) nicht angelegt: Zugang nach Ablauf der Abrechnungsfrist am ${formatDate(res.deadline)} (§ 556 Abs. 3 BGB)`
        : '';
      const waiting = res?.awaiting_delivery?.length
        ? ` · ${res.awaiting_delivery.length} Nachzahlung(en) warten auf den Zustellvermerk` : '';
      toast.show(`Forderungen erzeugt: ${created}${skipped}${late}${waiting}`, late || waiting ? 'warning' : 'success');
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
            const allPeriods = await api.list('/billing/periods').catch(() => []);
            const newPeriod = (allPeriods || []).find(p => p.id === res.new_period_id);
            if (newPeriod && currentPeriod.current === selectedPeriod.id) handleSelectPeriod(newPeriod);
          }
        } catch (err) {
          toast.show(err.message || t('pages.statements.revisionError') || 'Korrektur konnte nicht erstellt werden');
        } finally {
          setCreatingRevision(false);
        }
      },
    });
  };

  const handleDispute = () => { if (selectedPeriod && canRecordObjections) setCreatingObjection(true); };

  const handleSaveObjection = async payload => {
    if (!selectedPeriod || !canRecordObjections || disputing) return;
    const periodId = selectedPeriod.id;
    const session = api.captureSession();
    setDisputing(true);
    try {
      const saved = await api.post(`/billing/periods/${encodeURIComponent(periodId)}/objections`, payload);
      session();
      if (currentPeriod.current !== periodId) return;
      if (!saved?.id || saved.billing_period_id !== periodId) throw new Error('Erfassungsbeleg ist unvollständig. Bitte denselben Vorgang erneut versuchen.');
      const current = await api.get(`/billing/periods/${encodeURIComponent(periodId)}`);
      session();
      if (currentPeriod.current !== periodId) return;
      if (current?.id !== periodId) throw new Error('Abrechnungsstand ist unvollständig. Bitte denselben Vorgang erneut versuchen.');
      setCreatingObjection(false);
      // A lost creation answer may be replayed after a later decision. Read
      // today's state rather than changing that issued period back to disputed.
      setSelectedPeriod(current);
      await loadObjections(periodId);
      loadData();
      toast.show('Widerspruch gespeichert.', 'success');
    } catch (error) {
      if (currentPeriod.current === periodId) toast.show(error.message || 'Widerspruch konnte nicht erfasst werden');
    } finally { setDisputing(false); }
  };

  const handleOpenDecision = async (objection, action) => {
    if (!selectedPeriod || !canRejectObjections) return;
    const periodId = selectedPeriod.id;
    const request = ++decisionRequest.current;
    const session = api.captureSession();
    setDecisionLoading(true);
    try {
      const preview = await api.get(`/billing/objections/${encodeURIComponent(objection.id)}/decision-preview`);
      session();
      if (currentPeriod.current !== periodId || request !== decisionRequest.current) return;
      if (preview?.objection?.id !== objection.id || preview.objection.billing_period_id !== periodId
          || preview.objection.status !== 'open' || preview.period_status !== 'disputed' || !preview.source_sha256) {
        throw new Error('Widerspruch wurde geändert. Bitte die Liste erneut laden.');
      }
      setRejectingObjection({ ...preview.objection, action, source_sha256: preview.source_sha256 });
    } catch (error) {
      if (currentPeriod.current === periodId && request === decisionRequest.current) {
        toast.show(error.message || 'Entscheidungsvorschau konnte nicht geladen werden');
        loadObjections(periodId);
      }
    } finally { if (request === decisionRequest.current) setDecisionLoading(false); }
  };

  const handleRejectObjection = async rationale => {
    const objection = rejectingObjection;
    if (!objection || !selectedPeriod || !canRejectObjections || rejectingBusy) return;
    const text = rationale.trim();
    if (text.length < 12) {
      toast.show('Für eine Zurückweisung ist eine sachliche Begründung erforderlich.');
      return;
    }
    const periodId = selectedPeriod.id;
    const revision = objection.decision_revision || 0;
    const previous = rejectionCommands.current.get(objection.id);
    const action = objection.action;
    const command = previous?.text === text && previous?.revision === revision && previous?.action === action && previous?.source === objection.source_sha256
      ? previous
      : { text, revision, action, source: objection.source_sha256, key: crypto.randomUUID() };
    rejectionCommands.current.set(objection.id, command);
    const currentSession = api.captureSession();
    setRejectingBusy(true);
    try {
      const result = await api.post(`/billing/objections/${encodeURIComponent(objection.id)}/${action}`, {
        expected_revision: command.revision,
        expected_source_sha256: command.source,
        idempotency_key: command.key,
        rationale: command.text,
      });
      currentSession();
      if (currentPeriod.current !== periodId) return;
      if (result?.id !== objection.id || result?.status !== (action === 'revise' ? 'correction' : 'rejected')) {
        throw new Error('Entscheidungsbeleg ist unvollständig. Bitte Originalzustand erneut prüfen.');
      }
      rejectionCommands.current.delete(objection.id);
      setObjections(previousRows => previousRows.map(item => item.id === result.id ? result : item));
      setRejectingObjection(null);
      loadObjections(periodId);
      const period = await api.get(`/billing/periods/${encodeURIComponent(periodId)}`);
      currentSession();
      if (currentPeriod.current === periodId && period?.id === periodId) {
        setSelectedPeriod(period);
        loadData();
      }
      if (action === 'revise' && result.correction_period_id) {
        const correction = await api.get(`/billing/periods/${encodeURIComponent(result.correction_period_id)}`);
        currentSession();
        if (currentPeriod.current === periodId && correction?.id === result.correction_period_id) handleSelectPeriod(correction);
      }
      toast.show('Begründete Entscheidung gespeichert. Das Original bleibt unverändert.', 'success');
    } catch (error) {
      if (currentPeriod.current === periodId) {
        toast.show(error.message || 'Entscheidung nicht bestätigt. Mit demselben Befehl erneut versuchen.');
        if ([401, 403, 404, 409].includes(error.statusCode)) {
          setRejectingObjection(null);
          rejectionCommands.current.delete(objection.id);
          loadObjections(periodId);
        }
      }
      // Keep both the editor and exactly the same idempotency key after a
      // lost success response. Never trigger an automatic second write.
    } finally {
      setRejectingBusy(false);
    }
  };

  const handleOcrUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !selectedPeriod) return;
    setOcrUploading(true);
    setOcrDraft(null);
    try {
      const current = api.captureSession();
      // Step 1: Upload file
      const formData = new FormData();
      formData.append('file', file);
      const uploadData = await api.upload('/files/upload?folder=billing-ocr', formData);
      current();
      if (currentPeriod.current !== selectedPeriod.id) return;
      if (!uploadData?.file_url) throw new Error('Datei-Upload fehlgeschlagen');

      // Step 2: Call OCR import endpoint
      const ocrRes = await api.post(
        `/billing/cost-items/import-ocr?billing_period_id=${selectedPeriod.id}&file_url=${encodeURIComponent(uploadData.file_url)}`,
        {}
      );
      current();
      if (currentPeriod.current !== selectedPeriod.id) return;

      if (ocrRes?.success) {
        setOcrDraft(ocrRes);
      } else {
        toast.show(ocrRes?.error || 'Texterkennung fehlgeschlagen');
      }
    } catch (err) {
      toast.show(err.message || 'Import fehlgeschlagen');
    } finally {
      setOcrUploading(false);
      // Reset file input
      e.target.value = '';
    }
  };

  const handleAcceptOcrDraft = () => {
    if (!ocrDraft?.draft || !selectedPeriod || !isMutable(selectedPeriod.status) || !canEditCosts) return;
    const draft = ocrDraft.draft;
    const key = allocationKeys.find(item => item.id === draft.allocation_key_id
      && (!item.property_id || item.property_id === selectedPeriod.property_id));
    setCostPrefill({ ...draft, description: draft.description || 'Importierte Kostenposition', allocation_key_id: key?.id || '' });
    setOcrDraft(null);
    setCostModal('create');
  };

  const handleExportPeriod = async () => {
    if (!selectedPeriod) return;
    setExporting(true);
    try {
      const current = api.captureSession();
      const blob = await api.getBlob(`/billing/periods/${selectedPeriod.id}/export?format=csv`);
      current();
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
      const current = api.captureSession();
      const blob = await api.getBlob(`/billing/periods/${selectedPeriod.id}/export-zip`);
      current();
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

  const listSearch = query => {
    const next = new URLSearchParams(query);
    next.delete('period_id');
    if (next.get('filter') !== 'statements') next.delete('focus_id');
    next.delete('statement_id');
    ['notice_id', 'source_id'].forEach(key => next.delete(key));
    return next.toString();
  };
  const handleSelectPeriod = (period, { fromUrl = false } = {}) => {
    if (fromUrl || view !== 'detail') listReturnSearch.current = listSearch(params);
    if (!fromUrl) setParams(current => {
      const next = new URLSearchParams(current);
      // period_id owns the detail selection; the surrounding list filters and
      // search remain intact. A source receipt never follows a manual switch.
      ['focus_id', 'notice_id', 'source_id', 'statement_id'].forEach(key => next.delete(key));
      next.set('period_id', period.id);
      return next;
    });
    setCostSourceFilter('all'); setStatementSourceFilter('all');
    setCostModal(null); setCostPrefill(null); setOcrDraft(null); setBreakdown(null); setLetterStatement(null);
    currentPeriod.current = period.id;
    setSelectedPeriod(period);
    setView('detail');
    setObjections([]);
    loadObjections(period.id);
    refreshPreflight(period.id);
  };

  const handleBackToList = () => {
    setView('list'); setBreakdown(null); setLetterStatement(null);
    setParams(new URLSearchParams(listReturnSearch.current));
  };
  const requestedStatement = params.get('statement_id');
  const statementTarget = statements.find(row => row.id === requestedStatement);
  const noticePeriod = statementTarget?.billing_period_id || params.get('period_id') || (!params.get('filter') ? params.get('focus_id') : null);
  const previousNoticePeriod = useRef(noticePeriod);
  useEffect(() => {
    if (previousNoticePeriod.current && !noticePeriod) { setView('list'); setBreakdown(null); setLetterStatement(null); }
    previousNoticePeriod.current = noticePeriod;
  }, [noticePeriod]);
  useEffect(() => {
    if (noticePeriod && !loading && !loadError && (selectedPeriod?.id !== noticePeriod || view !== 'detail')) {
      const period = periods.find(row => row.id === noticePeriod); if (period) handleSelectPeriod(period, { fromUrl: true });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noticePeriod, loading, loadError, periods]);
  useEffect(() => {
    if (!requestedStatement || loading || loadError || !statementTarget || selectedPeriod?.id !== statementTarget.billing_period_id) return;
    setBreakdown(enrichStatement(statementTarget));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- open an explicit source after its period is ready
  }, [requestedStatement, loading, loadError, statementTarget, selectedPeriod?.id]);

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
  const openSourceRow = row => {
    if (sourceFilter !== 'statements') { handleSelectPeriod(row); return; }
    setBreakdown(row);
  };
  const COST_COLUMNS = getCostColumns(t);
  const STMT_COLUMNS = getStmtColumns(t, msg => toast.show(msg), setLetterStatement);
  const statementSources = statements.filter(row => { const bp = periods.find(item => item.id === row.billing_period_id); return bp && matchesPeriod(bp); }).map(row => ({ ...row, unit_label: unitMap[row.unit_id]?.label || '—',
    tenant_id: contractMap[row.contract_id]?.tenant_id || null,
    tenant_name: tenantMap[contractMap[row.contract_id]?.tenant_id] || '—' }));

  const documentDialogs = <>
    {letterStatement && <StatementLetterDialog key={`${auth?.user?.id || ''}:${letterStatement.id}`} statementId={letterStatement.id}
      onClose={() => setLetterStatement(null)} />}
    {breakdown && <StatementBreakdown statement={breakdown} period={periods.find(row => row.id === breakdown.billing_period_id)}
      onClose={() => setBreakdown(null)} onLetter={row => { setBreakdown(null); setLetterStatement(row); }}
      onCosts={isMutable(periods.find(row => row.id === breakdown.billing_period_id)?.status) && canEditCosts ? () => {
        const bp = periods.find(row => row.id === breakdown.billing_period_id); if (bp) handleSelectPeriod(bp);
        setBreakdown(null); openCostSources('all');
      } : null} />}
  </>;
  const periodDialog = modal && canManagePeriods && <FormModal
    draftContext="billing/periods"
    title={modal === 'copy' ? 'Abrechnung kopieren (neuer Zeitraum)' : modal === 'create' ? 'Abrechnung erstellen' : 'Abrechnung bearbeiten'}
    fields={modal === 'create' ? fields : fields.map(field => field.key === 'property_id' ? { ...field, type: 'hidden' } : field)}
    initial={modal === 'copy' && selectedPeriod ? { property_id: selectedPeriod.property_id, label: `${selectedPeriod.label} (Kopie)` }
      : modal === 'create' ? null : modal}
    onSave={handleSave} onClose={() => setModal(null)} />;

  if (loading && !modal && !costModal && !promptModal) return <div className="page-loading">{t('ui.table.loading')}</div>;

  if (requestedStatement && !statementTarget && !loadError) return <div className="page"><div role="alert" className="alert alert-error">
    Die angeforderte Einzelabrechnung ist nicht verfügbar.{' '}
    <button type="button" className="btn btn-secondary" onClick={() => setParams(current => {
      const next = new URLSearchParams(current); next.delete('statement_id'); return next;
    })}>Abrechnungsübersicht öffnen</button>
  </div></div>;

  if (view === 'detail' && selectedPeriod) {
    const periodCosts = costItems.filter(ci => ci.billing_period_id === selectedPeriod.id)
      .map(ci => ({ ...ci, allocation_key_name: akMap[ci.allocation_key_id]?.name || '—' }));
    const periodStmts = statements.filter(s => s.billing_period_id === selectedPeriod.id).map(enrichStatement);
    const totalCosts = sumMoney(periodCosts, 'amount');
    const nonRecoverable = sumMoney(periodCosts.filter(c => c.is_recoverable === false), 'amount');
    const tenantShare = sumMoney(periodStmts.filter(s => s.party !== 'vacancy'), 'total_cost');
    const vacancyShare = sumMoney(periodStmts.filter(s => s.party === 'vacancy'), 'total_cost');
    const editable = isMutable(selectedPeriod.status);
    const writableCosts = editable && canEditCosts;
    const writablePeriod = editable && canManagePeriods;
    const isFinalized = ['finalized', 'delivered'].includes(selectedPeriod.status);
    const canCorrect = CORRECTABLE.includes(selectedPeriod.status);
    const correctedVersion = selectedPeriod.corrects_period_id
      ? periods.find(p => p.id === selectedPeriod.corrects_period_id) : null;
    const revisionHistory = getRevisionHistory();
    const workflowStep = getWorkflowStep(selectedPeriod, periodCosts.length, periodStmts.length);

    return (
      <div className="page billing-workspace">
        {toast.Toast}
        <NotificationArrival record={params.get('source_id') ? undefined : selectedPeriod} rows={periodCosts} ready={!loading && !loadError} />

        <div className="detail-header">
          <button className="btn btn-sm btn-secondary" onClick={handleBackToList}>
            &larr; {t('pages.statements.back') || 'Zurück'}
          </button>
          <div className="detail-title">
            <h1>{selectedPeriod.label || t('pages.statements.defaultLabel') || 'Abrechnung'}</h1>
            <span className="text-muted">
              {propMap[selectedPeriod.property_id]?.name || '—'} · {formatDate(selectedPeriod.start_date)} – {formatDate(selectedPeriod.end_date)}
            </span>
            <Link className="detail-title-link" to={`/teha?property_id=${encodeURIComponent(selectedPeriod.property_id)}&period_id=${encodeURIComponent(selectedPeriod.id)}`}>TEHA Kundenportal für diese Periode</Link>
          </div>
          <div className="billing-header-actions">
            <StatusBadge status={selectedPeriod.status} />
            {writablePeriod && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setModal(selectedPeriod)}>Zeitraum bearbeiten</button>}

            {/* Primary workflow action based on current step */}
            {canManagePeriods && workflowStep === 3 && selectedPeriod.status === 'draft' && (
              <button
                className="btn btn-sm btn-primary"
                onClick={handleSubmitReview}
                disabled={submittingReview}
              >
                {submittingReview ? t('pages.statements.submitting') : t('pages.statements.submitReview')}
              </button>
            )}
            {canManagePeriods && workflowStep === 4 && (
              <button
                className="btn btn-sm btn-primary"
                onClick={handleFinalizePeriod}
                disabled={finalizing || preflightLoading || !preflight || preflight.has_blockers || Boolean(loadError)}
              >
                {finalizing ? t('pages.statements.finalizing') : t('pages.statements.finalize')}
              </button>
            )}
            {canManagePeriods && workflowStep === 5 && (
              <button
                className="btn btn-sm btn-primary"
                onClick={() => setDeliveryModal(true)}
                disabled={markingDelivered}
              >
                {markingDelivered ? t('pages.statements.markingDelivered') : t('pages.statements.markDelivered')}
              </button>
            )}

            {/* Secondary actions */}
            {canManagePeriods && selectedPeriod.status === 'review' && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleRevertDraft}
              >
                {t('pages.statements.revertDraft')}
              </button>
            )}

            {writablePeriod && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleGenerateStatements}
                disabled={generating || preflightLoading || !preflight || preflight.has_blockers || Boolean(loadError)}
                title={preflight?.has_blockers ? t('pages.statements.preflightBlockers') : ''}
              >
                {generating ? t('pages.statements.generating') : t('pages.statements.generate')}
              </button>
            )}

            {canManagePeriods && isFinalized && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleCreateReceivables}
                disabled={creatingReceivables}
              >
                {creatingReceivables ? t('pages.statements.creatingReceivables') : t('pages.statements.createReceivables')}
              </button>
            )}

            {canManagePeriods && canCorrect && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleCreateRevision}
                disabled={creatingRevision}
              >
                {creatingRevision ? t('pages.statements.creating') : t('pages.statements.startCorrection')}
              </button>
            )}
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
            {canCorrect && canRecordObjections && (
              <button
                className="btn btn-sm btn-secondary"
                onClick={handleDispute}
                disabled={disputing}
                style={{ color: 'var(--color-warning, #c57600)' }}
              >
                {disputing ? t('pages.statements.submitting') : t('pages.statements.dispute')}
              </button>
            )}
          </div>
        </div>

        <StepIndicator currentStep={workflowStep} t={t} />
        {loadError && <p className="alert alert-error" role="alert">{loadError} <button type="button" className="btn btn-sm btn-secondary" onClick={loadData}>Erneut laden</button></p>}
        <nav className="billing-section-nav" aria-label="Bereiche der Abrechnung">
          <button type="button" onClick={() => openCostSources('all')}><Pencil size={18} /><span>Kostenpositionen <strong>{periodCosts.length}</strong></span></button>
          <button type="button" onClick={() => { document.getElementById('billing-preflight')?.scrollIntoView?.({ block: 'start' }); document.getElementById('billing-preflight')?.focus(); }}><ListChecks size={18} /><span>Prüfung <strong>{preflightLoading ? 'Läuft' : !preflight ? 'Offen' : preflight.has_blockers ? `${preflight.blockers?.length || 1} offen` : 'Bereit'}</strong></span></button>
          <button type="button" onClick={() => openStatementSources('all')}><FileText size={18} /><span>Einzelabrechnungen & Schreiben <strong>{periodStmts.filter(row => row.party !== 'vacancy').length}</strong></span></button>
        </nav>

        {(correctedVersion || !editable) && (
          <p className="text-muted" role="note" style={{ marginBottom: '0.75rem' }}>
            {correctedVersion && t('pages.statements.correctsVersion', {
              revision: selectedPeriod.revision, label: correctedVersion.label,
            })}
            {correctedVersion && !editable && ' · '}
            {!editable && t('pages.statements.finalVersionNote')}
          </p>
        )}

        <div className="stats-grid" style={{ marginBottom: '1rem' }}>
          <button type="button" className="stat-card kpi-action" onClick={() => openCostSources('all')}>
            <div className="stat-label">{t('pages.statements.totalCosts')}</div>
            <div className="stat-value">{formatMoney(totalCosts)}</div>
          </button>
          {periodStmts.length > 0 && (
            <button type="button" className="stat-card kpi-action" onClick={() => openStatementSources('tenant')}>
              <div className="stat-label">{t('pages.statements.tenantShare') || 'Auf Mieter verteilt'}</div>
              <div className="stat-value">{formatMoney(tenantShare)}</div>
            </button>
          )}
          {periodStmts.length > 0 && (
            <button type="button" className="stat-card kpi-action" onClick={() => openStatementSources('vacancy')}>
              <div className="stat-label">{t('pages.statements.vacancyShare') || 'Leerstand (Eigentümer)'}</div>
              <div className="stat-value">{formatMoney(vacancyShare)}</div>
            </button>
          )}
          {nonRecoverable > 0 && (
            <button type="button" className="stat-card kpi-action" onClick={() => openCostSources('nonrecoverable')}>
              <div className="stat-label">{t('pages.statements.nonRecoverableShare') || 'Nicht umlagefähig'}</div>
              <div className="stat-value">{formatMoney(nonRecoverable)}</div>
            </button>
          )}
          <div className="stat-card">
            <div className="stat-label">{t('ui.form.status') || 'Status'}</div>
            <div className="stat-value"><StatusBadge status={selectedPeriod.status} /></div>
          </div>
        </div>

        <div className="card" id="billing-preflight" tabIndex={-1} style={{ marginBottom: '1rem', scrollMarginTop: '6rem' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>{t('pages.statements.preflight')}</strong>
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => refreshPreflight(selectedPeriod.id)}
            >
              {t('pages.statements.recheck')}
            </button>
          </div>
          <div className="card-body">
            {preflightLoading && <span className="text-muted">{t('pages.statements.checking')}</span>}
            {preflightError && <p role="alert">{preflightError} <button type="button" className="btn btn-sm btn-secondary" onClick={() => refreshPreflight(selectedPeriod.id)}>Prüfung erneut laden</button></p>}
            {!preflightLoading && !preflight && !preflightError && <span className="text-muted">{t('pages.statements.noPreflightData')}</span>}
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
                  <div className="text-muted" style={{ fontSize: 'var(--text-base)' }}>
                    {t('pages.statements.metricsContracts')}: {preflight.metrics?.contracts_in_period ?? 0} · {t('pages.statements.metricsCostItems')}: {preflight.metrics?.cost_items ?? 0} ·
                    {t('pages.statements.metricsMissingKeys')}: {preflight.metrics?.allocation_keys_missing ?? 0} · {t('pages.statements.metricsMissingArea')}: {preflight.metrics?.area_missing_units ?? 0}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {objectionsError && <p role="alert">{objectionsError} <button type="button" onClick={() => loadObjections(selectedPeriod.id)}>Widersprüche erneut laden</button></p>}
        {objections.length > 0 && (
          <div className="card" style={{ marginBottom: '1rem' }}>
            <div className="card-header"><strong>{t('pages.statements.objections')}</strong></div>
            <div className="card-body billing-table-scroll" role="region" aria-label="Widerspruchsliste" tabIndex={0}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t('pages.statements.objectionReceived')}</th>
                    <th>{t('pages.statements.objectionStatement')}</th>
                    <th>{t('pages.statements.objectionReason')}</th>
                    <th>{t('pages.statements.objectionStatus')}</th>
                  </tr>
                </thead>
                <tbody>
                  {objections.map(o => {
                    const stmt = statements.find(st => st.id === o.statement_id);
                    const correction = o.correction_period_id ? periods.find(p => p.id === o.correction_period_id) : null;
                    return (
                      <tr key={o.id}>
                        <td>{formatDate(o.received_on)}</td>
                        <td>{stmt ? (unitMap[stmt.unit_id]?.label || '—') : t('pages.statements.objectionWholePeriod')}</td>
                        <td>{o.reason}</td>
                        <td>
                          {o.status === 'rejected' ? (
                            <div>
                              <strong>Begründet zurückgewiesen</strong>
                              <p style={{ margin: '0.25rem 0', overflowWrap: 'anywhere' }}>{o.decision_reason}</p>
                              <small>Entscheidung: {o.decided_at ? new Date(o.decided_at).toLocaleString('de-DE') : '—'} · Autor: {o.decision_actor_id || '—'} · Original unverändert</small>
                            </div>
                          ) : <>{t(`pages.statements.objectionStatusValues.${o.status}`)}{o.decision_reason && <p>{o.decision_reason}<br /><small>Entscheidung: {o.decided_at ? new Date(o.decided_at).toLocaleString('de-DE') : '—'} · Autor: {o.decision_actor_id || '—'}</small></p>}</>}
                          {correction && (
                            <>
                              {' · '}
                              <button className="btn btn-sm btn-secondary" onClick={() => handleSelectPeriod(correction)}>
                                {correction.label}
                              </button>
                            </>
                          )}
                          {canRejectObjections && selectedPeriod.status === 'disputed' && o.status === 'open' && (
                            <> <button type="button" className="btn btn-sm btn-secondary"
                              aria-label={`Widerspruch zurückweisen: ${o.reason}`}
                              disabled={decisionLoading || rejectingBusy}
                              onClick={() => handleOpenDecision(o, 'reject')}>
                              Begründet zurückweisen
                            </button>
                            <button type="button" className="btn btn-sm btn-secondary"
                              aria-label={`Abrechnung überarbeiten: ${o.reason}`} disabled={decisionLoading || rejectingBusy}
                              onClick={() => handleOpenDecision(o, 'revise')}>Begründet überarbeiten</button></>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Revision History */}
        {revisionHistory.length > 1 && (
          <div className="card" style={{ marginBottom: '1rem' }}>
            <div className="card-header"><strong>{t('pages.statements.revisionHistory')}</strong></div>
            <div className="card-body billing-table-scroll" role="region" aria-label="Abrechnungsfassungen" tabIndex={0}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-base)' }}>
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

        <div ref={costSources} role="region" aria-label="Kostenquellen dieser Abrechnung" tabIndex={-1} style={{ marginBottom: '1.5rem' }}>
          {costSourceFilter === 'nonrecoverable' && <p>Quelle: Nicht umlagefähige Kosten. <button type="button" onClick={() => openCostSources('all')}>Alle Kosten anzeigen</button></p>}
          {writableCosts && <details className="billing-cost-suggestions"><summary>Häufige Kostenarten hinzufügen</summary>
            <p>Als Vorlage verwenden und Betrag sowie Verteilung prüfen. Diese Auswahl ist keine Pflichtliste.</p>
            <div>{COST_SUGGESTIONS.map(([description, category]) => <button key={category} type="button" className="btn btn-sm btn-secondary"
              onClick={() => { setCostPrefill({ description, cost_category: category }); setCostModal('create'); }}>+ {description}</button>)}</div>
          </details>}
          {writableCosts && (
            <div className="billing-cost-toolbar">
              <Link to={`/allocation-keys?property_id=${encodeURIComponent(selectedPeriod.property_id)}`} className="btn btn-sm btn-secondary">Verteilerschlüssel verwalten</Link>
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
          {writableCosts && <details className="billing-meter-import">
            <summary>Abrechnung oder Ableseprotokoll des Messdienstes auswerten (ista, Techem, Brunata, Minol …)</summary>
            <MeterDocumentImport key={selectedPeriod.id} propertyId={selectedPeriod.property_id} periodId={selectedPeriod.id}
              onApplied={() => loadData()} />
          </details>}
          <DataTable
            title={t('pages.statements.costItems')}
            columns={COST_COLUMNS}
            data={costSourceFilter === 'nonrecoverable' ? periodCosts.filter(row => row.is_recoverable === false) : periodCosts}
            drilldownKey={sourceDrilldown}
            writeArea="/billing/cost-items"
            inheritRouteFocus={false}
            inheritRouteSearch={false}
            settingsKey={`billing-costs:${selectedPeriod.id}`}
            onAdd={writableCosts ? () => { setCostPrefill(null); setCostModal('create'); } : undefined}
            onEdit={writableCosts ? (row => setCostModal(row)) : undefined}
            onDelete={writableCosts ? handleDeleteCost : undefined}
            rowActions={row => row.source_document_id ? [{ label: 'Quellbeleg öffnen', icon: <FileText size={16} />,
              onClick: () => navigate(`/documents?focus_id=${encodeURIComponent(row.source_document_id)}`) }] : []}
          />
        </div>

        {/* OCR Import Preview Dialog */}
        {ocrDraft && (
          <div className="modal-overlay" onClick={() => setOcrDraft(null)}>
            <div className="modal" role="dialog" aria-modal="true" aria-label="Erkannten Text prüfen" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
              <div className="modal-header">
                <h3>Erkannten Text prüfen</h3>
                <button className="btn-close" onClick={() => setOcrDraft(null)} aria-label="Schließen">&times;</button>
              </div>
              <div className="modal-body" style={{ display: 'grid', gap: '0.75rem' }}>
                {ocrDraft.ocr_fields && (
                  <div>
                    <strong>Erkannte Felder</strong>
                    <table style={{ width: '100%', fontSize: 'var(--text-base)', borderCollapse: 'collapse' }}>
                      <tbody>
                        {ocrDraft.ocr_fields.supplier && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Lieferant</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.supplier}</td>
                            <td style={{ padding: '4px 8px', color: '#888' }}>{Math.round((ocrDraft.confidence?.description || 0) * 100)}{'\u00a0%'}</td></tr>
                        )}
                        {ocrDraft.ocr_fields.total_amount != null && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Betrag</td>
                            <td style={{ padding: '4px 8px' }}>{formatMoney(ocrDraft.ocr_fields.total_amount)}</td>
                            <td style={{ padding: '4px 8px', color: '#888' }}>{Math.round((ocrDraft.confidence?.amount || 0) * 100)}{'\u00a0%'}</td></tr>
                        )}
                        {ocrDraft.ocr_fields.cost_category && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Kostenart</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.cost_category}</td>
                            <td style={{ padding: '4px 8px', color: '#888' }}>{Math.round((ocrDraft.confidence?.cost_category || 0) * 100)}{'\u00a0%'}</td></tr>
                        )}
                        {ocrDraft.ocr_fields.invoice_number && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Rechnungsnr.</td>
                            <td style={{ padding: '4px 8px' }}>{ocrDraft.ocr_fields.invoice_number}</td>
                            <td></td></tr>
                        )}
                        {ocrDraft.ocr_fields.invoice_date && (
                          <tr><td style={{ padding: '4px 8px', fontWeight: 500 }}>Datum</td>
                            <td style={{ padding: '4px 8px' }}>{formatDate(ocrDraft.ocr_fields.invoice_date)}</td>
                            <td></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
                {ocrDraft.ocr_text_preview && (
                  <div>
                    <strong>Textvorschau</strong>
                    <pre style={{ fontSize: 'var(--text-xs)', background: 'var(--bg-secondary, #f5f5f5)', padding: '8px', borderRadius: '4px', maxHeight: '150px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                      {ocrDraft.ocr_text_preview}
                    </pre>
                  </div>
                )}
                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => setOcrDraft(null)}>
                    Abbrechen
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={handleAcceptOcrDraft}>
                    Kostenposition prüfen und ergänzen
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {periodStmts.length > 0 && (
          <section ref={statementSourceTable} aria-label="Einzelabrechnungen als Verteilungsquelle" tabIndex={-1}>
          {statementSourceFilter !== 'all' && <p>Quelle: {statementSourceFilter === 'vacancy' ? 'Leerstand (Eigentümer)' : 'Auf Mieter verteilt'}. <button type="button" onClick={() => openStatementSources('all')}>Alle Einzelabrechnungen anzeigen</button></p>}
          <DataTable
            title={t('pages.statements.statementsTitle') || 'Einzelabrechnungen je Nutzungszeitraum'}
            inheritRouteFocus={false}
            inheritRouteSearch={false}
            settingsKey={`billing-statements:${selectedPeriod.id}`}
            columns={STMT_COLUMNS}
            data={statementSourceFilter === 'vacancy' ? periodStmts.filter(row => row.party === 'vacancy') : statementSourceFilter === 'tenant' ? periodStmts.filter(row => row.party !== 'vacancy') : periodStmts}
            drilldownKey={sourceDrilldown}
            onRowClick={setBreakdown}
            rowActions={row => [{ label: 'Aufschlüsselung öffnen', icon: <ListChecks size={16} />, onClick: () => setBreakdown(row) }]}
          />
          </section>
        )}

        {periodStmts.length === 0 && <section className="billing-empty-output" ref={statementSourceTable} aria-label="Einzelabrechnungen als Verteilungsquelle" tabIndex={-1}>
          <h2>Einzelabrechnungen & Schreiben</h2><p>Nach der Kostenerfassung und Prüfung die Einzelabrechnungen erzeugen. Anschließend können Sie die Verteilung und für jeden Mieter ein persönliches Anschreiben mit PDF prüfen.</p>
        </section>}
        {documentDialogs}
        {periodDialog}
        {deliveryModal && canManagePeriods && <FormModal title="Bereits erfolgte Zustellung vermerken" autosave={false}
          fields={[{ key: 'channel', label: 'Wie wurden die Abrechnungen zugestellt?', type: 'select', required: true,
            options: [{ value: 'post', label: 'Post' }, { value: 'email', label: 'E-Mail' }, { value: 'portal', label: 'Mieterportal' }],
            hint: 'Vermerkt die bestätigte Zustellung für alle Mieterabrechnungen. Ein Versand wird hierdurch nicht ausgelöst.' }]}
          onSave={handleMarkDelivered} onClose={() => { if (!markingDelivered) setDeliveryModal(false); }} />}
        {costModal && writableCosts && (
          <FormModal
            draftContext="billing/cost-items"
            draftAnchor={{ kind: 'billing_period', id: selectedPeriod.id }}
            title={costModal === 'create' ? 'Kostenposition hinzufügen' : 'Kostenposition bearbeiten'}
            fields={costFields}
            initial={costModal === 'create'
              ? { billing_period_id: selectedPeriod.id, ...costPrefill }
              : { ...costModal, is_recoverable: costModal.is_recoverable === false ? 'false' : 'true' }}
            onSave={handleSaveCost}
            repeatKeep={['allocation_key_id', 'is_recoverable']}
            onClose={() => { setCostModal(null); setCostPrefill(null); }}
          />
        )}

        {creatingObjection && canRecordObjections && <ObjectionDialog statements={periodStmts} unitMap={unitMap}
          busy={disputing} onConfirm={handleSaveObjection} onCancel={() => setCreatingObjection(false)} />}

        {rejectingObjection && canRejectObjections && (
          <RejectionDialog
            key={rejectingObjection.id}
            objection={rejectingObjection}
            action={rejectingObjection.action}
            onConfirm={handleRejectObjection}
            onCancel={() => setRejectingObjection(null)}
            busy={rejectingBusy}
          />
        )}

        {promptModal && (
          <PromptModal
            title={promptModal.title}
            defaultValue=""
            onConfirm={promptModal.onConfirm}
            onCancel={() => setPromptModal(null)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="page billing-workspace">
      {toast.Toast}
      <div className="billing-overview-heading"><div><h1>Nebenkostenabrechnungen</h1><p>Kosten, Verteilung und persönliche Abrechnungsschreiben je Immobilie und Zeitraum.</p></div></div>
      <div className="toolbar billing-overview-filters"><label className="inline-field">Ansicht <select value={sourceFilter} onChange={event => setParams(current => {
        const next = new URLSearchParams(current); ['focus_id', 'suche'].forEach(key => next.delete(key));
        if (event.target.value === 'all') next.delete('filter'); else next.set('filter', event.target.value); return next;
      })}><option value="all">Abrechnungszeiträume</option><option value="statements">Alle Einzelabrechnungen</option><option value="preflight_blockers">Zeiträume mit Prüfbedarf</option></select></label>
        <label>Immobilie <select value={params.get('property_id') || ''} onChange={event => setParams(current => {
          const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('period_id');
          if (event.target.value) next.set('property_id', event.target.value); else next.delete('property_id'); return next;
        })}><option value="">Alle Immobilien</option>{properties.map(property => <option key={property.id} value={property.id}>{property.name}</option>)}</select></label>
        <label>Jahr <select value={params.get('year') || ''} onChange={event => setParams(current => {
          const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('period_id');
          if (event.target.value) next.set('year', event.target.value); else next.delete('year'); return next;
        })}><option value="">Alle Jahre</option>{[...new Set([new Date().getFullYear().toString(), ...periods.flatMap(period => {
          const start = Number(period.start_date?.slice(0, 4)); const end = Number(period.end_date?.slice(0, 4));
          return start > 0 && end >= start ? Array.from({ length: end - start + 1 }, (_, index) => String(start + index)) : [];
        })])].sort().reverse().map(year => <option key={year} value={year}>{year}</option>)}</select></label>
        <label>Status <select value={params.get('status') || ''} onChange={event => setParams(current => {
          const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('period_id');
          if (event.target.value) next.set('status', event.target.value); else next.delete('status'); return next;
        })}><option value="">Alle Status</option>{['draft', 'review', 'finalized', 'delivered', 'disputed', 'corrected'].map(status => <option key={status} value={status}>{codeLabel(status)}</option>)}</select></label>
        {selectedPeriod && canManagePeriods && canEditCosts && <button className="btn btn-sm btn-secondary" onClick={() => setModal('copy')}>Vorjahr kopieren</button>}</div>
      {copyResult && <section className={copyResult.failures.length ? 'alert-error' : 'card'} role={copyResult.failures.length ? 'alert' : 'status'} aria-label="Ergebnis der Abrechnungskopie">
        <p>Neuer Zeitraum „{copyResult.period.label}“ angelegt. {copyResult.copied} von {copyResult.total} Kostenpositionen als Vorlagen übernommen; die Beträge sind 0 und müssen ergänzt werden.</p>
        {copyResult.failures.length > 0 && <><p>Diese Positionen fehlen im neuen Zeitraum. Bitte dort prüfen und bei Bedarf einzeln ergänzen; der Zeitraum wurde bereits angelegt.</p>
          <ul>{copyResult.failures.map((failure, index) => <li key={index}>{failure.description}: {failure.message}</li>)}</ul></>}
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => handleSelectPeriod(periods.find(period => period.id === copyResult.period.id) || copyResult.period)}>Neuen Zeitraum prüfen</button>
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => setCopyResult(null)}>Hinweis schließen</button>
      </section>}
      {loadError && <p role="alert">{loadError} <button type="button" onClick={loadData}>Erneut laden</button></p>}
      {sourceFilter === 'preflight_blockers' && <><p className="text-muted">Noch nicht abgeschlossene Zeiträume ohne abrechenbare Verträge, ohne Kosten oder mit einer unpassenden Schlüsselzuordnung.</p>
        {sourceRows.loading && <p role="status">Abrechnungsprüfungen werden geladen…</p>}
        {sourceRows.error && <p role="alert">{sourceRows.error} <button type="button" onClick={() => setSourceAttempt(value => value + 1)}>Abrechnungsprüfungen erneut laden</button></p>}</>}
      <DataTable
        title={sourceFilter === 'statements' ? 'Einzelabrechnungen & Schreiben' : 'Abrechnungszeiträume'}
        columns={sourceFilter === 'statements' ? STMT_COLUMNS : COLUMNS}
        data={sourceFilter === 'statements' ? statementSources : enriched}
        drilldownKey={drilldown}
        emptyText={sourceFilter === 'preflight_blockers' && (sourceRows.loading || sourceRows.error) ? 'Abrechnungsprüfungen noch nicht verfügbar.' : loadError ? 'Daten noch nicht verfügbar.' : undefined}
        viewConfig={{ column_filters: { source_filter: sourceFilter } }}
        onApplyView={config => setParams(current => { const next = new URLSearchParams(current); const value = config.column_filters?.source_filter;
          if (['statements', 'preflight_blockers'].includes(value)) next.set('filter', value); else next.delete('filter'); return next; })}
        onAdd={sourceFilter === 'statements' || !canManagePeriods ? undefined : () => setModal('create')}
        onRowClick={openSourceRow}
        // one way to open a row: "Bearbeiten" opened the same as this action, with the same pencil
        rowActions={row => [{ label: sourceFilter === 'statements' ? 'Aufschlüsselung öffnen' : 'Kosten und Abrechnung öffnen',
          icon: sourceFilter === 'statements' ? <ListChecks size={16} /> : <FolderOpen size={16} />,
          onClick: () => sourceFilter === 'statements' ? setBreakdown(row) : handleSelectPeriod(row) }]}
      />
      {documentDialogs}
      {periodDialog}
    </div>
  );
}
