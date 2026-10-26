import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { downloadPortal, formCommand, portalRequest } from './client';
import './portal.css';

const PortalAuthContext = createContext(null);
const statusLabels = { open: 'Gemeldet', in_progress: 'In Bearbeitung', completed: 'Abgeschlossen', cancelled: 'Abgebrochen' };

function usePage(path, refresh) {
  const [page, setPage] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setError(''); setPage(null);
    portalRequest(path, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setPage(value); })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [path, refresh]);
  return [page, error];
}

function Pagination({ page, onSkip, label }) {
  return <nav aria-label={label} className="portal-actions"><button disabled={page.skip === 0} onClick={() => onSkip(Math.max(0, page.skip - page.limit))}>Zurück</button>
    <span>{page.total} Einträge</span><button disabled={page.skip + page.limit >= page.total} onClick={() => onSkip(page.skip + page.limit)}>Weiter</button></nav>;
}

export default function PortalApp() {
  const [invitation, setInvitation] = useState(() => window.location.pathname === '/portal/accept' ? window.location.hash.slice(1) : '');
  const [profile, setProfile] = useState(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0), [tab, setTab] = useState('documents');
  const title = useRef(null);
  useEffect(() => {
    if (invitation) window.history.replaceState(null, '', '/portal/accept');
    const controller = new AbortController();
    const lost = () => { setProfile(null); setLoading(false); setError('Die Portalsitzung ist abgelaufen oder wurde widerrufen. Bitte erneut anmelden.'); };
    window.addEventListener('portal-session-lost', lost);
    if (invitation) setLoading(false);
    else portalRequest('/me', { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setProfile(value); })
      .catch(failure => { if (!controller.signal.aborted && failure.status !== 401) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); window.removeEventListener('portal-session-lost', lost); };
  }, [attempt, invitation]);
  useEffect(() => { title.current?.focus(); }, [tab, profile?.email]);
  const signedIn = async () => { window.history.replaceState(null, '', '/portal'); setError(''); setProfile(await portalRequest('/me')); setInvitation(''); };
  return <div className="portal-shell"><a className="portal-skip" href="#portal-main">Zum Inhalt</a>
    <header className="portal-header"><strong>ImmoManager · Mein Portal</strong>{profile && <span>{profile.email}</span>}</header>
    <main id="portal-main"><h1 ref={title} tabIndex={-1}>{profile ? 'Meine Unterlagen und Anliegen' : 'Willkommen im Portal'}</h1>
      {error && <p role="alert" className="portal-error">{error} <button onClick={() => { setError(''); setAttempt(value => value + 1); }}>Erneut prüfen</button></p>}
      {loading ? <p role="status">Anmeldung wird geprüft …</p> : !profile ? <SignIn invitation={invitation} onSignedIn={signedIn} /> : <PortalAuthContext.Provider value={profile}>
        <div className="portal-actions"><button onClick={async () => { try { await portalRequest('/logout', { method: 'POST' }); setProfile(null); } catch (failure) { setError(failure.message); } }}>Abmelden</button>
          <button onClick={async () => { try { await downloadPortal('/me/export', 'Meine-Portalunterlagen.zip'); } catch (failure) { setError(failure.message); } }}>Eigene Unterlagen exportieren</button></div>
        {!profile.grants.length && <p role="status">Derzeit ist keine aktive Zuordnung vorhanden. Bitte wenden Sie sich an Ihre Verwaltung.</p>}
        <nav aria-label="Portalbereiche" className="portal-tabs">{[['documents', 'Dokumente'], ['cases', 'Meine Anliegen'], ['report', 'Schaden melden']].map(([name, label]) =>
          <button key={name} aria-current={tab === name ? 'page' : undefined} onClick={() => setTab(name)}>{label}</button>)}</nav>
        <section key={profile.email + ':' + tab}>{tab === 'documents' ? <PortalDocuments /> : tab === 'cases' ? <PortalCases /> : <DamageForm onReported={() => setTab('cases')} />}</section>
      </PortalAuthContext.Provider>}
    </main><footer>Nur ausdrücklich freigegebene Unterlagen und eigene Anliegen sind sichtbar. Bei akuter Gefahr wenden Sie sich unmittelbar an die zuständige Notfallstelle.</footer>
  </div>;
}

