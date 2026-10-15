import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { workspace, FORM_KINDS, formContext } from '../utils/workspaceClient';

const SECRET = /password|passwd|passphrase|secret|token|credential|authorization|totp|otp|recovery.?code|api.?key|private.?key/i;
const containsSecret = value => Array.isArray(value) ? value.some(containsSecret)
  : value && typeof value === 'object' && Object.entries(value).some(([key, item]) => SECRET.test(key) || containsSecret(item));
const safeFields = fields => fields.filter(field => field.type !== 'password' && field.type !== 'file' && !SECRET.test(field.key));
const readBuffer = key => { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } };
const writeBuffer = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Server autosave still works. */ } };
const removeBuffer = key => { try { localStorage.removeItem(key); } catch { /* Storage may be disabled. */ } };
const completionBuffers = key => {
  try { return Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
    .filter(candidate => candidate?.startsWith(`${key}:completion:`)); } catch { return []; }
};
const formKey = signature => { let hash = 2166136261; for (const char of signature) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619); return `form-${(hash >>> 0).toString(16)}`; };

// A serialized writer keeps the revision and the command of an uncertain response.
// The browser buffer is never offered until a server request has rechecked access.
export default function useFormDraft({ fields, initial, enabled = true, context: explicitContext, anchor, source: explicitSource }) {
  const auth = useAuth();
  const context = explicitContext || formContext(window.location.pathname);
  const owner = auth?.user?.id;
  const fieldSignature = safeFields(fields).map(field => field.key).sort().join('|');
  const supported = Boolean(enabled && owner && context && fieldSignature && !fields.some(field => field.type === 'password' || SECRET.test(field.key)));
  const identity = `${owner}:${context}:${initial?.id || 'new'}:${anchor?.id || ''}:${fieldSignature}`;
  const key = `workspace:${owner}:draft-buffer:${context}:${initial?.id || 'new'}:${anchor?.id || ''}:${fieldSignature}`;
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [recovery, setRecovery] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const row = useRef(null);
  const latest = useRef(null);
  const pending = useRef(null);
  const chain = useRef(Promise.resolve());
  const timer = useRef(null);
  const active = useRef(false);
  const ready = useRef(false);
  const blocked = useRef(false);
  const fieldsRef = useRef(fields);
  fieldsRef.current = fields;
  const source = useRef(null);
  const generation = useRef(0);
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const completing = useRef(false);
  const sessionIdentity = useRef(null);

  const persist = useCallback(() => {
    const epoch = generation.current;
    const current = () => active.current && currentIdentity.current === identity && generation.current === epoch;
    chain.current = chain.current.catch(() => {}).then(async () => {
      if (!current() || completing.current || !ready.current || blocked.current || (!latest.current && !pending.current)) return;
      while (current() && !completing.current && (latest.current || pending.current)) {
        if (!pending.current) {
          const values = latest.current;
          latest.current = null;
          const id = row.current?.id || workspace.command();
          pending.current = { id, body: {
            base_revision: row.current?.revision || 0, idempotency_key: workspace.command(),
            context, mode: source.current ? 'edit' : 'create', source: source.current, anchor: anchor || null,
            field_keys: fieldSignature.split('|'), form_key: formKey(fieldSignature),
            values,
          } };
        }
        writeBuffer(key, { pending: pending.current, values: latest.current || pending.current.body.values });
        if (active.current) { setStatus('saving'); setError(''); }
        try {
          pending.current.sent = true;
          writeBuffer(key, { pending: pending.current, values: latest.current || pending.current.body.values });
          const command = pending.current;
          const saved = await workspace.put('drafts', command.id, command.body);
          if (!current()) return;
          row.current = saved;
          pending.current = null;
          if (!completing.current) writeBuffer(key, { row: saved, values: latest.current || saved.values });
          if (saved.source_state?.status === 'deleted') { setRecovery(saved); setStatus('recovery'); }
          else if (active.current) setStatus(saved.source_state?.status === 'changed' ? 'changed' : 'saved');
        } catch (failure) {
          if (!current()) return;
          if (failure.statusCode === 409) blocked.current = true;
          if (active.current) {
            setError(failure.statusCode === 409
              ? 'Dieser Entwurf wurde in einem anderen Fenster geändert. Eingaben bleiben erhalten. Bitte öffnen Sie das Formular erneut und prüfen Sie beide Stände.'
              : `Entwurf noch nicht auf dem Server gesichert. ${failure.message}`);
            setStatus('error');
          }
          throw failure;
        }
      }
    });
    // A background rejection must not become an unhandled browser error.
    chain.current.catch(() => {});
    return chain.current;
  }, [context, key, anchor, fieldSignature, identity]);

  useEffect(() => {
    generation.current += 1;
    sessionIdentity.current = identity;
    chain.current = Promise.resolve(); completing.current = false;
    active.current = true; ready.current = false; blocked.current = false;
    row.current = null; pending.current = null; latest.current = null;
    source.current = explicitSource || (initial?.id ? { kind: FORM_KINDS[context], id: initial.id, revision: initial.updated_at } : null);
    setRecovery(null); setError(''); setStatus(supported ? 'loading' : 'idle');
    if (!supported) return () => { active.current = false; };
    const controller = new AbortController();
    const buffer = readBuffer(key);
    const verifyLocalValues = async (existing, values, body, sibling = false) => {
      if (containsSecret(values)) { removeBuffer(key); throw new Error('Zugangsdaten werden nicht im Entwurf gespeichert.'); }
      if (controller.signal.aborted) return null;
      const command = { id: sibling ? workspace.command() : existing.id, body: {
        ...body, values, base_revision: sibling ? 0 : existing.revision, idempotency_key: workspace.command(),
      }, sent: true };
      writeBuffer(key, { pending: command, values });
      const saved = await workspace.put('drafts', command.id, command.body);
      if (controller.signal.aborted) return null;
      writeBuffer(key, { row: saved, values: saved.values });
      return saved;
    };
    const load = async () => {
      for (const completionKey of completionBuffers(key)) {
        const completion = readBuffer(completionKey)?.completion_pending;
        if (!completion) continue;
        let saved = completion.row;
        if (completion.pending) saved = await workspace.put('drafts', completion.pending.id, completion.pending.body);
        if (controller.signal.aborted) return;
        if (saved) await workspace.remove('drafts', saved.id, {
          base_revision: saved.revision, idempotency_key: completion.deletion_key,
        });
        if (controller.signal.aborted) return;
        removeBuffer(completionKey);
      }
      if (buffer?.completion) {
        await workspace.remove('drafts', buffer.completion.id, buffer.completion.body);
        if (controller.signal.aborted) return;
        removeBuffer(key);
      }
      let found = null;
      let cursor;
      do {
        const page = await workspace.list('drafts', { context, form_key: formKey(fieldSignature), cursor }, { signal: controller.signal });
        found = page.items?.find(item => (item.source?.id || null) === (initial?.id || null)
          && (item.anchor?.id || null) === (anchor?.id || null)
          && (item.form_key === formKey(fieldSignature) || Object.keys(item.values || {}).sort().join('|') === fieldSignature));
        cursor = found ? null : page.next_cursor;
      } while (cursor);
      if (controller.signal.aborted) return;
      // An unacknowledged local command is retried byte-for-byte. The server checks
      // its source and owner again, including after a permission change.
      if (buffer?.pending) {
        try { found = await workspace.put('drafts', buffer.pending.id, buffer.pending.body); }
        catch (failure) {
          if (failure.statusCode === 403 || failure.statusCode === 404) { removeBuffer(key); throw failure; }
          if (failure.statusCode !== 409) throw failure;
          if (controller.signal.aborted) return;
          const server = await workspace.get('drafts', buffer.pending.id);
          const local = await verifyLocalValues(server, buffer.values || buffer.pending.body.values, buffer.pending.body, true);
          if (!local) return;
          found = { ...local, server_values: server.values };
          // Keep the two versions explicit; never replace another tab's draft.
          if (active.current) setError('Ein anderer Entwurfsstand liegt vor. Prüfen Sie die lokal wiedergefundenen Eingaben vor der Übernahme.');
        }
        if (controller.signal.aborted) return;
        if (found && !found.server_values && buffer.values && JSON.stringify(buffer.values) !== JSON.stringify(found.values)) {
          // Changes typed while the uncertain command was in flight are another
          // private write, checked for current reference permissions before display.
          found = await verifyLocalValues(found, buffer.values, buffer.pending.body);
        }
      }
      if (!buffer?.pending && found && buffer?.row?.id === found.id && buffer.row.revision === found.revision
          && buffer.values && JSON.stringify(buffer.values) !== JSON.stringify(found.values)) {
        const { context, mode, source, anchor, field_keys, form_key } = found;
        found = await verifyLocalValues(found, buffer.values, { context, mode, source, anchor, field_keys, form_key });
      }
      if (controller.signal.aborted) return;
      row.current = found;
      ready.current = true;
      if (found) {
        source.current = found.source;
        setRecovery(found);
        setStatus('recovery');
      } else { removeBuffer(key); setStatus('ready'); }
    };
    load().catch(failure => {
      if (controller.signal.aborted) return;
      setStatus('error'); setError(`Entwurfssicherung konnte nicht vorbereitet werden. ${failure.message}`);
    });
    const retry = () => { if (ready.current && !blocked.current) persist(); };
    const invalidate = () => { active.current = false; generation.current += 1; clearTimeout(timer.current); controller.abort(); };
    window.addEventListener('online', retry);
    window.addEventListener('workspace-logout', invalidate);
    return () => { invalidate(); window.removeEventListener('online', retry); window.removeEventListener('workspace-logout', invalidate); };
  // Each form session owns a writer; inline initial/fields objects must not reload it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, supported, attempt]);

  const stage = useCallback(values => {
    if (!supported || !active.current || currentIdentity.current !== identity || blocked.current || completing.current) return;
    const allowed = new Set(safeFields(fieldsRef.current).map(field => field.key));
    const cleaned = Object.fromEntries(Object.entries(values).filter(([field]) => allowed.has(field)));
    if (containsSecret(cleaned)) {
      setError('Zugangsdaten werden nicht im Entwurf gespeichert.'); setStatus('error'); return;
    }
    latest.current = cleaned;
    if (ready.current && !pending.current) {
      pending.current = { id: row.current?.id || workspace.command(), body: {
        base_revision: row.current?.revision || 0, idempotency_key: workspace.command(), context,
        mode: source.current ? 'edit' : 'create', source: source.current, anchor: anchor || null,
        field_keys: fieldSignature.split('|'), form_key: formKey(fieldSignature), values: cleaned,
      } };
      latest.current = null;
    }
    writeBuffer(key, { row: row.current, pending: pending.current, values: cleaned });
    setStatus('pending');
    clearTimeout(timer.current);
    timer.current = setTimeout(persist, 600);
  }, [supported, key, persist, context, anchor, fieldSignature, identity]);

  const clear = useCallback(async ({ completed = false } = {}) => {
    const epoch = generation.current;
    const current = () => active.current && currentIdentity.current === identity && generation.current === epoch;
    if (!current()) return;
    clearTimeout(timer.current);
    latest.current = null;
    completing.current = true;
    const deletionKey = workspace.command();
    const completionKey = `${key}:completion:${deletionKey}`;
    writeBuffer(completionKey, { completion_pending: {
      pending: pending.current?.sent ? pending.current : null, row: row.current, deletion_key: deletionKey, completed,
    } });
    // Explicit discard is durable before navigation can unmount this dialog.
    // An uncertain DELETE must never make its old pending edit recoverable again.
    removeBuffer(key);
    try {
      await chain.current.catch(() => {});
      if (!current()) return;
      if (pending.current?.sent) {
        const command = pending.current;
        const saved = await workspace.put('drafts', command.id, command.body);
        if (!current()) return;
        row.current = saved; pending.current = null;
      }
      if (row.current) {
        const command = { base_revision: row.current.revision, idempotency_key: deletionKey };
        await workspace.remove('drafts', row.current.id, command);
        if (!current()) return;
      }
      removeBuffer(completionKey);
    } finally {
      if (current()) {
        // New edits use a different draft even if private cleanup is offline.
        // The separate durable marker is drained before any recovery.
        row.current = null; pending.current = null; blocked.current = false; removeBuffer(key); setRecovery(null); setStatus(supported ? 'ready' : 'idle');
        completing.current = false;
      }
    }
    if (!current()) return;
    row.current = null; pending.current = null; blocked.current = false;
    removeBuffer(key); setRecovery(null); setStatus(supported ? 'ready' : 'idle');
  }, [key, supported, identity]);

  const resume = useCallback(async (values, sourceRevision, dependencyEtags) => {
    const epoch = generation.current;
    const current = () => active.current && currentIdentity.current === identity && generation.current === epoch;
    if (!current() || !row.current) return;
    if (sourceRevision && (row.current.source || row.current.anchor) && (
      sourceRevision !== (row.current.source?.revision || row.current.anchor_revision) || row.current.source_state?.status === 'changed')) {
      const saved = await workspace.rebase(row.current.id, {
        base_revision: row.current.revision, idempotency_key: workspace.command(),
        source_revision: sourceRevision, dependency_etags: dependencyEtags, values,
      });
      if (!current()) return;
      row.current = saved;
    }
    source.current = row.current.source;
    setRecovery(null); setStatus('saved');
  }, [identity]);
  const sessionMatches = sessionIdentity.current === identity;
  return { enabled: supported, status: sessionMatches ? status : supported ? 'loading' : 'idle',
    error: sessionMatches ? error : '', recovery: sessionMatches ? recovery : null, stage, flush: persist, clear, resume,
    resetSource: next => { if (!row.current && !pending.current) source.current = next; },
    ready: sessionMatches && ready.current, retry: () => ready.current && !blocked.current ? persist().catch(() => {}) : setAttempt(value => value + 1),
    sourceRevision: sessionMatches ? source.current?.revision || row.current?.anchor_revision : null, sessionKey: identity,
    isCurrent: token => active.current && currentIdentity.current === token && token === identity };
}
