import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import useLookupChoices from '../../hooks/useLookupChoices';
import { usePortalAdminAction, usePortalAdminPage } from './adminHooks';
import PortalConversations from './PortalConversations';
import '../dataTransfer/dataTransfer.css';

const BASE = '/portal-admin';

export default function PortalAdmin() {
  const [refresh, setRefresh] = useState(0), [skip, setSkip] = useState(0), [selected, setSelected] = useState(null), [area, setArea] = useState('access');
  const [configuration, configurationError] = usePortalAdminPage(`${BASE}/configuration`, refresh);
  const [page, error] = usePortalAdminPage(`${BASE}/grants?skip=${skip}&limit=25`, refresh);
  const access = page?.items.find(row => row.id === selected);
  const reload = () => setRefresh(value => value + 1);
  return <section className="panel data-transfer"><div className="panel-body">
    <h2>Externe Mieter- und Eigentümerportale</h2>
    <p>Ein Zugang gilt nur für eine persönlich geprüfte Partei und ihr konkretes Miet- oder Eigentumsverhältnis. Jede Dokumentfassung wird einzeln veröffentlicht.</p>
    {configurationError && <p role="alert">{configurationError}</p>}
    {configuration && (configuration.available ? <p>Portaladresse: <a href={`${configuration.url}/portal`} target="_blank" rel="noopener noreferrer">{configuration.url}/portal</a>{configuration.local_test_mode && ' · Lokaler Testmodus'}</p>
      : <p role="status">{configuration.reason} Die Freischaltung erfolgt in der Betriebskonfiguration mit einer HTTPS-Adresse.</p>)}
    <div className="transfer-actions"><button className="btn btn-secondary" aria-pressed={area === 'access'} onClick={() => setArea('access')}>Zugänge und Veröffentlichungen</button>
      <button className="btn btn-secondary" aria-pressed={area === 'cases'} onClick={() => setArea('cases')}>Externe Anliegen und Rückfragen</button></div>
    {area === 'cases' ? <PortalConversations /> : <>
      <InviteParty available={Boolean(configuration?.available)} onCreated={reload} />
      <h3>Geprüfte Zuordnungen</h3>{error && <p role="alert">{error} <button onClick={reload}>Erneut laden</button></p>}
      <button className="btn btn-secondary" onClick={reload}>Aktuellen Stand laden</button>
      {!page ? <p role="status">Zuordnungen werden geladen …</p> : <>
        <ul className="transfer-list">{page.items.map(row => <li key={row.id}><strong>{row.email}</strong> · {row.kind === 'tenant' ? 'Mieter' : 'Eigentümer'} · {row.active && row.identity_active ? 'Aktiv' : 'Gesperrt oder Einladung ausstehend'}
          <p>Verhältnis: {row.contract_id || row.ownership_id}</p><button className="btn btn-secondary" onClick={() => setSelected(row.id)}>Zugang und Freigaben verwalten</button></li>)}</ul>
        {!page.items.length && <p>Noch keine externen Zugänge eingerichtet.</p>}
        <nav aria-label="Portalzugänge"><button className="btn btn-secondary" disabled={!skip} onClick={() => { setSkip(Math.max(0, skip - 25)); setSelected(null); }}>Zurück</button>
          <span> {page.total} Zuordnungen </span><button className="btn btn-secondary" disabled={skip + 25 >= page.total} onClick={() => { setSkip(skip + 25); setSelected(null); }}>Weiter</button></nav>
      </>}
      {access && <GrantDetails key={access.id} access={access} onChanged={reload} />}
    </>}
  </div></section>;
}