function SignIn({ invitation, onSignedIn }) {
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  return <form className="portal-card" onSubmit={async event => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('');
    try { await portalRequest(invitation ? '/accept' : '/login', { method: 'POST', body: invitation ? { token: invitation, password } : { email, password } }); setPassword(''); await onSignedIn(); }
    catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }}>
    <h2>{invitation ? 'Einladung annehmen' : 'Anmelden'}</h2>
    <p>{invitation ? 'Für Ihren neuen Zugang legen Sie ein Passwort mit mindestens zwölf Zeichen fest. Falls Sie bereits ein Portalpasswort haben, verwenden Sie dieses.' : 'Der Zugang wird von Ihrer Verwaltung persönlich eingeladen. Verwenden Sie Ihre Portal-Anmeldedaten.'}</p>
    {error && <p className="portal-error" role="alert">{error}</p>}
    {!invitation && <label>E-Mail-Adresse<input type="email" required autoComplete="username" maxLength={254} disabled={busy} value={email} onChange={event => setEmail(event.target.value)} /></label>}
    <label>Passwort<input type="password" required minLength={invitation ? 12 : 1} maxLength={128} autoComplete={invitation ? 'new-password' : 'current-password'} disabled={busy} value={password} onChange={event => setPassword(event.target.value)} /></label>
    <button disabled={busy}>{busy ? 'Wird geprüft …' : invitation ? 'Einladung annehmen' : 'Am Portal anmelden'}</button>
  </form>;
}

function PortalDocuments() {
  const [search, setSearch] = useState(''), [query, setQuery] = useState(''), [skip, setSkip] = useState(0), [refresh, setRefresh] = useState(0), [error, setError] = useState('');
  const [page, failure] = usePage(`/me/documents?search=${encodeURIComponent(query)}&skip=${skip}&limit=25`, refresh);
  return <><h2>Meine veröffentlichten Dokumente</h2><form className="portal-actions" onSubmit={event => { event.preventDefault(); setQuery(search); setSkip(0); }}>
    <label>Dokumenttitel suchen<input type="search" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} /></label><button>Suchen</button></form>
    {(error || failure) && <p role="alert" className="portal-error">{error || failure} <button onClick={() => { setError(''); setRefresh(value => value + 1); }}>Neu laden</button></p>}
    {!page ? <p role="status">Dokumente werden geladen …</p> : <><ul className="portal-list">{page.items.map(row => <li key={row.id} className="portal-card"><h3>{row.title}</h3><p>Veröffentlichte Fassung {row.version} · {row.filename}</p>
      <div className="portal-actions"><a target="_blank" rel="noopener noreferrer" href={`/api/v1/portal/me/documents/${encodeURIComponent(row.id)}/preview`}>Vorschau öffnen</a>
        <button onClick={async () => { try { await downloadPortal(`/me/documents/${row.id}/download`, row.filename); } catch (err) { setError(err.message); } }}>Herunterladen</button></div>
    </li>)}</ul>{!page.items.length && <p>Keine freigegebenen Dokumente für diese Suche vorhanden.</p>}<Pagination page={page} onSkip={setSkip} label="Dokumentseiten" /></>}
  </>;
}

function PortalCases() {
  const [selected, setSelected] = useState(null), [skip, setSkip] = useState(0), [refresh, setRefresh] = useState(0);
  const [page, error] = usePage(`/me/cases?skip=${skip}&limit=25`, refresh);
  if (selected) return <Conversation identifier={selected} onBack={() => { setSelected(null); setRefresh(value => value + 1); }} />;
  return <><h2>Meine Anliegen</h2>{error && <p role="alert">{error} <button onClick={() => setRefresh(value => value + 1)}>Neu laden</button></p>}
    {!page ? <p role="status">Anliegen werden geladen …</p> : <><ul className="portal-list">{page.items.map(row => <li key={row.id} className="portal-card"><h3>{row.title}</h3><p>{statusLabels[row.status] || row.status}</p>
      <button onClick={() => setSelected(row.id)}>Verlauf und Rückfragen öffnen</button></li>)}</ul>{!page.items.length && <p>Noch keine Anliegen vorhanden.</p>}<Pagination page={page} onSkip={setSkip} label="Vorgangsseiten" /></>}
  </>;
}

