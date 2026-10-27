import { useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, Plus, Search, LockKeyhole, Send, Paperclip, PanelLeft, UserRound, Square, FileText, ChartNoAxesCombined, FolderSearch, RefreshCw } from 'lucide-react';
import { formatBytes, formatDateTime } from '../../utils/format';
import { useCanWrite } from '../../contexts/AuthContext';
import useAssistantWorkspace from './useAssistantWorkspace';
import { activeRun, runText } from './assistantApi';
import AssistantAttachment from './AssistantAttachment';
import AssistantContext from './AssistantContext';
import { contextHref } from './assistantLinks';
import AssistantProposals from './AssistantProposals';
import AssistantMessageContent from './AssistantMessageContent';
import { FinancialProof } from './AssistantReportSelection';
import AssistantAccounts from './AssistantAccounts';
import AssistantActivity from './AssistantActivity';
import AssistantWorkflows from './AssistantWorkflows';
import AssistantFindings from './AssistantFindings';
import './assistant.css';

const runLabels = { queued: 'Auftrag gespeichert · wartet auf Verarbeitung', running: 'Antwort wird erstellt', completed: 'Abgeschlossen', failed: 'Analyse fehlgeschlagen',
  cancelled: 'Abgebrochen', unknown: 'Ergebnis unbestätigt', blocked: 'Dieser Auftrag kann derzeit nicht verarbeitet werden' };
const connectionLabels = { disconnected: 'Nicht verbunden', connecting: 'Anmeldung läuft', connected: 'Verbunden', unavailable: 'Einrichtung erforderlich', error: 'Verbindung prüfen' };

function Sources({ sources = [], attachments = [] }) {
  const linked = sources.filter(source => contextHref(source));
  const files = sources.filter(source => source.kind === 'attachment');
  return linked.length || files.length ? <details className="assistant-source-list"><summary>Quellen ({linked.length + files.length})</summary><div className="assistant-sources">{linked.map(source => <details key={`${source.kind}:${source.id}`}><summary>{source.title || 'Quelle'}</summary><Link to={contextHref(source)}>Originalakte öffnen →</Link><details><summary>Nachweisdetails</summary><small>Stand {source.revision || 'Nicht übermittelt'}</small>{source.sha256 && <small>SHA-256 {source.sha256}</small>}</details></details>)}{files.map(source => <AssistantAttachment key={source.id} attachment={attachments.find(item => item.id === source.id) || { id: source.id, name: source.title || 'Chatdatei', byte_length: 0 }} />)}</div></details> : null;
}

function ChatManagement({ record, disabled, onEdit }) {
  const [title, setTitle] = useState(record.title);
  return <details className="assistant-chat-management"><summary>Chat verwalten</summary><form onSubmit={event => { event.preventDefault(); if (title.trim()) onEdit({ title: title.trim() }); }}><label>Chattitel<input aria-label="Chattitel" value={title} maxLength={200} disabled={disabled} onChange={event => setTitle(event.target.value)} /></label><button className="btn btn-sm btn-secondary" type="submit" disabled={disabled || !title.trim() || title.trim() === record.title}>Titel speichern</button></form><button type="button" className="btn btn-sm btn-secondary" disabled={disabled} onClick={() => onEdit({ archived: !record.archived })}>{record.archived ? 'Aus Archiv zurückholen' : 'Chat archivieren'}</button></details>;
}

