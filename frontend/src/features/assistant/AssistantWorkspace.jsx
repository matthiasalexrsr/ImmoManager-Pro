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
import './assistant.css';

const runLabels = { queued: 'Auftrag gespeichert · wartet auf Verarbeitung', running: 'Antwort wird erstellt', completed: 'Abgeschlossen', failed: 'Analyse fehlgeschlagen',
  cancelled: 'Abgebrochen', unknown: 'Ergebnis unbestätigt', blocked: 'Dieser Auftrag kann derzeit nicht verarbeitet werden' };
const connectionLabels = { disconnected: 'Nicht verbunden', connecting: 'Anmeldung läuft', connected: 'Verbunden', unavailable: 'Nicht verfügbar', error: 'Verbindung prüfen' };
function loginHref(value, provider) {
  const hosts = provider === 'codex' ? ['auth.openai.com', 'chatgpt.com'] : provider === 'claude'
    ? ['claude.ai', 'claude.com', 'console.anthropic.com', 'platform.claude.com', 'accounts.anthropic.com', 'auth.anthropic.com'] : [];
  try { const url = new URL(value); return url.protocol === 'https:' && hosts.includes(url.hostname) && (!url.port || url.port === '443') && !url.username && !url.password && !url.hash ? url.href : ''; }
  catch { return ''; }
}

function LoginCompletion({ onComplete, disabled }) {
  const [code, setCode] = useState('');
  return <form onSubmit={event => { event.preventDefault(); const submitted = code.trim(); setCode(''); if (submitted) onComplete(submitted); }}>
    <label>Einmal-Anmeldecode von Claude<input aria-label="Einmal-Anmeldecode" autoComplete="off" spellCheck="false" value={code} onChange={event => setCode(event.target.value)} disabled={disabled} /></label>
    <button type="submit" className="btn btn-secondary" disabled={disabled || !code.trim()}>Anmeldung bestätigen</button>
  </form>;
}