function Conversation({ identifier, onBack }) {
  const [skip, setSkip] = useState(0), [refresh, setRefresh] = useState(0), [error, setError] = useState(''), [busy, setBusy] = useState(false), [body, setBody] = useState(''), [files, setFiles] = useState([]);
  const [page, failure] = usePage(`/me/cases/${identifier}?skip=${skip}&limit=50`, refresh);
  const command = useRef(crypto.randomUUID()), heading = useRef(null), fileInput = useRef(null);
  useEffect(() => { if (page) heading.current?.focus(); }, [page?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const change = () => { command.current = crypto.randomUUID(); };
  return <><button onClick={onBack}>Zurück zu meinen Anliegen</button>{(error || failure) && <p role="alert">{error || failure} <button onClick={() => { setError(''); change(); setRefresh(value => value + 1); }}>Verlauf neu laden</button></p>}
    {!page ? <p role="status">Verlauf wird geladen …</p> : <><h2 ref={heading} tabIndex={-1}>{page.title}</h2><p>{statusLabels[page.status] || page.status}</p>
      <ol className="portal-list">{page.messages.map(message => <li key={message.id} className="portal-card"><strong>{message.sender_kind === 'external' ? 'Ihre Nachricht' : 'Ihre Verwaltung'}</strong>
        <p className="portal-text">{message.body}</p>{message.attachments.map(image => <a key={image.id} href={`/api/v1/portal/me/attachments/${image.id}`} target="_blank" rel="noopener noreferrer">{image.filename} öffnen</a>)}
      </li>)}</ol><Pagination page={page} onSkip={setSkip} label="Nachrichtenseiten" />
      <form className="portal-card" onSubmit={async event => {
        event.preventDefault(); if (busy) return; setBusy(true); setError('');
        try { await portalRequest(`/me/cases/${identifier}/messages`, { method: 'POST', body: formCommand({ expected_revision: page.revision, idempotency_key: command.current, body }, files) });
          setBody(''); setFiles([]); if (fileInput.current) fileInput.current.value = ''; change(); setRefresh(value => value + 1); }
        catch (err) { setError(err.message); } finally { setBusy(false); }
      }}><h3>Nachricht ergänzen</h3><label>Ihre Nachricht<textarea required maxLength={10000} disabled={busy} value={body} onChange={event => { setBody(event.target.value); change(); }} /></label>
        <label>Bilder ergänzen (höchstens fünf)<input ref={fileInput} type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => { setFiles(Array.from(event.target.files || [])); change(); }} /></label>
        <button disabled={busy || !body.trim() || files.length > 5}>{busy ? 'Wird gesendet …' : 'An die Verwaltung senden'}</button></form>
    </>}
  </>;
}

function DamageForm({ onReported }) {
  const profile = useContext(PortalAuthContext);
  const [grantId, setGrantId] = useState(profile.grants.length === 1 ? profile.grants[0].id : '');
  const [title, setTitle] = useState(''), [body, setBody] = useState(''), [files, setFiles] = useState([]), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const command = useRef(crypto.randomUUID());
  const changed = () => { command.current = crypto.randomUUID(); };
  return <form className="portal-card" onSubmit={async event => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('');
    try { const grant = profile.grants.find(row => row.id === grantId);
      await portalRequest('/me/cases', { method: 'POST', body: formCommand({ grant_id: grantId, expected_revision: grant.revision, idempotency_key: command.current, title, body }, files) });
      onReported();
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }}><h2>Schaden melden</h2>{error && <p role="alert" className="portal-error">{error}</p>}
    <label>Zuordnung<select required disabled={busy} value={grantId} onChange={event => { setGrantId(event.target.value); changed(); }}><option value="">Bitte auswählen</option>
      {profile.grants.map(row => <option key={row.id} value={row.id}>{row.property}{row.unit ? ` · ${row.unit}` : ' · Eigentum'}</option>)}</select></label>
    <label>Kurzer Titel<input required minLength={3} maxLength={200} disabled={busy} value={title} onChange={event => { setTitle(event.target.value); changed(); }} /></label>
    <label>Was ist passiert?<textarea required minLength={10} maxLength={10000} disabled={busy} value={body} onChange={event => { setBody(event.target.value); changed(); }} /></label>
    <label>Bilder (JPEG, PNG oder WebP; bis fünf, je 8 MiB, zusammen 20 MiB)<input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => { setFiles(Array.from(event.target.files || [])); changed(); }} /></label>
    <button disabled={busy || !grantId || files.length > 5}>{busy ? 'Wird übermittelt …' : 'Schaden verbindlich melden'}</button>
  </form>;
}
