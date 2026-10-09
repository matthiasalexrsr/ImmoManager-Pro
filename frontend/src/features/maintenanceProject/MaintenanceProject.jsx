import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import FormModal from '../../components/FormModal';
import StatusBadge from '../../components/StatusBadge';
import { useConfirm } from '../../components/ConfirmDialog';
import { projectApi } from './projectApi';
import { Pill } from './ProjectUi';
import { contactLabel, money } from './projectFormat';
import { useProjectText } from './text';
import { AppointmentsTab, OverviewTab, WorkTab } from './PlanningTabs';
import { CostsTab, ProcurementTab } from './CommercialTabs';
import { DocumentsTab, ProtocolsTab } from './EvidenceTabs';
import './maintenanceProject.css';

const TABS = [
  ['overview', 'tabOverview'], ['work', 'tabWork'], ['appointments', 'tabAppointments'],
  ['procurement', 'tabProcurement'], ['costs', 'tabCosts'], ['protocols', 'tabProtocols'], ['documents', 'tabDocuments'],
];

/** The project file of one maintenance case (Schaden → Projektakte). */
export default function MaintenanceProject({ caseId }) {
  const { tx } = useProjectText();
  const confirm = useConfirm();
  const [project, setProject] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState('overview');
  const [notice, setNotice] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [contacts, setContacts] = useState([]);

  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    projectApi.load(caseId, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setProject(data); })
      .catch(failure => { if (failure?.name !== 'AbortError') setError(failure.message || tx.loadFailed); });
    return () => controller.abort();
  }, [caseId, revision, tx.loadFailed]);

  useEffect(() => {
    const controller = new AbortController();
    projectApi.contacts({ signal: controller.signal })
      .then(rows => { if (Array.isArray(rows)) setContacts(rows); })
      .catch(() => {});      // without the address book the forms still work with free text
    return () => controller.abort();
  }, []);

  const act = useCallback(async (operation, success, question) => {
    if (question && !(await (confirm ? confirm(question) : Promise.resolve(window.confirm(question))))) return false;
    setBusy(true);
    setNotice(null);
    try {
      await operation();
      setNotice({ kind: 'success', text: success || tx.saved });
      reload();
      return true;
    } catch (failure) {
      setNotice({ kind: 'error', text: failure.message });
      return false;
    } finally {
      setBusy(false);
    }
  }, [confirm, reload, tx.saved]);

  const openForm = useCallback(config => setForm({ ...config, key: Date.now() }), []);
  const contactOptions = useMemo(() => [...contacts]
    .sort((a, b) => (a.contact_type === 'supplier' ? 0 : 1) - (b.contact_type === 'supplier' ? 0 : 1)
      || contactLabel(a).localeCompare(contactLabel(b)))
    .map(contact => ({ value: contact.id, label: contactLabel(contact) })), [contacts]);

  if (error && !project) {
    return (
      <div className="page maintenance-project">
        <div className="alert alert-error" role="alert">{error}</div>
        <div className="mp-actions">
          <button type="button" className="btn btn-secondary" onClick={reload}>{tx.retry}</button>
          <Link className="btn btn-secondary" to="/maintenance">{tx.back}</Link>
        </div>
      </div>
    );
  }
  if (!project) return <div className="page-loading" role="status">{tx.loading}</div>;

  const { case: record, workflow, costs, abilities: can } = project;
  const ctx = { project, caseId, tx, can, act, openForm, contactOptions, busy, reload };
  const readOnly = !Object.values(can).some(Boolean);

  const changeStatus = target => {
    const label = tx[`to_${target.status}`] || target.status;
    if (target.reason_required) {
      openForm({
        title: tx.reasonTitle,
        fields: [{ key: 'reason', label: tx.reason, type: 'textarea', required: true }],
        onSave: values => projectApi.transition(caseId, { status: target.status, reason: values.reason }),
        success: tx.statusChanged,
      });
      return;
    }
    act(() => projectApi.transition(caseId, { status: target.status }), tx.statusChanged, `${label}?`);
  };

  return (
    <div className="page maintenance-project">
      <div className="detail-header mp-header">
        <Link className="btn btn-sm btn-secondary" to="/maintenance">← {tx.back}</Link>
        <div className="detail-title mp-title">
          <span className="text-muted mp-kicker">{tx.projectFile}</span>
          <h1>{record.title}</h1>
          <span className="text-muted">
            {[record.property_name, record.unit_label].filter(Boolean).join(' · ') || '—'}
          </span>
        </div>
        <StatusBadge status={record.status} />
      </div>

      {can.transition && workflow.allowed.length > 0 && (
        <div className="mp-workflow" aria-label={tx.reasonTitle}>
          {workflow.allowed.map(target => (
            <button key={target.status} type="button"
              className={`btn btn-sm ${target.status === 'completed' ? 'btn-primary' : 'btn-secondary'}`}
              disabled={busy || target.blockers.length > 0}
              title={target.blockers.length ? `${tx.blocked}: ${target.blockers.join(' ')}` : undefined}
              onClick={() => changeStatus(target)}>
              {tx[`to_${target.status}`] || target.status}
            </button>
          ))}
          {workflow.allowed.filter(target => target.blockers.length).map(target => (
            <p key={target.status} className="mp-blocker text-muted">
              {tx[`to_${target.status}`]}: {target.blockers.join(' ')}
            </p>
          ))}
        </div>
      )}
      {readOnly && <p className="text-muted mp-readonly">{tx.readOnly}</p>}

      <div className="stats-grid mp-kpis">
        {[['budget', costs.budget], ['ordered', costs.ordered], ['invoiced', costs.invoiced], ['paid', costs.paid]]
          .map(([key, value]) => (
            <div key={key} className="stat-card">
              <div className="stat-label">{tx[key]}</div>
              <div className="stat-value">{value == null ? '—' : money(value)}</div>
            </div>
          ))}
      </div>
      {costs.warnings.length > 0 && (
        <div className="mp-warnings" role="note">
          {costs.warnings.map((warning, index) => <Pill key={index} tone="yellow">{warning.message}</Pill>)}
        </div>
      )}

      {notice && (
        <div className={notice.kind === 'error' ? 'alert alert-error' : 'alert alert-success'}
          role={notice.kind === 'error' ? 'alert' : 'status'}>
          {notice.text}
        </div>
      )}

      <div className="detail-tabs mp-tabs" role="tablist" aria-label={tx.sections}>
        {TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" id={`mp-tab-${key}`} aria-selected={tab === key}
            aria-controls={`mp-panel-${key}`} className={`detail-tab ${tab === key ? 'active' : ''}`}
            onClick={() => setTab(key)}>
            {tx[label]}
          </button>
        ))}
      </div>
      <div className="detail-tab-content" role="tabpanel" id={`mp-panel-${tab}`} aria-labelledby={`mp-tab-${tab}`}>
        {tab === 'overview' && <OverviewTab ctx={ctx} />}
        {tab === 'work' && <WorkTab ctx={ctx} />}
        {tab === 'appointments' && <AppointmentsTab ctx={ctx} />}
        {tab === 'procurement' && <ProcurementTab ctx={ctx} />}
        {tab === 'costs' && <CostsTab ctx={ctx} />}
        {tab === 'protocols' && <ProtocolsTab ctx={ctx} />}
        {tab === 'documents' && <DocumentsTab ctx={ctx} />}
      </div>

      {form && (
        <FormModal key={form.key} title={form.title} fields={form.fields} initial={form.initial || null}
          onClose={() => setForm(null)}
          onSave={async values => {
            await form.onSave(values);
            setNotice({ kind: 'success', text: form.success || tx.saved });
            reload();
          }} />
      )}
    </div>
  );
}
