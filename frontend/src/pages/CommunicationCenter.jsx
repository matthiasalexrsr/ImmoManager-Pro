import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useConfirm } from '../components/ConfirmDialog';
import useWriteAccess from '../hooks/useWriteAccess';
import './CommunicationCenter.css';

const EMPTY_EDITOR = {
  title: '', channel: 'email', recipient_type: 'tenant', recipient_id: '',
  contract_id: '', template_id: '', subject_template: '', body_template: '',
  whatsapp_template_name: '', whatsapp_language_code: 'de',
};

const channelLabel = value => ({
  email: 'E-Mail', post: 'Deutsche Post / E-POST', whatsapp: 'WhatsApp',
}[value] || value);

const statusLabel = value => ({
  draft: 'Entwurf', reviewed: 'Freigegeben', queued: 'Übergeben',
  sent: 'Versendet', failed: 'Fehler',
}[value] || value);

function recipientLabel(row) {
  return row?.full_name || row?.company_name
    || [row?.first_name, row?.last_name].filter(Boolean).join(' ')
    || row?.email || row?.id || '—';
}

function errorText(error) {
  if (typeof error?.message === 'string') return error.message;
  return 'Die Aktion konnte nicht abgeschlossen werden.';
}

export default function CommunicationCenter() {
  const confirm = useConfirm();
  const auth = useAuth();
  const { canWrite } = useWriteAccess('/communication-center');
  const libraryCanWrite = ['eigentuemer', 'verwalter'].includes(auth?.user?.role);
  const bodyRef = useRef(null);
  const [tab, setTab] = useState('compose');
  const [catalog, setCatalog] = useState({ variables: [], templates: [], blocks: [], channels: [] });
  const [portfolios, setPortfolios] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [portfolioId, setPortfolioId] = useState('');
  const [drafts, setDrafts] = useState([]);
  const [active, setActive] = useState(null);
  const [editor, setEditor] = useState(EMPTY_EDITOR);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [postTestMode, setPostTestMode] = useState(true);
  const [templateEdit, setTemplateEdit] = useState(null);
  const [blockEdit, setBlockEdit] = useState(null);

  const refreshCatalog = useCallback(async () => {
    const data = await api.get('/communication-center/catalog');
    setCatalog(data || { variables: [], templates: [], blocks: [], channels: [] });
  }, []);

  const refreshDrafts = useCallback(async id => {
    if (!id) { setDrafts([]); return; }
    const rows = await api.get('/communication-center/drafts?portfolio_id=' + encodeURIComponent(id));
    setDrafts(rows || []);
  }, []);

  useEffect(() => {
    let current = true;
    Promise.all([
      api.get('/communication-center/catalog'),
      api.getAll('/portfolios'),
      api.getAll('/tenants'),
      api.getAll('/contacts'),
      api.getAll('/contracts'),
    ]).then(([cat, ps, ts, cs, ctrs]) => {
      if (!current) return;
      setCatalog(cat || {});
      setPortfolios(ps || []);
      setTenants(ts || []);
      setContacts(cs || []);
      setContracts(ctrs || []);
      if (ps?.length) setPortfolioId(ps[0].id);
    }).catch(err => current && setError(errorText(err)))
      .finally(() => current && setLoading(false));
    return () => { current = false; };
  }, []);

  useEffect(() => {
    refreshDrafts(portfolioId).catch(err => setError(errorText(err)));
  }, [portfolioId, refreshDrafts]);

  const recipients = editor.recipient_type === 'tenant' ? tenants : contacts;
  const recipientContracts = useMemo(() => (
    editor.recipient_type === 'tenant' && editor.recipient_id
      ? contracts.filter(row => row.tenant_id === editor.recipient_id)
      : []
  ), [contracts, editor.recipient_type, editor.recipient_id]);
  const availableTemplates = useMemo(() => {
    const audience = editor.recipient_type === 'tenant' ? 'tenant' : 'company';
    return (catalog.templates || []).filter(row => row.is_active
      && (row.audience === 'any' || row.audience === audience)
      && (row.channel === 'universal' || row.channel === editor.channel));
  }, [catalog.templates, editor.channel, editor.recipient_type]);

  const selectDraft = row => {
    setActive(row);
    setEditor({
      title: row.title || '', channel: row.channel || 'email',
      recipient_type: row.recipient_type || 'tenant', recipient_id: row.recipient_id || '',
      contract_id: row.contract_id || '', template_id: row.template_id || '',
      subject_template: row.subject_template || '', body_template: row.body_template || '',
      whatsapp_template_name: row.whatsapp_template_name || '',
      whatsapp_language_code: row.whatsapp_language_code || 'de',
    });
    setPreview(row.rendered_body ? {
      subject: row.rendered_subject, body: row.rendered_body,
      missing_fields: [], warnings: [],
    } : null);
    setNotice('');
    setError('');
  };

  const newDraft = () => {
    setActive(null);
    setEditor(EMPTY_EDITOR);
    setPreview(null);
    setNotice('');
    setError('');
    setTab('compose');
  };

  const changeEditor = (key, value) => {
    setEditor(previous => {
      const next = { ...previous, [key]: value };
      if (key === 'recipient_type') {
        next.recipient_id = '';
        next.contract_id = '';
        next.template_id = '';
      }
      if (key === 'channel') next.template_id = '';
      if (key === 'recipient_id') next.contract_id = '';
      return next;
    });
    if (active?.status === 'draft' || !active) setPreview(null);
  };

  const applyTemplate = id => {
    const template = catalog.templates?.find(row => row.id === id);
    setEditor(previous => ({
      ...previous,
      template_id: id,
      subject_template: template?.subject_template || '',
      body_template: template?.body_template || '',
      channel: template?.channel && template.channel !== 'universal'
        ? template.channel : previous.channel,
    }));
    setPreview(null);
  };

  const insertToken = token => {
    const marker = '{{' + token + '}}';
    const textarea = bodyRef.current;
    if (!textarea) {
      changeEditor('body_template', editor.body_template + marker);
      return;
    }
    const start = textarea.selectionStart ?? editor.body_template.length;
    const end = textarea.selectionEnd ?? start;
    const body = editor.body_template.slice(0, start) + marker + editor.body_template.slice(end);
    changeEditor('body_template', body);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(start + marker.length, start + marker.length);
    });
  };

  const renderPreview = async () => {
    if (!portfolioId || !editor.recipient_id || !editor.body_template.trim()) {
      setError('Portfolio, Empfänger und Dokumentinhalt sind für die Vorschau erforderlich.');
      return null;
    }
    setBusy(true);
    setError('');
    try {
      const data = await api.post(
        '/communication-center/preview?portfolio_id=' + encodeURIComponent(portfolioId),
        {
          recipient_type: editor.recipient_type,
          recipient_id: editor.recipient_id,
          channel: editor.channel,
          contract_id: editor.contract_id || null,
          template_id: editor.template_id || null,
          subject_template: editor.subject_template,
          body_template: editor.body_template,
        },
      );
      setPreview(data);
      return data;
    } catch (err) {
      setError(errorText(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const draftPayload = () => ({
    portfolio_id: portfolioId,
    ...editor,
    contract_id: editor.contract_id || null,
    template_id: editor.template_id || null,
  });

  const saveDraft = async () => {
    if (!canWrite) return null;
    if (!portfolioId || !editor.title.trim() || !editor.recipient_id || !editor.body_template.trim()) {
      setError('Titel, Portfolio, Empfänger und Inhalt sind Pflichtfelder.');
      return null;
    }

    setBusy(true);
    setError('');
    try {
      const saved = active
        ? await api.put('/communication-center/drafts/' + active.id, {
          expected_revision: active.revision,
          ...editor,
          contract_id: editor.contract_id || null,
          template_id: editor.template_id || null,
        })
        : await api.post('/communication-center/drafts', draftPayload());
      setActive(saved);
      setNotice('Entwurf gespeichert.');
      await refreshDrafts(portfolioId);
      return saved;
    } catch (err) {
      setError(errorText(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const reviewDraft = async () => {
    if (!canWrite) return;
    const rendered = await renderPreview();
    if (!rendered || rendered.missing_fields?.length) return;
    const accepted = await confirm(
      'Dokument verbindlich freigeben? Danach sind Inhalt und Daten-Snapshot unveränderlich.'
    );
    if (!accepted) return;
    const saved = await saveDraft();
    if (!saved) return;
    setBusy(true);
    setError('');
    try {
      const reviewed = await api.post('/communication-center/drafts/' + saved.id + '/review', {
        expected_revision: saved.revision,
        confirmed: true,
      });
      setActive(reviewed);
      setPreview({
        subject: reviewed.rendered_subject, body: reviewed.rendered_body,
        missing_fields: [], warnings: [],
      });
      setNotice('Dokument wurde mit Daten-Snapshot und Prüfsummen freigegeben.');
      await refreshDrafts(portfolioId);

    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = async () => {
    if (!active) return;
    setBusy(true);
    setError('');
    try {
      const blob = await api.getBlob('/communication-center/drafts/' + active.id + '/pdf');
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = (active.title || 'korrespondenz') + '.pdf';
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const dispatch = async () => {
    if (!active || active.status !== 'reviewed') return;
    const explanation = active.channel === 'post' && postTestMode
      ? 'E-POST-Testsendung übergeben? Es erfolgt kein physischer Versand.'
      : channelLabel(active.channel) + '-Übergabe verbindlich ausführen?';
    if (!await confirm(explanation)) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.post('/communication-center/drafts/' + active.id + '/dispatch', {
        expected_revision: active.revision,
        confirmed: true,
        action: active.channel,
        test_mode: postTestMode,
      });
      setActive(result.draft);
      setNotice('An Versandkanal übergeben. Annahme ist noch keine Zustellbestätigung.');
      await refreshDrafts(portfolioId);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const refreshPostStatus = async () => {
    if (!active?.id || active.channel !== 'post' || !active.external_reference) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.post(
        '/communication-center/drafts/' + active.id + '/post-status?confirmed=true', {}
      );
      setActive(result.draft);
      setNotice('E-POST-Verarbeitungsstatus aktualisiert.');
      await refreshDrafts(portfolioId);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const installStarterLibrary = async () => {
    if (!libraryCanWrite) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.post('/communication-center/starter-library', {});
      await refreshCatalog();
      setNotice(`Starterbibliothek ergänzt: ${result.templates_added} Vorlagen, ${result.blocks_added} Bausteine.`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const saveTemplate = async event => {
    event.preventDefault();
    if (!libraryCanWrite) return;
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    payload.is_active = true;
    setError('');
    try {
      if (templateEdit?.id) {
        payload.expected_revision = templateEdit.revision;
        await api.put('/communication-center/templates/' + templateEdit.id, payload);
      } else {
        await api.post('/communication-center/templates', payload);
      }
      setTemplateEdit(null);
      await refreshCatalog();
      setNotice('Vorlagenbibliothek aktualisiert.');
    } catch (err) {
      setError(errorText(err));
    }
  };

  const saveBlock = async event => {
    event.preventDefault();
    if (!libraryCanWrite) return;
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    payload.is_active = true;
    setError('');
    try {
      if (blockEdit?.id) {
        payload.expected_revision = blockEdit.revision;
        await api.put('/communication-center/blocks/' + blockEdit.id, payload);
      } else {
        await api.post('/communication-center/blocks', payload);
      }
      setBlockEdit(null);
      await refreshCatalog();
      setNotice('Bausteinbibliothek aktualisiert.');
    } catch (err) {
      setError(errorText(err));
    }
  };

  if (loading) {
    return <div className="page-loading">Kommunikationszentrum wird geladen…</div>;
  }

  return <div className="page communication-center">
    <header className="communication-header">
      <div>
        <span className="communication-eyebrow">Korrespondenz · geprüft · nachvollziehbar</span>
        <h1>Kommunikationszentrum</h1>
        <p>Schreiben und Nachrichten mit verlässlichen Stammdaten erstellen, freigeben und über definierte Kanäle übergeben.</p>
      </div>
      <div className="communication-header-actions">
        <select aria-label="Portfolio" value={portfolioId}
          onChange={event => {
            setPortfolioId(event.target.value);
            setActive(null);
            setEditor(EMPTY_EDITOR);
            setPreview(null);
            setNotice('');
            setError('');
          }}>
          {portfolios.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select>
        {canWrite && <button className="btn btn-primary" onClick={newDraft}>+ Neue Korrespondenz</button>}
      </div>
    </header>

    {error && <div role="alert" className="alert alert-error communication-alert">
      <span>{error}</span><button type="button" onClick={() => setError('')}>×</button>
    </div>}
    {notice && <div role="status" className="alert alert-success communication-alert">{notice}</div>}

    <nav className="communication-tabs" aria-label="Bereiche">
      {[['compose', 'Korrespondenz'], ['templates', 'Vorlagen'], ['blocks', 'Bausteine']].map(([id, label]) =>
        <button type="button" key={id} className={tab === id ? 'active' : ''}
          onClick={() => setTab(id)}>{label}</button>)}
    </nav>

    {tab === 'compose' && <div className="communication-workbench">
      <aside className="communication-drafts" aria-label="Korrespondenzen">
        <div className="communication-panel-heading">
          <div><span>Arbeitsmappe</span><strong>{drafts.length} Vorgänge</strong></div>
        </div>
        <div className="communication-draft-list">
          {drafts.length === 0 &&
            <p className="communication-empty">Noch keine Korrespondenz in diesem Portfolio.</p>}
          {drafts.map(row => <button key={row.id} type="button"
            className={'communication-draft-card ' + (active?.id === row.id ? 'active' : '')}
            onClick={() => selectDraft(row)}>
            <span className="communication-draft-title">{row.title}</span>
            <span className="communication-draft-meta">
              {channelLabel(row.channel)} · {statusLabel(row.status)}
            </span>
            <span className="communication-draft-time">
              {row.updated_at?.slice(0, 16).replace('T', ' ')}
            </span>
          </button>)}
        </div>
      </aside>

      <section className="communication-editor" aria-label="Editor">
        <div className="communication-panel-heading">
          <div><span>Editor</span><strong>{active ? 'Revision ' + active.revision : 'Neuer Entwurf'}</strong></div>
          {active?.status &&
            <span className={'communication-status status-' + active.status}>{statusLabel(active.status)}</span>}
        </div>

        <fieldset disabled={!canWrite || (active && active.status !== 'draft')}
          className="communication-form">
          <div className="communication-grid-two">
            <label>Titel
              <input value={editor.title}
                onChange={e => changeEditor('title', e.target.value)}
                placeholder="z. B. Mietanpassung Oktober" />
            </label>
            <label>Versandkanal
              <select value={editor.channel}
                onChange={e => changeEditor('channel', e.target.value)}>
                <option value="email">E-Mail</option>
                <option value="post">Deutsche Post / E-POST</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </label>
          </div>
          <div className="communication-grid-two">
            <label>Empfängerart
              <select value={editor.recipient_type}
                onChange={e => changeEditor('recipient_type', e.target.value)}>
                <option value="tenant">Mietpartei</option>
                <option value="contact">Unternehmen / Kontakt</option>
              </select>
            </label>
            <label>Empfänger
              <select value={editor.recipient_id}
                onChange={e => changeEditor('recipient_id', e.target.value)}>
                <option value="">Bitte auswählen</option>
                {recipients.map(row =>
                  <option key={row.id} value={row.id}>{recipientLabel(row)}</option>)}
              </select>
            </label>
          </div>

          {editor.recipient_type === 'tenant' && <label>Vertrag
            <select value={editor.contract_id}
              onChange={e => changeEditor('contract_id', e.target.value)}>
              <option value="">Automatisch, wenn eindeutig</option>
              {recipientContracts.map(row =>
                <option key={row.id} value={row.id}>{row.contract_number}</option>)}
            </select>
          </label>}
          <label>Vorlage
            <select value={editor.template_id} onChange={e => applyTemplate(e.target.value)}>
              <option value="">Freier Entwurf</option>
              {availableTemplates.map(row =>
                <option key={row.id} value={row.id}>{row.name} · {row.category}</option>)}
            </select>
          </label>
          <label>Betreff
            <input value={editor.subject_template}
              onChange={e => changeEditor('subject_template', e.target.value)}
              placeholder="Platzhalter wie {{contract.number}} sind erlaubt" />
          </label>
          <label>Dokumentinhalt
            <textarea ref={bodyRef} rows={15} value={editor.body_template}
              onChange={e => changeEditor('body_template', e.target.value)}
              placeholder={'Sehr geehrte/r {{recipient.name}},\n\n…'} />
          </label>
          {editor.channel === 'whatsapp' && <div className="communication-grid-two">
            <label>Meta Template-Name
              <input required value={editor.whatsapp_template_name}
                onChange={e => changeEditor('whatsapp_template_name', e.target.value)}
                placeholder="z. B. rent_notice" pattern="[a-z0-9_]+" />
              <small>Für proaktive Nachrichten wird ausschließlich ein freigegebenes Meta-Template versendet.</small>
            </label>
            <label>Sprache
              <input value={editor.whatsapp_language_code}
                onChange={e => changeEditor('whatsapp_language_code', e.target.value)} />
            </label>
          </div>}
        </fieldset>

        <div className="communication-token-box">
          <span>Felder einfügen</span>
          <div>{(catalog.variables || []).map(variable =>
            <button type="button" key={variable.key}
              onClick={() => insertToken(variable.key)}
              title={variable.label}>{variable.label}</button>)}</div>
          <span>Bausteine</span>
          <div>{(catalog.blocks || []).filter(row => row.is_active).map(block =>
            <button type="button" key={block.id}
              onClick={() => insertToken('block:' + block.key)}>{block.name}</button>)}</div>
        </div>
        <div className="communication-actions">
          {canWrite && (!active || active.status === 'draft') && <>
            <button className="btn btn-secondary" disabled={busy}
              onClick={saveDraft}>Entwurf speichern</button>
            <button className="btn btn-secondary" disabled={busy}
              onClick={renderPreview}>Vorschau prüfen</button>
            <button className="btn btn-primary" disabled={busy}
              onClick={reviewDraft}>Verbindlich freigeben</button>
          </>}
          {active?.status !== 'draft' && active &&
            <button className="btn btn-secondary" disabled={busy}
              onClick={downloadPdf}>PDF herunterladen</button>}
        </div>
      </section>

      <aside className="communication-preview" aria-label="Dokumentvorschau">
        <div className="communication-panel-heading">
          <div><span>Prüfansicht</span><strong>Daten & Ausgabe</strong></div>
        </div>
        {preview ? <>
          {preview.missing_fields?.length > 0 && <div className="communication-missing">
            <strong>Freigabe blockiert</strong>
            <span>Fehlende Daten: {preview.missing_fields.join(', ')}</span>
          </div>}
          {preview.warnings?.map(warning =>
            <div className="communication-warning" key={warning}>{warning}</div>)}
          <article className="communication-paper">
            <div className="paper-brand">
              {portfolios.find(row => row.id === portfolioId)?.name || 'ImmoManager Pro'}
            </div>
            <div className="paper-recipient">
              {recipientLabel(recipients.find(row => row.id === editor.recipient_id))}
            </div>
            <div className="paper-subject">{preview.subject}</div>
            <div className="paper-body">{preview.body}</div>
          </article>
        </> : <div className="communication-preview-placeholder">
          <strong>Noch keine geprüfte Vorschau</strong>
          <p>Die Vorschau wird serverseitig mit den aktuellen Stammdaten aufgelöst.
            Fehlende Werte werden vor der Freigabe blockiert.</p>
          <button className="btn btn-secondary" disabled={busy}
            onClick={renderPreview}>Vorschau erzeugen</button>
        </div>}

        {active?.status === 'reviewed' && <div className="communication-dispatch">
          <h3>Versand</h3>
          <p>Freigabe-Snapshot <code>{active.snapshot_sha256?.slice(0, 12)}…</code></p>
          {active.channel === 'post' && <>
            <label className="communication-checkbox">
              <input type="checkbox" checked={postTestMode}
                onChange={e => setPostTestMode(e.target.checked)} />
              E-POST-Testmodus (kein physischer Versand)
            </label>
            {!postTestMode && <div className="communication-missing">
              <strong>Produktivversand blockiert</strong>
              <span>Für den erzeugten Brief liegt noch kein PDF/A-1b-Prüfnachweis vor.</span>
            </div>}
          </>}
          <button className="btn btn-primary"
            disabled={busy || (active.channel === 'post' && !postTestMode)}
            onClick={dispatch}>{channelLabel(active.channel)} übergeben</button>
          <small>„Übergeben“ bedeutet nicht „zugestellt“. Zustell- und Verarbeitungsstatus
            werden separat geführt.</small>
        </div>}
        {active?.status === 'queued' && <div className="communication-dispatch">
          <h3>Übergeben</h3>
          <p>Externe Referenz: <code>{active.external_reference || '—'}</code></p>
          <p>Status: {active.external_status || 'angenommen'}</p>
          {active.channel === 'post' && active.external_reference &&
            <button type="button" className="btn btn-secondary" disabled={busy}
              onClick={refreshPostStatus}>E-POST-Status aktualisieren</button>}
          {active.channel === 'email' &&
            <Link className="btn btn-secondary" to="/outbox">SMTP-Ausgang und Versandjournal öffnen</Link>}
          {active.channel === 'whatsapp' &&
            <small>Die API-Annahme ist keine Zustell- oder Lesebestätigung. Webhook-Status ist separat anzubinden.</small>}
        </div>}
      </aside>
    </div>}

    {tab === 'templates' && <section className="communication-library">
      <div className="communication-library-list">
        <div className="communication-panel-heading">
          <div><span>Bibliothek</span><strong>Vorlagen</strong></div>
          {libraryCanWrite && <div className="communication-library-actions">
            <button className="btn btn-secondary btn-sm" type="button" disabled={busy}
              onClick={installStarterLibrary}>Starterbibliothek ergänzen</button>
            <button className="btn btn-primary btn-sm" type="button"
              onClick={() => setTemplateEdit({})}>+ Vorlage</button>
          </div>}
        </div>
        {(catalog.templates || []).map(row =>
          <button type="button" key={row.id} onClick={() => setTemplateEdit(row)}
            className="library-card">
            <strong>{row.name}</strong>
            <span>{row.category} · {row.audience} · {row.channel}</span>
            <small>Revision {row.revision} · {row.locale}</small>
          </button>)}
      </div>
      <form className="communication-library-editor" onSubmit={saveTemplate}>
        <h2>{templateEdit?.id ? 'Vorlage bearbeiten' : 'Neue Vorlage'}</h2>
        {!templateEdit ? <p>Vorlage auswählen oder neu anlegen.</p> : <>
          <label>Name<input name="name" defaultValue={templateEdit.name || ''} required /></label>
          <div className="communication-grid-two">
            <label>Kategorie
              <input name="category" defaultValue={templateEdit.category || 'general'} required />
            </label>
            <label>Sprache
              <input name="locale" defaultValue={templateEdit.locale || 'de-DE'} required />
            </label>
          </div>

          <div className="communication-grid-two">
            <label>Zielgruppe
              <select name="audience" defaultValue={templateEdit.audience || 'any'}>
                <option value="any">Alle</option>
                <option value="tenant">Mietparteien</option>
                <option value="company">Unternehmen</option>
              </select>
            </label>
            <label>Kanal
              <select name="channel" defaultValue={templateEdit.channel || 'universal'}>
                <option value="universal">Universal</option>
                <option value="email">E-Mail</option>
                <option value="post">Post</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </label>
          </div>
          <label>Betreff
            <input name="subject_template" defaultValue={templateEdit.subject_template || ''} />
          </label>
          <label>Inhalt
            <textarea name="body_template" rows={14}
              defaultValue={templateEdit.body_template || ''} required />
          </label>
          <label>Tags<input name="tags" defaultValue={templateEdit.tags || ''} /></label>
          {libraryCanWrite
            ? <button className="btn btn-primary" type="submit">Vorlage speichern</button>
            : <p className="text-muted">Nur Eigentümer oder Verwalter können die globale Bibliothek ändern.</p>}
        </>}
      </form>
    </section>}

    {tab === 'blocks' && <section className="communication-library">
      <div className="communication-library-list">
        <div className="communication-panel-heading">
          <div><span>Bibliothek</span><strong>Bausteine</strong></div>
          {libraryCanWrite && <div className="communication-library-actions">
            <button className="btn btn-secondary btn-sm" type="button" disabled={busy}
              onClick={installStarterLibrary}>Starterbibliothek ergänzen</button>
            <button className="btn btn-primary btn-sm" type="button"
              onClick={() => setBlockEdit({})}>+ Baustein</button>
          </div>}
        </div>
        {(catalog.blocks || []).map(row =>
          <button type="button" key={row.id} onClick={() => setBlockEdit(row)}
            className="library-card">
            <strong>{row.name}</strong>
            <span><code>{'{{block:' + row.key + '}}'}</code></span>
            <small>{row.category} · Revision {row.revision}</small>
          </button>)}
      </div>
      <form className="communication-library-editor" onSubmit={saveBlock}>
        <h2>{blockEdit?.id ? 'Baustein bearbeiten' : 'Neuer Baustein'}</h2>
        {!blockEdit ? <p>Baustein auswählen oder neu anlegen.</p> : <>
          <div className="communication-grid-two">
            <label>Name<input name="name" defaultValue={blockEdit.name || ''} required /></label>
            <label>Schlüssel
              <input name="key" defaultValue={blockEdit.key || ''}
                placeholder="closing.standard" required />
            </label>
          </div>

          <div className="communication-grid-two">
            <label>Kategorie
              <input name="category" defaultValue={blockEdit.category || 'general'} required />
            </label>
            <label>Sprache
              <input name="locale" defaultValue={blockEdit.locale || 'de-DE'} required />
            </label>
          </div>
          <label>Inhalt
            <textarea name="content_template" rows={12}
              defaultValue={blockEdit.content_template || ''} required />
          </label>
          <label>Tags<input name="tags" defaultValue={blockEdit.tags || ''} /></label>
          {libraryCanWrite
            ? <button className="btn btn-primary" type="submit">Baustein speichern</button>
            : <p className="text-muted">Nur Eigentümer oder Verwalter können die globale Bibliothek ändern.</p>}
        </>}
      </form>
    </section>}
  </div>;
}
