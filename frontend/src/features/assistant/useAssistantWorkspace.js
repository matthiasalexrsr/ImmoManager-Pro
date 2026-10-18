import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api';
import { assistantApi, activeRun, contextSelection } from './assistantApi';
import { readAssistantDraft, writeAssistantDraft, readAssistantCommand, writeAssistantCommand, clearAssistantCommand } from './assistantDrafts';

const emptyDraft = () => ({ body: '', attachments: [], context: [], web_research: false, report: null });
const rejected = failure => [400, 403, 404, 409, 413, 415, 422].includes(failure.statusCode);
const mergeRows = (first, next) => [...new Map([...first, ...next].map(row => [row.id, row])).values()];
const proposalPageCursor = page => page?.has_more === false ? null : page?.next_cursor || null;

export default function useAssistantWorkspace(owner) {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get('conversation') || '';
  const identity = `${owner}:${selectedId || 'new'}`;
  const live = useRef(false), scope = useRef(identity), epoch = useRef(0), operation = useRef(false);
  scope.current = identity;
  const [attempt, setAttempt] = useState(0);
  const [capabilities, setCapabilities] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [connection, setConnection] = useState(null);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [record, setRecord] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messageCursor, setMessageCursor] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [attachmentCursor, setAttachmentCursor] = useState(null);
  const [run, setRun] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [proposalCursor, setProposalCursor] = useState(null);
  const proposalPagesLoaded = useRef(false);
  const [draft, setDraft] = useState(emptyDraft);
  const draftRef = useRef(draft);
  const [pending, setPending] = useState(null);
  const [editPending, setEditPending] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [notice, setNotice] = useState('');
  const [pollAttempt, setPollAttempt] = useState(0);
  const currentProvider = record?.provider || provider;
  const connectionProvider = useRef('');
  const hideRevoked = useCallback(failure => {
    if (![401, 403, 404].includes(failure.statusCode)) return;
    setRecord(null); setMessages([]); setAttachments([]); setRun(null); setProposals([]); setProposalCursor(null); proposalPagesLoaded.current = false;
    draftRef.current = emptyDraft(); setDraft(emptyDraft()); setPending(null);
    setConversations(previous => previous.filter(item => item.id !== selectedId));
  }, [selectedId]);

  useEffect(() => {
    live.current = true;
    const invalidate = () => { live.current = false; epoch.current += 1; setMessages([]); setDraft(emptyDraft()); setAttachments([]); setRecord(null); setRun(null); setProposals([]); setProposalCursor(null); proposalPagesLoaded.current = false; setConversations([]); };
    window.addEventListener('workspace-logout', invalidate);
    window.addEventListener('workspace-owner', invalidate);
    return () => { live.current = false; epoch.current += 1; window.removeEventListener('workspace-logout', invalidate); window.removeEventListener('workspace-owner', invalidate); };
  }, []);

  useEffect(() => {
    const controller = new AbortController(); const session = api.captureSession();
    Promise.all([assistantApi.capabilities({ signal: controller.signal }), assistantApi.conversations(null, { signal: controller.signal })])
      .then(([caps, page]) => {
        session(); if (!live.current || controller.signal.aborted) return;
        if (!Array.isArray(caps.providers) || !Array.isArray(page.items)) throw new Error('Der KI-Arbeitsbereich hat unvollständige Auswahldaten geliefert.');
        setCapabilities(caps); setConversations(page.items); setNextCursor(page.next_cursor || null);
        setProvider(previous => previous || caps.providers.find(item => item.id === 'local')?.id || caps.providers[0]?.id || '');
      }).catch(failure => { if (live.current && !controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    const generation = ++epoch.current; const controller = new AbortController(); const session = api.captureSession();
    operation.current = false;
    setRecord(null); setMessages([]); setAttachments([]); setRun(null); setProposals([]); setProposalCursor(null); proposalPagesLoaded.current = false; setPending(null); setEditPending(null);
    setError(''); setPollError(''); setNotice(''); setBusy(false); setUploading(false); setLoading(Boolean(selectedId));
    const current = () => { session(); return live.current && scope.current === identity && generation === epoch.current && !controller.signal.aborted; };
    if (!selectedId) {
      const restored = readAssistantDraft(owner, 'new'); draftRef.current = restored; setDraft(restored);
      setPending(readAssistantCommand(owner, 'new')); setLoading(false);
      return () => controller.abort();
    }
    draftRef.current = emptyDraft(); setDraft(emptyDraft());
    Promise.all([assistantApi.conversation(selectedId, { signal: controller.signal }), assistantApi.messages(selectedId, null, { signal: controller.signal }),
      assistantApi.attachments(selectedId, { signal: controller.signal }), assistantApi.runs(selectedId, null, { signal: controller.signal }),
      assistantApi.proposals(selectedId, { signal: controller.signal })]).then(([conversation, page, files, runs, suggested]) => {
      if (!current()) return;
      if (conversation.id !== selectedId || !Array.isArray(page.items) || !Array.isArray(files.items) || !Array.isArray(runs.items)) throw new Error('Die Chatantwort gehört nicht zur ausgewählten Unterhaltung.');
      setRecord(conversation); setMessages(page.items); setMessageCursor(page.next_cursor || null); setAttachments(files.items); setAttachmentCursor(files.next_cursor || null);
      setRun(runs.items.find(item => item.id === conversation.active_run_id) || runs.items[0] || null);
      setProposals(Array.isArray(suggested) ? suggested : suggested.items || []);
      setProposalCursor(proposalPageCursor(suggested));
      const restored = readAssistantDraft(owner, selectedId);
      // Restore private buffers only after the server has authorized this conversation.
      draftRef.current = restored; setDraft(restored); setPending(readAssistantCommand(owner, selectedId));
      setEditPending(readAssistantCommand(owner, `edit:${selectedId}`));
      setConversations(previous => mergeRows(previous, [conversation]));
    }).catch(failure => { if (live.current && scope.current === identity && !controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (live.current && scope.current === identity && !controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [identity, owner, selectedId, attempt]);

  useEffect(() => {
    if (!currentProvider) return;
    const controller = new AbortController(); const session = api.captureSession();
    if (connectionProvider.current !== currentProvider) { connectionProvider.current = currentProvider; setConnection(null); }
    assistantApi.connection(currentProvider, { signal: controller.signal }).then(value => {
      session(); if (live.current && !controller.signal.aborted) setConnection(value);
    }).catch(failure => { if (live.current && !controller.signal.aborted) setConnection({ status: 'error', connected: false, reason: failure.message }); });
    return () => controller.abort();
  }, [currentProvider, connectionAttempt, attempt]);

  useEffect(() => {
    if (connection?.status !== 'connecting') return;
    const timer = setTimeout(() => setConnectionAttempt(value => value + 1), 2500);
    return () => clearTimeout(timer);
  }, [connection]);

  useEffect(() => {
    if (!activeRun(run) || pollError) return;
    const controller = new AbortController(); const session = api.captureSession(); const token = identity;
    const timer = setTimeout(async () => {
      try {
        const next = await assistantApi.run(run.id, { signal: controller.signal }); session();
        if (!live.current || scope.current !== token || controller.signal.aborted) return;
        if (next.conversation_id !== selectedId || next.id !== run.id) throw new Error('Der Laufstatus gehört zu einer anderen Unterhaltung.');
        if (activeRun(next)) setRun(next);
        else {
          const [page, conversation, suggestions] = await Promise.all([assistantApi.messages(selectedId), assistantApi.conversation(selectedId), assistantApi.proposals(selectedId)]); session();
          if (!live.current || scope.current !== token || controller.signal.aborted) return;
          setRun(next); setMessages(previous => mergeRows(previous, page.items)); setRecord(conversation);
          setProposals(previous => mergeRows(previous, Array.isArray(suggestions) ? suggestions : suggestions.items || []));
          if (!proposalPagesLoaded.current) setProposalCursor(proposalPageCursor(suggestions));
          setConversations(previous => mergeRows(previous, [conversation]));
        }
      } catch (failure) { if (live.current && scope.current === token && !controller.signal.aborted) { hideRevoked(failure); setPollError(failure.message); } }
    }, 1500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [run, identity, selectedId, pollError, pollAttempt, hideRevoked]);

  const changeDraft = next => {
    const value = typeof next === 'function' ? next(draftRef.current) : next;
    draftRef.current = value; setDraft(value);
    try { writeAssistantDraft(owner, selectedId || 'new', value); } catch (failure) { setError(failure.message); }
  };
  const navigate = value => setParams(current => {
    const next = new URLSearchParams(current); if (value) next.set('conversation', value); else next.delete('conversation'); return next;
  });
  const chooseProvider = value => { setProvider(value); setModel(''); setConnection(null); changeDraft(previous => ({ ...previous, web_research: false })); };

  const perform = async action => {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError(''); setNotice('');
    const token = identity; const generation = epoch.current; const session = api.captureSession();
    const current = () => { session(); if (!live.current || scope.current !== token || generation !== epoch.current) throw new Error('Die ausgewählte Unterhaltung hat sich geändert.'); };
    try { await action(current); }
    catch (failure) { if (live.current && scope.current === token && generation === epoch.current) { hideRevoked(failure); setError(failure.message); } }
    finally { if (live.current && scope.current === token && generation === epoch.current) { operation.current = false; setBusy(false); } }
  };
  const ensureConversation = async (current, title = 'Neuer Chat') => {
    if (record) return record;
    const old = readAssistantCommand(owner, 'new');
    if (old && old.kind !== 'create') throw new Error('Bitte zuerst die unbestätigte Übermittlung abgleichen.');
    const command = old || { kind: 'create', idempotency_key: crypto.randomUUID(), request: { title, provider, model: model || null, effort: 'high' } };
    writeAssistantCommand(owner, 'new', command); setPending(command);
    let conversation;
    try { conversation = await assistantApi.create({ ...command.request, idempotency_key: command.idempotency_key }); current(); }
    catch (failure) { current(); if (rejected(failure)) { clearAssistantCommand(owner, 'new', command); setPending(null); } throw failure; }
    clearAssistantCommand(owner, 'new', command); setPending(null);
    writeAssistantDraft(owner, conversation.id, draftRef.current);
    setConversations(previous => mergeRows(previous, [conversation]));
    return conversation;
  };
  const startConversation = () => perform(async current => {
    const conversation = await ensureConversation(current); current(); navigate(conversation.id);
  });
  const submit = (retry = false) => perform(async current => {
    if (activeRun(run)) throw new Error('Bitte warten Sie auf die laufende Antwort oder brechen Sie sie ab.');
    const original = draftRef.current;
    if (!retry && !original.body.trim()) return;
    const conversation = await ensureConversation(current, original.body.trim().slice(0, 80) || 'Neuer Chat'); current();
    const prior = readAssistantCommand(owner, conversation.id);
    const command = prior || { kind: 'submit', idempotency_key: crypto.randomUUID(), request: {
      content: original.body, attachment_ids: original.attachments.map(item => item.id), context: contextSelection(original.context), expected_revision: conversation.revision,
      web_research: conversation.provider !== 'local' && Boolean(capabilities?.providers.find(item => item.id === conversation.provider)?.web_research) && original.web_research === true,
      report: original.report || null,
    } };
    if (prior && !retry) throw new Error('Eine Übermittlung ist unbestätigt. Bitte zuerst mit derselben Kennung abgleichen.');
    writeAssistantCommand(owner, conversation.id, command); setPending(command);
    let submitted;
    try { submitted = await assistantApi.submit(conversation.id, { ...command.request, idempotency_key: command.idempotency_key }); current(); }
    catch (failure) {
      current();
      if (rejected(failure)) { clearAssistantCommand(owner, conversation.id, command); setPending(null); }
      if (!selectedId) navigate(conversation.id);
      throw failure;
    }
    clearAssistantCommand(owner, conversation.id, command); setPending(null);
    const cleared = { ...original, body: '', attachments: [] };
    writeAssistantDraft(owner, conversation.id, cleared);
    if (!selectedId) { writeAssistantDraft(owner, 'new', emptyDraft()); navigate(conversation.id); }
    else {
      changeDraft(cleared); setRun(submitted); setPollError('');
      const [page, fresh] = await Promise.all([assistantApi.messages(conversation.id), assistantApi.conversation(conversation.id)]); current();
      setMessages(previous => mergeRows(previous, page.items)); setRecord(fresh); setConversations(previous => mergeRows(previous, [fresh]));
    }
  });
  const upload = files => perform(async current => {
    setUploading(true);
    try {
      if (draftRef.current.attachments.length + files.length > (capabilities?.max_attachments || 12)) throw new Error('Zu viele ausgewählte Dateien. Bitte die Auswahl verkleinern.');
      for (const file of files) if (capabilities?.attachment_max_bytes && file.size > capabilities.attachment_max_bytes) throw new Error(`„${file.name}“ überschreitet die erlaubte Dateigröße.`);
      const conversation = await ensureConversation(current); current();
      setRecord(conversation);
      for (const file of files) {
        const uploaded = await assistantApi.upload(conversation.id, file); current();
        setAttachments(previous => mergeRows(previous, [uploaded]));
        const next = { ...draftRef.current, attachments: mergeRows(draftRef.current.attachments, [uploaded]) };
        writeAssistantDraft(owner, conversation.id, next);
        if (selectedId) changeDraft(next); else { draftRef.current = next; setDraft(next); }
      }
      if (!selectedId) navigate(conversation.id);
    } finally { if (live.current && scope.current === identity) setUploading(false); }
  });
  const runCommand = action => perform(async current => {
    if (!run) return;
    const identityKey = `${action}:${run.id}`;
    const command = readAssistantCommand(owner, identityKey) || { kind: action, idempotency_key: crypto.randomUUID(), request: { expected_revision: run.revision } };
    writeAssistantCommand(owner, identityKey, command);
    try {
      const next = await assistantApi[action](run.id, { ...command.request, idempotency_key: command.idempotency_key }); current();
      clearAssistantCommand(owner, identityKey, command); setRun(next); setPollError('');
      const fresh = await assistantApi.conversation(selectedId); current(); setRecord(fresh); setConversations(previous => mergeRows(previous, [fresh]));
    } catch (failure) { current(); if (rejected(failure)) clearAssistantCommand(owner, identityKey, command); throw failure; }
  });
  const refreshRun = () => perform(async current => {
    const next = await assistantApi.run(run.id); current(); setRun(next); setPollError(''); setPollAttempt(value => value + 1);
    if (!activeRun(next)) {
      const [page, fresh, suggestions] = await Promise.all([assistantApi.messages(selectedId), assistantApi.conversation(selectedId), assistantApi.proposals(selectedId)]); current();
      setMessages(previous => mergeRows(previous, page.items)); setRecord(fresh); setConversations(previous => mergeRows(previous, [fresh]));
      setProposals(previous => mergeRows(previous, Array.isArray(suggestions) ? suggestions : suggestions.items || []));
      if (!proposalPagesLoaded.current) setProposalCursor(proposalPageCursor(suggestions));
    }
  });
  const connect = action => perform(async current => {
    const value = action === 'login' ? await assistantApi.login(currentProvider) : action === 'cancel'
      ? await assistantApi.cancelLogin(currentProvider, connection?.pending_login?.id) : await assistantApi.disconnect(currentProvider);
    current(); setConnection(value); setConnectionAttempt(value => value + 1);
  });
  const moreConversations = () => perform(async current => {
    const page = await assistantApi.conversations(nextCursor); current(); setConversations(previous => mergeRows(previous, page.items)); setNextCursor(page.next_cursor || null);
  });
  const completeLogin = code => perform(async current => {
    const value = await assistantApi.completeLogin(currentProvider, connection.pending_login.id, code); current();
    setConnection(value); setConnectionAttempt(value => value + 1);
  });
  const moreMessages = () => perform(async current => {
    const page = await assistantApi.messages(selectedId, messageCursor); current(); setMessages(previous => mergeRows(page.items, previous)); setMessageCursor(page.next_cursor || null);
  });
  const moreAttachments = () => perform(async current => {
    const page = await assistantApi.attachments(selectedId, undefined, attachmentCursor); current(); setAttachments(previous => mergeRows(previous, page.items)); setAttachmentCursor(page.next_cursor || null);
  });
  const moreProposals = () => perform(async current => {
    if (!proposalCursor) return;
    const page = await assistantApi.proposals(selectedId, undefined, proposalCursor); current();
    if (!Array.isArray(page.items)) throw new Error('Die Vorschlagsliste hat eine unvollständige Antwort geliefert.');
    setProposals(previous => mergeRows(previous, page.items)); proposalPagesLoaded.current = true; setProposalCursor(proposalPageCursor(page));
  });
  const editConversation = (patch, retry = false) => perform(async current => {
    if (!record) return;
    const key = `edit:${record.id}`;
    const old = readAssistantCommand(owner, key);
    if (old && !retry) throw new Error('Bitte zuerst die unbestätigte Chatänderung abgleichen.');
    const command = old || { kind: 'edit', idempotency_key: crypto.randomUUID(), request: { ...patch, expected_revision: record.revision } };
    writeAssistantCommand(owner, key, command); setEditPending(command);
    try {
      const fresh = await assistantApi.edit(record.id, { ...command.request, idempotency_key: command.idempotency_key }); current();
      clearAssistantCommand(owner, key, command); setEditPending(null); setRecord(fresh); setConversations(previous => mergeRows(previous, [fresh]));
    } catch (failure) { current(); if (rejected(failure)) { clearAssistantCommand(owner, key, command); setEditPending(null); } throw failure; }
  });
  return { capabilities, conversations, nextCursor, provider: currentProvider, model: record?.model || model, connection,
    record, messages, messageCursor, attachments, attachmentCursor, run, proposals, proposalCursor, draft, pending, editPending, loading, busy, uploading, error, pollError, notice, selectedId,
    setModel, chooseProvider, changeDraft, navigate, startConversation, submit, upload, runCommand, refreshRun, connect, moreConversations, moreMessages,
    retryLoad: () => setAttempt(value => value + 1), setError, setNotice, perform, refresh: () => setAttempt(value => value + 1), setProposals, completeLogin, moreAttachments, moreProposals, editConversation };
}
