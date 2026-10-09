/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation } from 'react-router-dom';
import { Building2, CalendarDays, Check, ClipboardCheck, Copy, FileCheck, FileText, Mail, MapPin, Phone, UserRound, X } from 'lucide-react';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import { formatDate, formatMoney } from '../../utils/format';
import FileViewer from '../../components/FileViewer';
import HousingConfirmationDialog from '../housingConfirmation/HousingConfirmationDialog';
import HandoverProtocolsDialog from '../handoverProtocol/HandoverProtocolsDialog';
import { handoverText } from '../handoverProtocol/handoverProtocolText';
import PartyDocuments from './PartyDocuments';
import { useModalDialog } from './useModalDialog';
import { usePartyText } from './text';
import './partyWorkspace.css';

const PartyWorkspaceContext = createContext(null);

export function usePartyWorkspace() {
  return useContext(PartyWorkspaceContext);
}

export function PartyLink({ tenantId, children, className = '', ...props }) {
  const workspace = usePartyWorkspace();
  if (!tenantId) return <span className={className}>{children || '—'}</span>;
  // This fallback keeps account access usable in isolated pages and tests.
  if (!workspace) return <a className={className} href={`/tenants/${encodeURIComponent(tenantId)}/account`} {...props}>{children}</a>;
  return <button type="button" className={`party-link ${className}`} aria-haspopup="dialog" {...props} onClick={event => { event.stopPropagation(); props.onClick?.(event); if (!event.defaultPrevented) workspace.openParty(tenantId); }}>{children}</button>;
}

export function PartyWorkspaceProvider({ children }) {
  const [selection, setSelection] = useState(null);
  const location = useLocation();
  const routeRef = useRef(location);
  const closeParty = useCallback(() => setSelection(null), []);
  const openParty = useCallback((tenantId, { tab = 'overview' } = {}) => {
    if (!tenantId) return;
    setSelection({ tenantId: String(tenantId), tab: tab === 'documents' ? 'documents' : 'overview' });
  }, []);
  const setTab = useCallback(tab => setSelection(previous => previous ? { ...previous, tab } : previous), []);
  useEffect(() => {
    if (routeRef.current !== location) closeParty();
    routeRef.current = location;
  }, [location, closeParty]);
  const value = useMemo(() => ({ openParty, closeParty }), [openParty, closeParty]);
  return <PartyWorkspaceContext.Provider value={value}>{children}{selection && <PartyPanel key={selection.tenantId} tenantId={selection.tenantId} tab={selection.tab} onTab={setTab} onClose={closeParty} />}</PartyWorkspaceContext.Provider>;
}

function CopyButton({ value, label }) {
  const { text } = usePartyText();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  const timerRef = useRef(null);
  const mountedRef = useRef(false);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; clearTimeout(timerRef.current); }; }, []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      if (!mountedRef.current) return;
      setError(false);
      setCopied(true);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      if (mountedRef.current) setError(true);
    }
  };
  return <span className="party-copy-wrap"><button type="button" className="party-icon-button" onClick={copy} aria-label={`${copied ? text.copied : text.copy}: ${label}`} title={`${text.copy}: ${label}`}>{copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}</button>{error && <small className="party-inline-error" role="alert">{text.copyFailed}</small>}<span className="party-sr-only" role="status">{copied ? text.copied : ''}</span></span>;
}

function ContactRow({ icon, label, value, href, children }) {
  const Icon = icon;
  return <div className="party-contact-row"><Icon size={17} aria-hidden="true" /><div className="party-contact-value"><span className="party-field-label">{label}</span>{href ? <a href={href}>{value}</a> : children || <span>{value}</span>}</div><CopyButton value={value} label={label} /></div>;
}