function InviteParty({ available, onCreated }) {
  const choices = useLookupChoices({ contracts: '/contracts', tenants: '/tenants', shares: '/ownership-shares', contacts: '/contacts', properties: '/properties', units: '/units' });
  const [kind, setKind] = useState('tenant'), [relation, setRelation] = useState(''), [email, setEmail] = useState(''), [verification, setVerification] = useState(''), [created, setCreated] = useState(null);
  const action = usePortalAdminAction();
  const relations = kind === 'tenant' ? choices.data.contracts || [] : choices.data.shares || [];
  const selected = relations.find(row => row.id === relation);
  const party = selected && (kind === 'tenant' ? choices.data.tenants?.find(row => row.id === selected.tenant_id) : choices.data.contacts?.find(row => row.id === selected.owner_contact_id));
  const title = row => {
    const person = kind === 'tenant' ? choices.data.tenants?.find(p => p.id === row.tenant_id) : choices.data.contacts?.find(p => p.id === row.owner_contact_id);
    const name = person?.full_name || [person?.first_name, person?.last_name].filter(Boolean).join(' ') || person?.company || row.owner_contact_id;
    return [name, choices.data.properties?.find(p => p.id === row.property_id)?.name, choices.data.units?.find(p => p.id === row.unit_id)?.label, row.contract_number || `${row.share_percent} %`].filter(Boolean).join(' · ');
  };
  return <details><summary>Geprüfte Partei einladen</summary><form className="transfer-grid" onSubmit={async event => {
    event.preventDefault(); if (!party || !selected) return;
    const result = await action.perform(`${BASE}/invitations`, { kind, party_id: party.id, relation_id: relation, email, verification, expires_hours: 48 });
    if (result) { setCreated(result); onCreated(); }
  }}>
    <p>Identität, persönliche E-Mail-Adresse und Verhältnis anhand Ihrer Unterlagen prüfen. Der Link wird nur einmal angezeigt und verfällt nach 48 Stunden. Geben Sie ihn ausschließlich an die geprüfte Person weiter.</p>
    {choices.error && <p role="alert">{choices.error} <button type="button" onClick={choices.reload}>Auswahl neu laden</button></p>}
    <label>Portalart<select disabled={action.busy} value={kind} onChange={event => { setKind(event.target.value); setRelation(''); setEmail(''); setCreated(null); }}><option value="tenant">Mieter</option><option value="owner">Eigentümer</option></select></label>
    <label>Geprüftes Verhältnis<select required disabled={!choices.ready || action.busy} value={relation} onChange={event => {
      setRelation(event.target.value); setCreated(null);
      const found = relations.find(row => row.id === event.target.value);
      const person = kind === 'tenant' ? choices.data.tenants?.find(p => p.id === found?.tenant_id) : choices.data.contacts?.find(p => p.id === found?.owner_contact_id);
      setEmail(person?.email || '');
    }}><option value="">Bitte auswählen</option>{relations.map(row => <option key={row.id} value={row.id}>{title(row)}</option>)}</select></label>
    <label>Persönliche E-Mail-Adresse<input required type="email" maxLength={254} value={email} disabled={action.busy} onChange={event => setEmail(event.target.value)} /></label>
    <label>Dokumentierte Identitäts- und Verhältnisprüfung<textarea required minLength={10} maxLength={2000} value={verification} disabled={action.busy} onChange={event => setVerification(event.target.value)} /></label>
    {action.error && <p role="alert">{action.error}</p>}<button className="btn btn-primary" disabled={action.busy || !available || !choices.ready || !party}>Einladungslink erstellen</button>
    {created && <div role="status">{created.invitation_url ? <><p>Einladung an {created.email} · gültig bis {new Date(created.expires_at).toLocaleString('de-DE')}</p><label>Einmalig angezeigter Einladungslink<input readOnly value={created.invitation_url} onFocus={event => event.target.select()} /></label>
      <button className="btn btn-secondary" type="button" onClick={() => setCreated(null)}>Linkanzeige schließen</button></> : <p>{created.notice}</p>}</div>}
  </form></details>;
}