function Sources({ sources = [] }) {
  const linked = sources.filter(source => contextHref(source));
  return linked.length ? <div className="assistant-sources">{linked.map(source => <details key={`${source.kind}:${source.id}`}><summary>{source.title || 'Quelle'}</summary><Link to={contextHref(source)}>Originalakte öffnen →</Link><small>Stand {source.revision || 'Nicht übermittelt'}</small>{source.sha256 && <small>SHA-256 {source.sha256}</small>}</details>)}</div> : null;
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
  const input = useRef(null), composer = useRef(null), transcript = useRef(null);
  const scroll = useRef({ conversation: null, follow: true, older: null });
  const capability = state.capabilities?.providers.find(provider => provider.id === state.provider);
  const local = state.provider === 'local';
  const models = state.connection?.models || capability?.models || [];
  const providerReady = Boolean(capability?.available && state.connection?.connected);
  const sending = activeRun(state.run);
  const locked = state.loading || state.busy || Boolean(state.pending) || Boolean(state.editPending) || Boolean(state.record?.archived) || Boolean(state.selectedId && !state.record);
  const chats = state.conversations.filter(chat => Boolean(chat.archived) === showArchived && chat.title.toLocaleLowerCase().includes(filter.toLocaleLowerCase()))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  const response = runText(state.run);
  const displayedRun = state.run && response && !state.messages.some(message => message.run_id === state.run.id && message.role === 'assistant');
  const pendingLogin = state.connection?.pending_login;
  const terminalLogin = pendingLogin && ['failed', 'cancelled', 'expired', 'completed'].includes(pendingLogin.status);
  const authUrl = loginHref(pendingLogin?.verification_url || pendingLogin?.auth_url, state.provider);
  const setBody = body => state.changeDraft(previous => ({ ...previous, body }));
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
      <main className="assistant-main" aria-label="KI-Unterhaltung">
        <header className="assistant-toolbar"><button type="button" className="btn btn-secondary assistant-mobile-list" aria-controls="assistant-chat-list" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(value => !value)}><PanelLeft size={16} /> Chats</button>
          <h2>{state.record?.title || 'Neuer Chat'}</h2>
          {state.record && <ChatManagement key={state.record.id} record={state.record} disabled={state.busy || sending || Boolean(state.editPending)} onEdit={state.editConversation} />}
          <div className="assistant-provider"><label className="sr-only" htmlFor="assistant-provider">Assistent auswählen</label><select id="assistant-provider" value={state.provider} disabled={Boolean(state.record) || locked || !state.capabilities} onChange={event => state.chooseProvider(event.target.value)}>
            {!state.provider && <option value="">Assistent wird geladen …</option>}{(state.capabilities?.providers || []).map(provider => <option key={provider.id} value={provider.id}>{provider.label}</option>)}
          </select>
          <span className={`assistant-pill ${providerReady ? 'ready' : ''}`} role="status">{local && providerReady ? 'Lokal verfügbar' : connectionLabels[state.connection?.status] || 'Status wird geprüft …'}</span>
          </div>
        </header>
        <div className="assistant-mode">
          <p>{local ? 'Lokale Analyse verarbeitet ausgewählte Quellen in Ihrer Anwendung. Für freie KI-Antworten wählen Sie ein verbundenes Konto.' : `${capability?.label || 'KI-Provider'} erhält Ihre Nachricht sowie die ausdrücklich ausgewählten Dateien und Akten. Fachliche Einträge entstehen erst nach Ihrer Prüfung im jeweiligen Formular.`}</p>
          {!local && <p>Für die KI wird ein begrenztes Quellenpaket übertragen. Verarbeitungshinweise zeigen mögliche Auslassungen. Originalakten und vollständige lokale Auswertungen bleiben direkt zugänglich.</p>}
          {state.record && <p>Provider und Modell gehören zu dieser Unterhaltung. Für einen Wechsel starten Sie einen neuen Chat.</p>}
          {models.length > 0 && <label>Modell <select aria-label="KI-Modell" value={state.model || ''} disabled={Boolean(state.record) || locked} onChange={event => state.setModel(event.target.value)}><option value="">Vorgabe der Verbindung</option>{models.map(model => <option key={model.id} value={model.id}>{model.label || model.id}</option>)}</select></label>}
          {capability?.reason && !capability.available && <p role="status">{capability.reason}</p>}
          {state.connection?.reason && <p role="status">{state.connection.reason}</p>}
          {!local && !state.connection?.connected && capability?.available && <div className="assistant-connection">
            {state.provider === 'codex' && <p>Für diese Anmeldung die Gerätecode-Anmeldung in den ChatGPT-Sicherheitseinstellungen freigeben. <a href="https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta" target="_blank" rel="noopener noreferrer">Offizielle Anmeldehilfe</a></p>}
            {pendingLogin && !terminalLogin ? <><strong>Anmeldung mit Ihrem Konto</strong>{pendingLogin.user_code && <p>Anmeldecode: <code>{pendingLogin.user_code}</code></p>}{authUrl && <a href={authUrl} target="_blank" rel="noopener noreferrer" className="btn btn-secondary">Anmeldung im Browser öffnen</a>}
              <p>{pendingLogin.error || 'Schließen Sie die Anmeldung im geöffneten Browser ab. Der Verbindungsstatus wird hier aktualisiert.'}</p>
              {pendingLogin.can_submit_code && <LoginCompletion key={`${state.provider}:${pendingLogin.id}`} onComplete={state.completeLogin} disabled={state.busy} />}
              <button type="button" className="btn btn-secondary" disabled={state.busy} onClick={() => state.connect('cancel')}>Anmeldung abbrechen</button></>
              : <><span>{terminalLogin ? pendingLogin.error || 'Die vorige Anmeldung ist beendet. Sie können sofort einen neuen Anmeldeversuch starten.' : 'Verbinden Sie Ihr Konto über den vom Provider bereitgestellten Anmeldeweg.'}</span><button type="button" className="btn btn-secondary" disabled={state.busy} onClick={() => state.connect('login')}>{terminalLogin ? 'Erneut anmelden' : `Mit ${capability.label} anmelden`}</button></>}
          </div>}
          {!local && state.connection?.connected && <button type="button" className="btn btn-sm btn-secondary" disabled={state.busy || sending} onClick={() => state.connect('disconnect')}>Kontoverbindung trennen</button>}
        </div>
        {state.error && <div className="assistant-alert error" role="alert"><span>{state.error}</span><button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={state.retryLoad}>Ansicht erneut laden</button></div>}
        {state.notice && <p className="assistant-alert" role="status">{state.notice}</p>}
        {state.record?.archived && <p className="assistant-alert" role="status">Dieser Chat ist archiviert. Der Verlauf bleibt lesbar; über „Chat verwalten“ können Sie ihn zurückholen.</p>}
        {state.editPending && <p className="assistant-alert" role="status">Eine Chatänderung ist unbestätigt. <button type="button" className="btn btn-secondary btn-sm" disabled={state.busy} onClick={() => state.editConversation(null, true)}>Chatänderung abgleichen</button></p>}
        {state.pending && <div className="assistant-alert" role="status"><span>Eine Übermittlung ist unbestätigt. Ihre Eingabe bleibt erhalten; der ursprüngliche Auftrag wird mit derselben Kennung abgeglichen.</span><button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={() => state.pending.kind === 'create' ? state.startConversation() : state.submit(true)}>Übermittlung abgleichen</button></div>}
        <section className="assistant-transcript" ref={transcript} aria-label="Chatverlauf" aria-busy={state.loading} onScroll={event => { const element = event.currentTarget; scroll.current.follow = element.scrollHeight - element.clientHeight - element.scrollTop < 80; }}>
          {state.loading ? <p role="status">Private Unterhaltung wird geladen …</p> : !state.messages.length && !response ? <div className="assistant-empty"><Sparkles size={32} aria-hidden="true" /><h2>Was möchten Sie klären?</h2><p>Fügen Sie einen Beleg oder eine Akte hinzu. Der Assistent unterstützt Sie beim Verstehen und bereitet überprüfbare Entwürfe vor.</p>
            <div className="assistant-starters"><button type="button" onClick={() => { setBody('Fasse die ausgewählten Unterlagen zusammen und nenne offene Punkte mit Quellen.'); composer.current?.focus(); }}><FileText size={18} /> Unterlagen zusammenfassen</button>
              <button type="button" onClick={() => { setBody('Prüfe die ausgewählten Akten anhand der lokalen Analysedaten auf Unstimmigkeiten und fehlende Angaben. Nenne die Quellen.'); composer.current?.focus(); }}><FolderSearch size={18} /> Unstimmigkeiten prüfen</button>
              {local ? <Link to={canTask ? '/tasks?neu=1' : '/tasks'}><Plus size={18} />{canTask ? 'Aufgabe im Fachformular anlegen' : 'Aufgaben ansehen'}</Link>
                : <button type="button" onClick={() => { setBody('Bereite aus den ausgewählten Quellen einen Aufgabenvorschlag vor.'); composer.current?.focus(); }}><Plus size={18} /> Aufgabe vorbereiten</button>}
              <Link to="/reports"><ChartNoAxesCombined size={18} /> Zahlen lokal auswerten</Link></div>
          </div> : <>
            {state.messageCursor && <button type="button" className="btn btn-secondary" disabled={state.busy} onClick={moreMessages}>Weitere Nachrichten laden</button>}
            {state.messages.map(message => <article className={`assistant-message ${message.role === 'user' ? 'user' : ''}`} key={message.id}>
              <span className="assistant-avatar">{message.role === 'user' ? <UserRound size={16} aria-hidden="true" /> : <Sparkles size={16} aria-hidden="true" />}</span>
              <div><div className="assistant-message-meta"><strong>{message.role === 'user' ? 'Sie' : capability?.label || 'Assistent'}</strong><time>{formatDateTime(message.created_at)}</time></div>{message.role === 'user' ? <div className="assistant-message-body">{message.content}</div> : <AssistantMessageContent content={message.content} />}
                {message.attachment_ids?.length > 0 && <div className="assistant-attachments">{message.attachment_ids.map(id => state.attachments.find(attachment => attachment.id === id)).filter(Boolean).map(attachment => <AssistantAttachment key={attachment.id} attachment={attachment} />)}</div>}
                <Sources sources={message.sources} />
              </div>
            </article>)}
            {displayedRun && <article className="assistant-message"><span className="assistant-avatar"><Sparkles size={16} /></span><div><div className="assistant-message-meta"><strong>{capability?.label || 'Assistent'}</strong><span>{sending ? 'Antwort wird ergänzt …' : runLabels[state.run.state]}</span></div><AssistantMessageContent content={response} /><Sources sources={state.run.sources} /></div></article>}
          </>}
          {state.run && <div className="assistant-run" role="status">{sending && <span className="assistant-live-dot" aria-hidden="true" />}<span>{runLabels[state.run.state] || 'Auftrag gespeichert'}</span><small>Auftrag {state.run.id.slice(0, 8)}</small>
            {sending && <button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={() => state.runCommand('cancel')}><Square size={13} /> Antwort abbrechen</button>}
            {['failed', 'cancelled', 'blocked', 'unknown'].includes(state.run.state) && <><span>{typeof state.run.error === 'string' ? state.run.error : state.run.error?.message}</span><button type="button" className="btn btn-sm btn-secondary" disabled={state.busy || !providerReady} onClick={() => state.runCommand('retry')}><RefreshCw size={13} /> Neuen Versuch starten</button></>}
          </div>}
          {state.run?.verification_status === 'stale' && <p className="assistant-alert error" role="alert">Die Quellen wurden seit Beginn der Analyse geändert. Diese Antwort beschreibt den früheren Stand; bitte die aktuellen Quellen erneut prüfen. Vorschläge aus diesem Lauf können nicht übernommen werden.</p>}
          {(state.run?.events || []).some(event => event.message) && <details className="assistant-run-notes"><summary>Verarbeitungshinweise</summary>{state.run.events.filter(event => event.message).map(event => <p key={event.sequence}>{event.message}</p>)}</details>}
          <FinancialProof finance={state.run?.financial_summary} report={state.run?.report} />
          {state.pollError && <div className="assistant-alert error" role="alert">Laufstatus konnte nicht aktualisiert werden: {state.pollError}<button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={state.run ? state.refreshRun : state.retryLoad}>{state.run ? 'Status erneut abrufen' : 'Ansicht erneut laden'}</button></div>}
          <AssistantProposals owner={owner} proposals={state.proposals} perform={state.perform} disabled={locked} onChanged={proposal => { if (proposal) state.setProposals(previous => previous.map(item => item.id === proposal.id ? proposal : item)); }} />
          {state.proposalCursor && <button type="button" className="btn btn-secondary" disabled={state.busy || state.loading || !state.record} onClick={state.moreProposals}>Weitere Vorschläge laden</button>}
        </section>
        <form className={`assistant-composer ${dragging ? 'dragging' : ''}`} aria-label="Nachricht verfassen" onSubmit={event => { event.preventDefault(); if (!locked && !sending && providerReady) state.submit(); }}
          onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); upload(event.dataTransfer.files); }}>
          <AssistantContext key={state.selectedId || 'new'} cards={state.draft.context} report={state.draft.report} onReportChange={report => state.changeDraft(previous => ({ ...previous, report }))} onChange={context => state.changeDraft(previous => ({ ...previous, context,
            report: previous.report && !context.some(card => card.id === previous.report[`${card.kind}_id`]) ? null : previous.report }))} disabled={locked} />
          {state.attachments.length > 0 && <details className="assistant-file-library"><summary>Dateien dieser Unterhaltung ({state.attachments.length}{state.attachmentCursor ? '+' : ''})</summary><div className="assistant-attachments">{state.attachments.map(attachment => <div key={attachment.id}><AssistantAttachment attachment={attachment} /><button type="button" className="btn btn-sm btn-secondary" disabled={locked || state.draft.attachments.some(item => item.id === attachment.id)} onClick={() => state.changeDraft(previous => ({ ...previous, attachments: [...previous.attachments, attachment] }))}>Für Nachricht auswählen</button></div>)}</div>{state.attachmentCursor && <button type="button" className="btn btn-secondary btn-sm" disabled={state.busy} onClick={state.moreAttachments}>Weitere Dateien laden</button>}</details>}
          <div className="assistant-attachments" role="group" aria-label="Dateiauswahl für die Nachricht">{state.draft.attachments.map(attachment => <AssistantAttachment key={attachment.id} attachment={attachment} disabled={locked} onRemove={() => state.changeDraft(previous => ({ ...previous, attachments: previous.attachments.filter(item => item.id !== attachment.id) }))} />)}</div>
          <label className="sr-only" htmlFor="assistant-message">Ihre Nachricht</label><textarea id="assistant-message" ref={composer} maxLength={state.capabilities?.max_message_length || 32000} placeholder={local ? 'Frage zu Ihren ausgewählten Quellen …' : 'Fragen, erklären lassen oder einen Entwurf vorbereiten …'} value={state.draft.body} disabled={state.loading || Boolean(state.pending) || Boolean(state.editPending) || Boolean(state.record?.archived) || Boolean(state.selectedId && !state.record)}
            onChange={event => setBody(event.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }}
            onPaste={event => { const files = Array.from(event.clipboardData?.files || []); if (files.length) { event.preventDefault(); upload(files); } }} />
          <div className="assistant-composer-actions"><div className="assistant-composer-tools"><input type="file" ref={input} multiple hidden accept={state.capabilities?.allowed_mime_types?.join(',')} onChange={event => { upload(event.target.files); event.target.value = ''; }} />
            <button type="button" className="btn btn-secondary" disabled={locked || !state.capabilities} onClick={() => input.current?.click()}><Paperclip size={16} /> Dateien und Bilder</button>
            {state.uploading && <span role="status">Datei wird hochgeladen …</span>}
          </div><button className="btn btn-primary assistant-send" type="submit" disabled={locked || sending || !providerReady || !state.draft.body.trim()}><Send size={16} /> {local ? 'Lokal analysieren' : 'Senden'}</button></div>
          <label className="assistant-web-option"><input type="checkbox" checked={!local && Boolean(capability?.web_research) && state.draft.web_research === true} disabled={locked || local || !capability?.web_research} onChange={event => state.changeDraft(previous => ({ ...previous, web_research: event.target.checked }))} /> Internetrecherche zulassen{local ? ' · lokale Analyse bleibt offline' : !capability?.web_research ? ' · für diese Verbindung nicht verfügbar' : ''}</label>
          <p className="assistant-composer-help">Dateien hier ablegen oder Bilder einfügen · Strg + Enter sendet{state.capabilities?.attachment_max_bytes ? ` · Maximal ${formatBytes(state.capabilities.attachment_max_bytes)} je Datei` : ''}{state.capabilities?.max_attachments ? ` · Höchstens ${state.capabilities.max_attachments} Dateien je Nachricht` : ''}{state.capabilities?.request_attachment_max_bytes ? ` · Insgesamt höchstens ${formatBytes(state.capabilities.request_attachment_max_bytes)} je Nachricht` : ''}. Vorschläge werden erst nach Prüfung übernommen.</p>
        </form>
      </main>
    </div>
  </div>;
}