function ContractCard({ contract, onDocuments, onHousing, onHandover }) {
  const { text, locale } = usePartyText();
  const rent = contract.current_rent;
  const rentStart = rent?.valid_from || rent?.effective_from || rent?.start_date;
  const status = { active: text.active, terminated: text.terminated, expired: text.expired, draft: text.draft }[contract.status] || contract.status;
  return <article className="party-contract-card"><div className="party-contract-heading"><h4>{contract.contract_number || text.contract}</h4><span className={`party-status party-status-${contract.status === 'active' ? 'active' : 'neutral'}`}>{status}</span></div><p className="party-contract-property"><Building2 size={16} aria-hidden="true" /><span>{contract.property_name || text.emptyValue}{contract.unit_label && <strong>{contract.unit_label}</strong>}</span></p><div className="party-contract-dates"><CalendarDays size={15} aria-hidden="true" /><span><span className="party-sr-only">{text.start}: </span>{formatDate(contract.start_date)} — <span className="party-sr-only">{text.end}: </span>{contract.end_date ? formatDate(contract.end_date) : text.openEnded}</span></div>{rent ? <><dl className="party-contract-rent">{[['cold_rent', text.coldRent], ['service_charge', text.serviceCharge], ['heating_charge', text.heatingCharge]].filter(([key]) => rent[key] != null).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{formatMoney(rent[key])}</dd></div>)}</dl>{rentStart && <small className="party-muted">{text.rentDate} {formatDate(rentStart)}</small>}</> : <p className="party-muted party-rent-missing">{text.rentMissing}</p>}<div className="party-contract-actions"><button type="button" className="party-contract-docs" onClick={() => onDocuments(contract.id)}><FileText size={14} aria-hidden="true" />{text.contractDocs}</button><button type="button" className="party-contract-docs" onClick={() => onHousing(contract.id)}><FileCheck size={14} aria-hidden="true" />{text.housingConfirmation}</button><button type="button" className="party-contract-docs" onClick={() => onHandover(contract.id)}><ClipboardCheck size={14} aria-hidden="true" />{handoverText(locale, 'action')}</button></div></article>;
}

function ContractGroups({ contracts, onDocuments, onHousing, onHandover }) {
  const { text } = usePartyText();
  const today = new Date();
  const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const groups = { current: [], upcoming: [], history: [], drafts: [] };
  for (const contract of contracts) {
    if (contract.status === 'draft') groups.drafts.push(contract);
    else if (contract.status === 'expired' || contract.status === 'terminated' || (contract.end_date && contract.end_date < day)) groups.history.push(contract);
    else if (contract.start_date > day) groups.upcoming.push(contract);
    else groups.current.push(contract);
  }
  return <section className="party-section"><div className="party-section-heading"><h3>{text.contracts}</h3><span className="party-count">{contracts.length}</span></div>{!contracts.length ? <p className="party-muted">{text.noContracts}</p> : Object.entries(groups).filter(([, items]) => items.length > 0).map(([key, items]) => <div key={key} className="party-contract-group"><h4 className="party-subheading">{text[key]}</h4>{[...items].sort((a, b) => String(b.start_date).localeCompare(String(a.start_date))).map(contract => <ContractCard key={contract.id} contract={contract} onDocuments={onDocuments} onHousing={onHousing} onHandover={onHandover} />)}</div>)}</section>;
}

function PartyOverview({ overview, onDocuments, onHousing, onHandover }) {
  const { text } = usePartyText();
  const tenant = overview.tenant;
  const cityLine = [tenant.postal_code, tenant.city].filter(Boolean).join(' ');
  const address = [tenant.address_line, cityLine, tenant.country].filter(Boolean).join('\n');
  const hasContact = tenant.email || tenant.phone || address;
  return <div className="party-overview"><section className="party-section"><h3>{text.contact}</h3><div className="party-contact-list">{tenant.email && <ContactRow icon={Mail} label={text.email} value={tenant.email} href={`mailto:${tenant.email}`} />}{tenant.phone && <ContactRow icon={Phone} label={text.phone} value={tenant.phone} href={`tel:${tenant.phone.replace(/[^+\d]/g, '')}`} />}{address && <ContactRow icon={MapPin} label={text.address} value={address}><address>{tenant.address_line && <span>{tenant.address_line}</span>}{cityLine && <span>{cityLine}</span>}{tenant.country && <span>{tenant.country}</span>}</address></ContactRow>}{!hasContact && <p className="party-muted">{text.noContact}</p>}</div></section><ContractGroups contracts={overview.contracts || []} onDocuments={onDocuments} onHousing={onHousing} onHandover={onHandover} /><section className="party-section"><h3>{text.notes}</h3><p className={tenant.notes ? 'party-notes' : 'party-muted'}>{tenant.notes || text.noNotes}</p></section></div>;
}