function GrantDetails({ access, onChanged }) {
  const auth = useAuth(), heading = useRef(null);
  const [reason, setReason] = useState(''), [skip, setSkip] = useState(0), [version, setVersion] = useState(''), [title, setTitle] = useState(''), [publishReason, setPublishReason] = useState(''), [refresh, setRefresh] = useState(0);
  const action = usePortalAdminAction();
  const [publications, publicationError] = usePortalAdminPage(`${BASE}/grants/${access.id}/publications`, refresh);
  const [documents, documentError] = usePortalAdminPage(access.active ? `${BASE}/grants/${access.id}/documents?skip=${skip}&limit=25` : null, refresh);
  useEffect(() => { heading.current?.focus(); }, []);
  const reload = () => { setRefresh(value => value + 1); onChanged(); };
  const change = async (path, revision, active) => { if (await action.perform(path, { expected_revision: revision, active, reason }, 'put')) { setReason(''); reload(); } };
  const fullAccess = auth?.user?.role === 'eigentuemer' || auth?.user?.portfolio_access === 'all';
  return <section aria-labelledby="portal-grant-title"><h3 ref={heading} tabIndex={-1} id="portal-grant-title">Zugang: {access.email}</h3>
    <p>Prüfvermerk: {access.verification}</p>{action.error && <p role="alert">{action.error} <button onClick={reload}>Aktuellen Stand laden</button></p>}
    <label>Begründung für Änderung oder Widerruf<textarea minLength={10} maxLength={2000} value={reason} disabled={action.busy} onChange={event => setReason(event.target.value)} /></label>
    <div className="transfer-actions"><button className="btn btn-secondary" disabled={action.busy || reason.trim().length < 10} onClick={() => change(`${BASE}/grants/${access.id}`, access.revision, !access.active)}>{access.active ? 'Diese Zuordnung widerrufen' : 'Zuordnung nach Prüfung reaktivieren'}</button>
      {fullAccess && <button className="btn btn-secondary" disabled={action.busy || reason.trim().length < 10} onClick={() => change(`${BASE}/grants/${access.id}/identity`, access.identity_revision, !access.identity_active)}>{access.identity_active ? 'Gesamten externen Zugang deaktivieren' : 'Externen Zugang reaktivieren'}</button>}</div>
    <h4>Veröffentlichte Fassungen</h4>{publicationError && <p role="alert">{publicationError}</p>}
    <ul className="transfer-list">{publications?.map(row => <li key={row.id}><strong>{row.title}</strong> · {row.active ? 'Veröffentlicht' : 'Widerrufen'}<p>SHA-256: <code>{row.sha256}</code></p>
      <button className="btn btn-secondary" disabled={action.busy || reason.trim().length < 10} onClick={() => change(`${BASE}/publications/${row.id}`, row.revision, !row.active)}>{row.active ? 'Veröffentlichung widerrufen' : 'Fassung erneut veröffentlichen'}</button></li>)}</ul>
    {access.active && <form className="transfer-grid" onSubmit={async event => {
      event.preventDefault();
      if (await action.perform(`${BASE}/grants/${access.id}/publications`, { grant_revision: access.revision, version_id: version, title, reason: publishReason })) { setVersion(''); setTitle(''); setPublishReason(''); reload(); }
    }}><h4>Weitere archivierte Fassung ausdrücklich veröffentlichen</h4>
      {documentError && <p role="alert">{documentError} <button type="button" onClick={reload}>Neu laden</button></p>}
      <label>Passende Originalfassung<select required disabled={action.busy || !documents} value={version} onChange={event => { setVersion(event.target.value); setTitle(documents.items.find(row => row.id === event.target.value)?.title || ''); }}><option value="">Bitte auswählen</option>{documents?.items.map(row => <option key={row.id} value={row.id}>{row.title} · Fassung {row.number} · {row.filename}</option>)}</select></label>
      {documents && <nav aria-label="Passende Dokumentfassungen"><button type="button" disabled={!skip} onClick={() => { setSkip(Math.max(0, skip - 25)); setVersion(''); }}>Zurück</button><span> {documents.total} passende Fassungen </span><button type="button" disabled={skip + 25 >= documents.total} onClick={() => { setSkip(skip + 25); setVersion(''); }}>Weiter</button></nav>}
      <label>Im Portal sichtbarer Titel<input required maxLength={300} disabled={action.busy} value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label>Grund und Prüfung der Veröffentlichung<textarea required minLength={10} maxLength={2000} disabled={action.busy} value={publishReason} onChange={event => setPublishReason(event.target.value)} /></label>
      <button className="btn btn-primary" disabled={action.busy || !version}>Diese Fassung für diese Partei veröffentlichen</button>
    </form>}
  </section>;
}