export default function AssistantWorkspace({ owner }) {
  const state = useAssistantWorkspace(owner);
  const canTask = useCanWrite('/tasks');
  const [filter, setFilter] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [accountsOpen, setAccountsOpen] = useState(false);
  const input = useRef(null), composer = useRef(null), transcript = useRef(null);
  const scroll = useRef({ conversation: null, follow: true, older: null });
  const capability = state.capabilities?.providers.find(provider => provider.id === state.provider);
  const local = state.provider === 'local';
  const models = state.connection?.models || capability?.models || [];
  const providerReady = Boolean(capability?.available && state.connection?.connected);
  const onboarding = !local && !providerReady && Boolean(state.capabilities);
  const sending = activeRun(state.run);
  const locked = state.loading || state.busy || Boolean(state.pending) || Boolean(state.editPending) || Boolean(state.record?.archived) || Boolean(state.selectedId && !state.record);
  const chats = state.conversations.filter(chat => Boolean(chat.archived) === showArchived && chat.title.toLocaleLowerCase().includes(filter.toLocaleLowerCase()))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  const response = runText(state.run);
  const displayedRun = state.run && response && !state.messages.some(message => message.run_id === state.run.id && message.role === 'assistant');
  const dataScope = state.draft.data_scope || 'authorized';
  const workingIds = [...new Set([...(state.record?.attachment_ids || state.run?.effective_attachment_ids || []), ...state.draft.attachments.map(item => item.id)])].filter(id => !(state.draft.excluded_attachment_ids || []).includes(id));
  const workingFiles = workingIds.map(id => state.draft.attachments.find(item => item.id === id) || state.attachments.find(item => item.id === id) || { id, name: 'Datei aus diesem Chat', byte_length: 0 });
  const removeFile = id => state.changeDraft(previous => ({ ...previous, attachments: previous.attachments.filter(item => item.id !== id), excluded_attachment_ids: [...new Set([...(previous.excluded_attachment_ids || []), id])] }));
  const selectFile = attachment => state.changeDraft(previous => ({ ...previous, attachments: [...previous.attachments.filter(item => item.id !== attachment.id), attachment], excluded_attachment_ids: (previous.excluded_attachment_ids || []).filter(id => id !== attachment.id) }));
  const canSubmit = !locked && !sending && providerReady && (Boolean(state.draft.body.trim()) || local && Boolean(workingFiles.length || dataScope !== 'none' && state.draft.context.length));
  const setBody = body => state.changeDraft(previous => ({ ...previous, body }));
  const addRequest = text => {
    const next = state.draft.body.trim() ? `${state.draft.body}\n\n${text}` : text;
    if (next.length > (state.capabilities?.max_message_length || 32000)) {
      state.setError('Der ergänzte Auftrag ist zu lang. Bitte die vorhandene Eingabe kürzen; sie bleibt unverändert erhalten.');
      return;
    }
    state.changeDraft(previous => ({ ...previous, body: next }));
    composer.current?.focus();
  };
  const discuss = finding => addRequest(`Untersuche diesen Prüfhinweis genauer: ${finding.message}\nQuellen: ${(finding.evidence || []).map(source => `${source.kind}:${source.id}`).join(', ')}. Lies den aktuellen Stand und die erforderlichen Bezüge nach. Erkläre belegte Ursachen, offene Fragen und konkrete nächste Schritte. Prüfe vor neuen Aufgaben vorhandene passende Aufgaben.`);
  const choose = id => { state.navigate(id); setSidebarOpen(false); };
  useLayoutEffect(() => {
    const element = transcript.current; if (!element) return;
    const memory = scroll.current;
    if (memory.conversation !== state.selectedId) { memory.conversation = state.selectedId; memory.follow = true; memory.older = null; }
    if (memory.older && state.messages[0]?.id !== memory.older.first) {
      element.scrollTop = memory.older.top + element.scrollHeight - memory.older.height;
      memory.older = null; memory.follow = false;
    } else if (memory.follow && !memory.older) element.scrollTop = element.scrollHeight;
    if (memory.older && !state.busy) memory.older = null;
  }, [state.messages, response, state.selectedId, state.busy]);
  const moreMessages = () => {
    const element = transcript.current; const memory = scroll.current;
    if (element) memory.older = { top: element.scrollTop, height: element.scrollHeight, first: state.messages[0]?.id };
    state.moreMessages();
  };
  const upload = files => { if (!locked && files.length) state.upload(Array.from(files)); };

  return <div className="page assistant-page">
    <header className="assistant-heading"><div className="assistant-heading-title"><span className="assistant-symbol"><Sparkles size={23} aria-hidden="true" /></span><div><h1>KI-Assistent</h1><p>Akten verstehen. Zusammenhänge erkennen. Entwürfe vorbereiten.</p></div></div>
      <Link className="btn btn-secondary" to="/reports"><ChartNoAxesCombined size={16} /> Lokale Auswertungen</Link>
    </header>
    <div className="assistant-layout">
      <aside className={`assistant-sidebar ${sidebarOpen ? 'open' : ''}`} aria-label="Persönliche Chats" id="assistant-chat-list">
        <button type="button" className="btn btn-primary" onClick={() => { setShowArchived(false); choose(''); composer.current?.focus(); }}><Plus size={17} /> Neuer Chat</button>
        <div className="assistant-search"><Search size={15} aria-hidden="true" /><input aria-label="Chats durchsuchen" placeholder="Chats durchsuchen" value={filter} onChange={event => setFilter(event.target.value)} /></div>
        <p className="assistant-sidebar-label">Ihre Unterhaltungen</p>
        <button type="button" className="btn btn-sm btn-secondary" aria-pressed={showArchived} onClick={() => setShowArchived(value => !value)}>{showArchived ? 'Aktive Chats anzeigen' : 'Archiv anzeigen'}</button>
        <ul className="assistant-chat-list">{chats.map(chat => <li key={chat.id}><button type="button" aria-label={`Chat öffnen: ${chat.title || 'Neue Unterhaltung'}`} aria-current={state.selectedId === chat.id ? 'true' : undefined} onClick={() => choose(chat.id)}>
          <strong>{chat.title || 'Neue Unterhaltung'}</strong><small>{state.capabilities?.providers.find(provider => provider.id === chat.provider)?.label || chat.provider} · {formatDateTime(chat.updated_at)}</small>
        </button></li>)}</ul>
        {state.nextCursor && <button type="button" className="btn btn-secondary btn-sm" disabled={state.busy} onClick={state.moreConversations}>Weitere Chats laden</button>}
        {state.capabilities && !chats.length && <p className="text-muted">{filter ? 'Keine passenden Chats.' : 'Hier finden Sie Ihre gespeicherten Unterhaltungen.'}</p>}
        <p className="assistant-private-note"><LockKeyhole size={14} aria-hidden="true" /> Persönlich für Ihr Anwendungskonto. Aktenrechte gelten auch im Chat.</p>
      </aside>
      <section className="assistant-main" aria-label="KI-Unterhaltung">
        <header className="assistant-toolbar"><button type="button" className="btn btn-secondary assistant-mobile-list" aria-controls="assistant-chat-list" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(value => !value)}><PanelLeft size={16} /> Chats</button>
          <div className="assistant-conversation-title"><h2>{state.record?.title || 'Neue Unterhaltung'}</h2>{state.record && <ChatManagement key={state.record.id} record={state.record} disabled={state.busy || sending || Boolean(state.editPending)} onEdit={state.editConversation} />}</div>
          <div className="assistant-provider"><label className="sr-only" htmlFor="assistant-provider">Assistent auswählen</label><select id="assistant-provider" value={state.provider} disabled={locked || sending || !state.capabilities} onChange={event => state.chooseProvider(event.target.value)}>
            {!state.provider && <option value="">Assistent wird geladen …</option>}{(state.capabilities?.providers || []).map(provider => <option key={provider.id} value={provider.id}>{provider.id === 'local' ? 'Lokale Regelprüfung' : provider.label}</option>)}
          </select>{models.length > 0 && !local && <><label className="sr-only" htmlFor="assistant-model">KI-Modell</label><select id="assistant-model" value={state.model || ''} disabled={locked || sending} onChange={event => state.setModel(event.target.value)}><option value="">Vorgabe der Verbindung</option>{models.map(model => <option key={model.id} value={model.id}>{model.label || model.id}{state.connection?.model_discovery_status === 'verified' ? '' : ' · Verfügbarkeit ungeprüft'}</option>)}</select></>}
          <span className={`assistant-pill ${providerReady ? 'ready' : ''}`} role="status">{local && providerReady ? 'Lokal verfügbar' : connectionLabels[state.connection?.status] || 'Status wird geprüft …'}</span>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => setAccountsOpen(true)}>Konten und Modelle</button></div>
        </header>
        {local ? <p className="assistant-mode-note">Lokale Regelprüfung: prüft ausgewählte Angaben, liest verfügbaren Dokumenttext und berechnet vorhandene Auswertungen. Freie Fragen beantwortet ein verbundenes KI-Konto.</p>
          : !providerReady && state.capabilities && <div className="assistant-onboarding"><Sparkles size={23} aria-hidden="true" /><div><strong>Verbinden Sie Ihren Verwaltungsassistenten</strong><p>Mit ChatGPT oder Claude können Sie frei fragen und Verwaltungsaufträge vorbereiten. Ihre Auswahl bestimmt, welche Daten der Assistent nachlesen darf.</p><div className="assistant-inline-actions"><button type="button" className="btn btn-primary" onClick={() => setAccountsOpen(true)}>Kontoverbindung einrichten</button><button type="button" className="btn btn-secondary" disabled={locked || sending} onClick={() => state.chooseProvider('local')}>Lokal prüfen ohne KI-Konto</button></div></div></div>}
        {state.error && <div className="assistant-alert error" role="alert"><span>{state.error}</span><button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={state.retryLoad}>Ansicht erneut laden</button></div>}
        {state.notice && <p className="assistant-alert" role="status">{state.notice}</p>}
        {state.record?.archived && <p className="assistant-alert" role="status">Dieser Chat ist archiviert. Der Verlauf bleibt lesbar; über „Chat verwalten“ können Sie ihn zurückholen.</p>}
        {state.editPending && <p className="assistant-alert" role="status">Eine Chatänderung ist unbestätigt. <button type="button" className="btn btn-secondary btn-sm" disabled={state.busy} onClick={() => state.editConversation(null, true)}>Chatänderung abgleichen</button></p>}
        {state.pending && <div className="assistant-alert" role="status"><span>Eine Übermittlung ist unbestätigt. Ihre Eingabe bleibt erhalten; der ursprüngliche Auftrag wird mit derselben Kennung abgeglichen.</span><button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={() => state.pending.kind === 'create' ? state.startConversation() : state.submit(true)}>Übermittlung abgleichen</button></div>}
        <section className="assistant-transcript" ref={transcript} aria-label="Chatverlauf" aria-busy={state.loading} onScroll={event => { const element = event.currentTarget; scroll.current.follow = element.scrollHeight - element.clientHeight - element.scrollTop < 80; }}>
          {/* an empty chat greets only once an assistant is ready; before, the banner above says what to do and the
              chat area stays free (in a window of 900 px it had no room for both) */}
          {state.loading ? <p role="status">Private Unterhaltung wird geladen …</p> : !state.messages.length && !response ? onboarding ? null : <div className="assistant-empty"><Sparkles size={32} aria-hidden="true" /><h2>Was möchten Sie klären?</h2><p>Fügen Sie einen Beleg oder eine Akte hinzu. Der Assistent unterstützt Sie beim Verstehen und bereitet überprüfbare Entwürfe vor.</p>
            {/* without a connected account the banner above leads; the starters need a connected assistant */}
            {(local || providerReady) && <div className="assistant-starters">{local ? <><button type="button" onClick={() => document.getElementById('assistant-context')?.setAttribute('open', '')}><FolderSearch size={18} /> Grundlagen für die Regelprüfung wählen</button><Link to={canTask ? '/tasks?neu=1' : '/tasks'}><Plus size={18} />{canTask ? 'Aufgabe im Fachformular anlegen' : 'Aufgaben ansehen'}</Link><Link to="/reports"><ChartNoAxesCombined size={18} /> Zahlen lokal auswerten</Link></> : <>
              <button type="button" onClick={() => { setBody('Prüfe die Mietrückstände anhand aktueller Verträge, Forderungen und Zahlungen. Frage nach dem Bezug oder Zeitraum, falls diese nicht eindeutig sind.'); composer.current?.focus(); }}><ChartNoAxesCombined size={18} /> Mietrückstände verstehen</button>
              <button type="button" onClick={() => { setBody('Prüfe die angehängte Rechnung, kläre die Immobilienzuordnung und bereite einen belegten Rechnungsentwurf vor. Frage nach fehlenden Angaben.'); input.current?.click(); }}><FileText size={18} /> Rechnung vorbereiten</button>
              <button type="button" onClick={() => { setBody('Bereite eine Aktennotiz vor. Frage mich nach Inhalt und Bezug.'); composer.current?.focus(); }}><FileText size={18} /> Notiz vorbereiten</button>
              <button type="button" onClick={() => { setBody('Bereite eine Aufgabe vor. Frage mich nach Inhalt, Fälligkeit und optionalem Aktenbezug.'); composer.current?.focus(); }}><Plus size={18} /> Aufgabe vorbereiten</button>
            </>}</div>}
          </div> : <>
            {state.messageCursor && <button type="button" className="btn btn-secondary" disabled={state.busy} onClick={moreMessages}>Weitere Nachrichten laden</button>}
            {state.messages.map(message => <article className={`assistant-message ${message.role === 'user' ? 'user' : ''}`} key={message.id}>
              <span className="assistant-avatar">{message.role === 'user' ? <UserRound size={16} aria-hidden="true" /> : <Sparkles size={16} aria-hidden="true" />}</span>
              <div><div className="assistant-message-meta"><strong>{message.role === 'user' ? 'Sie' : state.capabilities?.providers.find(item => item.id === message.provider)?.label || message.provider || 'Assistent · Anbieter nicht erfasst'}</strong>{message.model && <small>{message.model}</small>}<time>{formatDateTime(message.created_at)}</time></div>{message.role === 'user' ? <div className="assistant-message-body">{message.content}</div> : <AssistantMessageContent content={message.content} />}
                {message.attachment_ids?.length > 0 && <div className="assistant-attachments">{message.attachment_ids.map(id => state.attachments.find(attachment => attachment.id === id)).filter(Boolean).map(attachment => <AssistantAttachment key={attachment.id} attachment={attachment} />)}</div>}
                <Sources sources={message.sources} attachments={state.attachments} />
                {message.role === 'assistant' && <AssistantFindings findings={(state.run && message.run_id === state.run.id) ? state.run.findings : message.findings} checks={message.local_checks} run={(state.run && message.run_id === state.run.id) ? state.run : undefined} disabled={locked || sending} canTask={canTask} onPrepare={(state.run && message.run_id === state.run.id) ? state.prepareFinding : undefined} onDiscuss={!local ? discuss : undefined} />}
              </div>
            </article>)}
            {displayedRun && <article className="assistant-message"><span className="assistant-avatar"><Sparkles size={16} /></span><div><div className="assistant-message-meta"><strong>{state.capabilities?.providers.find(item => item.id === state.run.provider)?.label || capability?.label || 'Assistent'}</strong><span>{sending ? 'Antwort wird ergänzt …' : runLabels[state.run.state]}</span></div><AssistantMessageContent content={response} /><Sources sources={state.run.sources} attachments={state.attachments} /></div></article>}
          </>}
          {state.run && <div className="assistant-run" role="status">{sending && <span className="assistant-live-dot" aria-hidden="true" />}<span>{runLabels[state.run.state] || 'Auftrag gespeichert'}</span><details><summary>Auftragsdetails</summary><small>Kennung {state.run.id} · {formatDateTime(state.run.created_at)}</small></details>
            {sending && <button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={() => state.runCommand('cancel')}><Square size={13} /> Antwort abbrechen</button>}
            {['failed', 'cancelled', 'blocked', 'unknown'].includes(state.run.state) && <><span>{typeof state.run.error === 'string' ? state.run.error : state.run.error?.message}</span><button type="button" className="btn btn-sm btn-secondary" disabled={state.busy || !providerReady} onClick={() => state.runCommand('retry')}><RefreshCw size={13} /> Neuen Versuch starten</button></>}
          </div>}
          {state.run?.verification_status === 'stale' && <p className="assistant-alert error" role="alert">Die Quellen wurden seit Beginn der Analyse geändert. Diese Antwort beschreibt den früheren Stand; bitte die aktuellen Quellen erneut prüfen. Vorschläge aus diesem Lauf können nicht übernommen werden.</p>}
          <AssistantActivity run={state.run} />
          {state.run && !state.messages.some(message => message.role === 'assistant' && message.run_id === state.run.id) && <AssistantFindings findings={state.run.findings} checks={state.run.local_checks} run={state.run} disabled={locked || sending} canTask={canTask} onPrepare={state.prepareFinding} onDiscuss={!local ? discuss : undefined} />}
          {state.run?.financial_summary && <details className="assistant-calculation"><summary>Berechnung und Originalauswertung</summary><FinancialProof finance={state.run.financial_summary} report={state.run.report} /></details>}
          {state.pollError && <div className="assistant-alert error" role="alert">Laufstatus konnte nicht aktualisiert werden: {state.pollError}<button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={state.run ? state.refreshRun : state.retryLoad}>{state.run ? 'Status erneut abrufen' : 'Ansicht erneut laden'}</button></div>}
        </section>
        {(state.proposals.length > 0 || state.proposalCursor) && <details className="assistant-workbasket" open><summary>Arbeitskorb · {state.proposals.filter(item => !['saved', 'rejected'].includes(item.state)).length} offen</summary><AssistantProposals owner={owner} attachments={state.attachments} proposals={state.proposals} perform={state.perform} disabled={locked} onChanged={proposal => { if (proposal) state.setProposals(previous => previous.map(item => item.id === proposal.id ? proposal : item)); }} />{state.proposalCursor && <button type="button" className="btn btn-secondary" disabled={state.busy || state.loading || !state.record} onClick={state.moreProposals}>Weitere Vorschläge laden</button>}</details>}
        <form className={`assistant-composer ${dragging ? 'dragging' : ''}`} aria-label="Nachricht verfassen" onSubmit={event => { event.preventDefault(); if (canSubmit) state.submit(); }}
          onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); upload(event.dataTransfer.files); }}>
          <AssistantWorkflows local={local} disabled={locked || sending} onChoose={addRequest} />
          <div className="assistant-scope-row"><label>Datenzugriff<select aria-label="Datenzugriff" value={dataScope} disabled={locked || sending} onChange={event => state.chooseScope(event.target.value)}><option value="authorized" disabled={local}>Berechtigte Verwaltungsdaten</option><option value="selected">Nur ausgewählte Akten</option><option value="none">Keine Verwaltungsdaten</option></select></label><details className="assistant-scope-help"><summary>Was bedeutet das?</summary><p>{dataScope === 'authorized' ? 'Der Assistent darf für Ihren Auftrag passende Akten in Ihrem berechtigten Bestand suchen, lesen und vorhandene Auswertungen berechnen. Verwendete Quellen und Arbeitsschritte werden angezeigt.' : dataScope === 'selected' ? 'Nur die ausdrücklich gewählten Akten stehen für diesen Auftrag bereit. Weitere Akten werden nicht automatisch freigegeben.' : 'Der Assistent erhält keine Verwaltungsakten und kann keine Daten daraus abfragen. Ihre Nachricht und die Arbeitsdateien dieses Chats bleiben verfügbar.'} Einträge werden erst nach Ihrer fachlichen Prüfung gespeichert.</p></details></div>
          {dataScope === 'authorized' && <p className="assistant-scope-notice">Für diese Unterhaltung freigegeben: benötigte Verwaltungsdaten innerhalb Ihrer Aktenrechte. Jeder Zugriff erscheint im Arbeitsprotokoll.</p>}
          {state.draft.context.length > 0 && <div className={`assistant-context-chips ${dataScope === 'none' ? 'inactive' : ''}`} aria-label="Gewählte Akten">{state.draft.context.map(card => <Link key={`${card.kind}:${card.id}`} to={contextHref(card)}>{card.title}</Link>)}</div>}
          <details className="assistant-context-disclosure" id="assistant-context"><summary>Arbeitskontext{state.draft.context.length ? ` · ${state.draft.context.length} Akten` : ''}{workingFiles.length ? ` · ${workingFiles.length} Dateien` : ''}{state.draft.report && dataScope !== 'none' ? ' · lokale Auswertung' : ''}</summary>
          {dataScope === 'none' && <p>Gewählte Akten und Berichte werden bei diesem Datenzugriff nicht übertragen.</p>}
          <AssistantContext key={state.selectedId || 'new'} cards={state.draft.context} report={state.draft.report} onReportChange={report => state.changeDraft(previous => ({ ...previous, report }))} onChange={context => state.changeDraft(previous => ({ ...previous, context, context_explicit: true,
            report: previous.report && !context.some(card => card.id === previous.report[`${card.kind}_id`]) ? null : previous.report }))} disabled={locked || dataScope === 'none'} />
          {state.attachments.length > 0 && <details className="assistant-file-library"><summary>Dateien dieser Unterhaltung ({state.attachments.length}{state.attachmentCursor ? '+' : ''})</summary><div className="assistant-attachments">{state.attachments.map(attachment => <div key={attachment.id}><AssistantAttachment attachment={attachment} /><button type="button" className="btn btn-sm btn-secondary" disabled={locked || workingIds.includes(attachment.id)} onClick={() => selectFile(attachment)}>Für Nachricht auswählen</button></div>)}</div>{state.attachmentCursor && <button type="button" className="btn btn-secondary btn-sm" disabled={state.busy} onClick={state.moreAttachments}>Weitere Dateien laden</button>}</details>}
          </details>
          <div className="assistant-attachments" role="group" aria-label="Dateiauswahl für die Nachricht">{workingFiles.map(attachment => <AssistantAttachment key={attachment.id} attachment={attachment} disabled={locked} onRemove={() => removeFile(attachment.id)} />)}</div>
          {workingFiles.length > 0 && <p className="assistant-composer-help">Diese Arbeitsdateien bleiben für Folgefragen verfügbar. Entfernen beendet ihre Verwendung; die Originaldatei bleibt im Chat.</p>}
          <label className="sr-only" htmlFor="assistant-message">Ihre Nachricht</label><textarea id="assistant-message" ref={composer} maxLength={state.capabilities?.max_message_length || 32000} placeholder={local ? 'Hinweis zur Regelprüfung (optional) …' : 'Was möchten Sie klären oder vorbereiten?'} value={state.draft.body} disabled={state.loading || Boolean(state.pending) || Boolean(state.editPending) || Boolean(state.record?.archived) || Boolean(state.selectedId && !state.record)}
            onChange={event => setBody(event.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }}
            onPaste={event => { const files = Array.from(event.clipboardData?.files || []); if (files.length) { event.preventDefault(); upload(files); } }} />
          <div className="assistant-composer-actions"><div className="assistant-composer-tools"><input type="file" ref={input} multiple hidden accept={state.capabilities?.allowed_mime_types?.join(',')} onChange={event => { upload(event.target.files); event.target.value = ''; }} />
            <button type="button" className="btn btn-secondary" disabled={locked || !state.capabilities} onClick={() => input.current?.click()}><Paperclip size={16} /> Dateien und Bilder</button>
            {state.uploading && <span role="status">Datei wird hochgeladen …</span>}
          </div><button className="btn btn-primary assistant-send" type="submit" disabled={!canSubmit}><Send size={16} /> {local ? 'Lokal prüfen' : 'Senden'}</button></div>
          <label className="assistant-web-option"><input type="checkbox" checked={!local && Boolean(capability?.web_research) && state.draft.web_research === true} disabled={locked || local || !capability?.web_research} onChange={event => state.changeDraft(previous => ({ ...previous, web_research: event.target.checked }))} /> Internetrecherche zulassen{local ? ' · lokale Analyse bleibt offline' : !capability?.web_research ? ' · für diese Verbindung nicht verfügbar' : ''}</label>
          <div className="assistant-composer-help">Dateien hier ablegen · Strg + Enter sendet <details className="assistant-file-limits"><summary>Dateigrenzen</summary>{state.capabilities?.attachment_max_bytes ? `Maximal ${formatBytes(state.capabilities.attachment_max_bytes)} je Datei` : ''}{state.capabilities?.max_attachments ? ` · Höchstens ${state.capabilities.max_attachments} Dateien je Nachricht` : ''}{state.capabilities?.request_attachment_max_bytes ? ` · Insgesamt höchstens ${formatBytes(state.capabilities.request_attachment_max_bytes)} je Nachricht` : ''}</details></div>
        </form>
      </section>
    </div>
    {accountsOpen && <AssistantAccounts state={state} onClose={() => { setAccountsOpen(false); state.reloadCapabilities(); }} />}
  </div>;
}