function PartyPanel({ tenantId, tab, onTab, onClose }) {
  const { text } = usePartyText();
  const canEdit = useCanWrite('/tenants');
  const store = useDataStore();
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [viewer, setViewer] = useState(null);
  const [housing, setHousing] = useState(null);
  const [handover, setHandover] = useState(null);
  const [contractFilter, setContractFilter] = useState('');
  const dialogRef = useRef(null);
  const id = useId();
  useModalDialog(dialogRef, onClose);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.get(`/tenants/${encodeURIComponent(tenantId)}/overview`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!data?.tenant || String(data.tenant.id) !== tenantId) throw new Error(text.loadFailed);
        setOverview(data);
      })
      .catch(err => { if (!controller.signal.aborted) setError(err.message || text.loadFailed); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [tenantId, attempt, text.loadFailed]);

  const tenant = overview?.tenant;
  const name = tenant?.full_name || text.party;
  const initials = tenant?.full_name?.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
  const closeViewer = useCallback(() => setViewer(null), []);
  const closeHousing = useCallback(() => setHousing(null), []);
  const housingPublished = useCallback(() => { store?.invalidateRelated('documents'); setAttempt(value => value + 1); }, [store]);
  const closeHandover = useCallback(() => setHandover(null), []);
  const handoverChanged = useCallback(() => store?.invalidateRelated('documents', 'handover_protocols'), [store]);
  const covered = Boolean(viewer || housing || handover);   // a dialog on top: the panel is inert behind it
  const openContractDocuments = contractId => { setContractFilter(contractId); onTab('documents'); };
  const tabKeydown = event => {
    const tabs = ['overview', 'documents'];
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs[tab === 'overview' ? 1 : 0];
    onTab(next);
    dialogRef.current?.querySelector(`[data-party-tab="${next}"]`)?.focus();
  };

  return createPortal(<><div className="party-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}><section className="party-panel" role="dialog" aria-modal="true" aria-labelledby={`${id}-name`} aria-hidden={covered ? true : undefined} inert={covered ? true : undefined} tabIndex={-1} ref={dialogRef}><header className="party-panel-header"><span className="party-eyebrow">{text.party}</span><button type="button" className="party-icon-button party-close" onClick={onClose} aria-label={text.close}><X size={21} aria-hidden="true" /></button><div className="party-identity"><div className="party-avatar" aria-hidden="true">{initials || <UserRound size={27} />}</div><div className="party-identity-text"><h2 id={`${id}-name`}>{name}</h2>{tenant && <span className={`party-status party-status-${tenant.archived ? 'neutral' : 'active'}`}><span aria-hidden="true" />{tenant.archived ? text.archived : text.active}</span>}</div></div>{tenant && <div className="party-primary-actions"><Link className="btn btn-sm btn-primary" to={`/tenants/${encodeURIComponent(tenantId)}/account`}>{text.account}</Link>{canEdit && <Link className="btn btn-sm btn-secondary" to={`/tenants?edit=${encodeURIComponent(tenantId)}`}>{text.edit}</Link>}</div>}</header><div className="party-tabs" role="tablist" aria-label={text.party} onKeyDown={tabKeydown}>{['overview', 'documents'].map(value => <button key={value} type="button" id={`${id}-${value}`} role="tab" data-party-tab={value} aria-selected={tab === value} aria-controls={`${id}-content`} tabIndex={tab === value ? 0 : -1} onClick={() => onTab(value)}>{text[value]}{value === 'documents' && overview && <span className="party-tab-count">{overview.document_count ?? 0}</span>}</button>)}</div><div className="party-panel-content" id={`${id}-content`} role="tabpanel" aria-labelledby={`${id}-${tab}`} tabIndex={0}>{error && <div className="party-error" role="alert"><p>{text.loadFailed}</p><p className="party-muted">{error}</p><button type="button" className="btn btn-sm btn-secondary" onClick={() => setAttempt(value => value + 1)}>{text.retry}</button></div>}{loading && !overview ? <div className="party-loading" role="status">{text.loading}</div> : overview && (tab === 'overview' ? <PartyOverview overview={overview} onDocuments={openContractDocuments} onHousing={setHousing} onHandover={setHandover} /> : <PartyDocuments tenantId={tenantId} overview={overview} onPreview={setViewer} contractFilter={contractFilter} onContractFilter={setContractFilter} />)}</div></section></div>{viewer && <FileViewer key={viewer.id} fileUrl={viewer.file_url} title={viewer.title} onClose={closeViewer} />}{housing && <HousingConfirmationDialog contractId={housing} onClose={closeHousing} onPublished={housingPublished} />}{handover && <HandoverProtocolsDialog contractId={handover} onClose={closeHandover} onChanged={handoverChanged} />}</>, document.body);
}
