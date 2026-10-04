import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import { authMayWrite } from '../utils/writeAccess';

const endpoint = '/auth/users/me/form-drafts';
const signature = value => JSON.stringify(value);
const httpStatus = error => Number.isInteger(error?.statusCode) ? error.statusCode : null;
// Computed table/card rows can retain id+updated_at while losing the API's
// non-enumerable symbol. Their original timestamp remains authoritative; only
// the explicit editor collection is added, never a fresh server revision.
const revisionData = (revision, collection) => revision ? { collection,
  ...Object.fromEntries(['collection', 'id', 'updatedAt', 'etag', 'path']
    .filter(key => revision[key] != null).map(key => [key, revision[key]])) } : null;
const query = value => `${endpoint}?${new URLSearchParams(Object.entries(value).filter(([, item]) => item != null))}`;
const safeFields = fields => fields.filter(field => field.type !== 'password' && field.type !== 'file' && field.draft !== false);
const pick = (values, fields) => Object.fromEntries(safeFields(fields).map(field => [field.key, values?.[field.key] ?? field.default ?? '']));

/** Opt-in storage only. No business API is ever invoked by this hook. */
export default function useFormDraft({ config, fields, values, original, editRevision, onRestore }) {
  const auth = useAuth();
  const { t } = useTranslation();
  const text = useRef(t);
  useLayoutEffect(() => { text.current = t; }, [t]);
  const enabled = Boolean(config?.collection && auth?.user?.id && authMayWrite(auth, '/' + config.collection));
  const userSignature = signature([auth?.user?.id, auth?.user?.role, auth?.user?.portfolio_access, [...(auth?.user?.portfolio_ids || [])].sort()]);
  const identity = { collection: config?.collection, entity_id: original.current?.id || null, form_key: config?.formKey || 'crud', owner_id: auth?.user?.id };
  const identitySignature = enabled ? signature([identity, userSignature]) : '';
  const schema = signature(safeFields(fields).map(field => [field.key, field.type || 'text']).sort((a, b) => a[0].localeCompare(b[0])));
  const [state, setState] = useState({ status: 'disabled', draft: null, error: null, errorStatus: null });
  const current = useRef(null);
  const lifecycle = useRef(null);
  const listener = useRef(onRestore);
  const timer = useRef(null);
  useLayoutEffect(() => {
    current.current = { enabled, identity, key: identitySignature, schema, fields, values, original, editRevision, snapshotFields: config?.snapshotFields || [] };
    listener.current = onRestore;
  });
  const active = useCallback(session => lifecycle.current === session && session.key === current.current?.key && !session.closed, []);
  const publish = useCallback((session, next) => {
    if (active(session)) setState(previous => ({ ...previous,
      ...(Object.hasOwn(next, 'error') && next.error === null ? { errorStatus: null } : {}), ...next }));
  }, [active]);

  const load = useCallback(async () => {
    const input = current.current;
    if (!input?.enabled) return;
    const session = lifecycle.current;
    if (!active(session)) return;
    session.controller?.abort();
    const controller = new AbortController();
    session.controller = controller;
    publish(session, { status: 'loading', error: null });
    try {
      const result = await api.get(query(input.identity), { signal: controller.signal });
      if (!active(session) || controller.signal.aborted) return;
      if (!result || !Object.hasOwn(result, 'draft') || result.draft && typeof result.draft.revision !== 'string') throw new Error(text.current('formDraft.invalidResponse'));
      session.revision = result.draft?.revision || null;
      session.pending = result.draft || null;
      session.blocked = Boolean(result.draft);
      session.loaded = true;
      publish(session, { status: result.draft ? 'available' : 'ready', draft: result.draft, error: null });
    } catch (error) {
      if (!active(session) || controller.signal.aborted || error.name === 'AbortError') return;
      session.loaded = false;
      publish(session, { status: 'error', error: error.message || text.current('formDraft.failed'), errorStatus: httpStatus(error) });
    }
  }, [active, publish]);

  useEffect(() => {
    clearTimeout(timer.current);
    if (!enabled) { lifecycle.current = null; setState({ status: 'disabled', draft: null, error: null, errorStatus: null }); return; }
    const session = { key: identitySignature, revision: null, blocked: true, loaded: false, closed: false,
      inFlight: null, pending: null, baseline: signature(pick(current.current.original.current, current.current.fields)), last: null, submitted: false };
    lifecycle.current = session;
    void load();
    return () => { session.closed = true; session.controller?.abort(); clearTimeout(timer.current); };
  }, [enabled, identitySignature, load]);

  const save = useCallback(async ({ force = false, submitting = false } = {}) => {
    clearTimeout(timer.current);
    const session = lifecycle.current;
    if (!current.current?.enabled) return true;
    if (!active(session) || !session.loaded || session.blocked) return false;
    if (session.submitted && !submitting && !force) return false;
    if (session.inFlight) {
      await session.inFlight;
      return save({ force, submitting });
    }
    const input = current.current;
    const nextValues = pick(input.values, input.fields);
    const fingerprint = signature(nextValues);
    if (!force && (fingerprint === session.last || !session.revision && fingerprint === session.baseline)) return true;
    const data = { ...input.identity, expected_revision: session.revision, schema: input.schema, values: nextValues,
      original_values: { ...pick(input.original.current, input.fields), ...Object.fromEntries(input.snapshotFields.map(key => [key, input.original.current?.[key] ?? null])) },
      edit_revision: revisionData(input.editRevision.current, input.identity.collection), submission_pending: submitting };
    publish(session, { status: 'saving', error: null });
    const operation = (async () => {
      try {
        const result = await api.put(endpoint, data);
        if (!active(session)) return false;
        if (typeof result?.revision !== 'string' || !result.updated_at || !result.expires_at) throw new Error(text.current('formDraft.invalidResponse'));
        session.revision = result.revision;
        session.last = fingerprint;
        session.submitted = submitting;
        publish(session, { status: submitting ? 'pending' : 'saved', draft: { ...data, ...result }, error: null });
        return true;
      } catch (error) {
        if (!active(session)) return false;
        if (error.code === 'DRAFT_CONFLICT' || error.statusCode === 409) session.blocked = true;
        publish(session, { status: error.statusCode === 409 ? 'conflict' : 'error', error: error.message || text.current('formDraft.failed'), errorStatus: httpStatus(error) });
        return false;
      } finally { session.inFlight = null; }
    })();
    session.inFlight = operation;
    return operation;
  }, [active, publish]);

  const valueSignature = signature(values);
  useEffect(() => {
    const session = lifecycle.current;
    if (!enabled || !session?.loaded || session.blocked || session.submitted || !['ready', 'saved', 'restored'].includes(state.status)) return;
    const input = current.current;
    const value = signature(pick(input.values, input.fields));
    if (value === session.last || !session.revision && value === session.baseline) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { void save(); }, 650);
    return () => clearTimeout(timer.current);
  }, [enabled, valueSignature, schema, state.status, save]);

  const discard = useCallback(async () => {
    const session = lifecycle.current;
    if (!active(session) || session.inFlight) return false;
    clearTimeout(timer.current);
    if (!session.revision) return true;
    publish(session, { status: 'discarding', error: null });
    try {
      await api.del(query({ ...current.current.identity, expected_revision: session.revision }));
      if (!active(session)) return false;
      session.revision = null; session.pending = null; session.blocked = false; session.submitted = false;
      // Discard keeps the current screen values; they are not silently written
      // back immediately. A subsequent actual field change starts new work.
      session.last = signature(pick(current.current.values, current.current.fields));
      publish(session, { status: 'ready', draft: null, error: null });
      return true;
    } catch (error) {
      if (active(session)) publish(session, { status: error.statusCode === 409 ? 'conflict' : 'error', error: error.message || text.current('formDraft.failed'), errorStatus: httpStatus(error) });
      return false;
    }
  }, [active, publish]);

  const restore = useCallback(async () => {
    const session = lifecycle.current;
    if (!active(session) || !session.pending || session.pending.schema !== current.current.schema) return false;
    // Re-read permissions and stored revision on the explicit restore action.
    try {
      const result = await api.get(query(current.current.identity));
      if (!active(session)) return false;
      if (!result.draft || result.draft.revision !== session.pending.revision) { await load(); return false; }
      const draft = result.draft;
      const keys = safeFields(current.current.fields).map(field => field.key);
      if (!draft.values || !draft.original_values || Object.keys(draft.values).some(key => !keys.includes(key))) throw new Error(text.current('formDraft.invalidResponse'));
      listener.current?.(draft);
      session.pending = null; session.blocked = false; session.submitted = Boolean(draft.submission_pending);
      session.last = null; session.baseline = signature(draft.original_values);
      publish(session, { status: 'restored', draft, error: null });
      return true;
    } catch (error) { publish(session, { status: 'error', error: error.message || text.current('formDraft.failed'), errorStatus: httpStatus(error) }); return false; }
  }, [active, load, publish]);

  const prepareSubmit = useCallback(() => save({ force: true, submitting: true }), [save]);
  const failedSubmit = useCallback(async error => {
    const session = lifecycle.current;
    if (!active(session) || !session.submitted) return;
    if (error.statusCode && error.statusCode < 500) await save({ force: true, submitting: false });
    else publish(session, { status: 'uncertain', error: text.current('formDraft.uncertain'), errorStatus: httpStatus(error) });
  }, [active, publish, save]);
  const resume = useCallback(async () => {
    const session = lifecycle.current;
    if (!active(session)) return false;
    return save({ force: true, submitting: false });
  }, [active, save]);
  return { enabled, ...state, status: enabled && state.status === 'disabled' ? 'loading' : state.status,
    schemaMatches: !state.draft || state.draft.schema === schema,
    restore, discard, retry: () => lifecycle.current?.loaded && !lifecycle.current?.blocked
      ? save({ force: true, submitting: Boolean(lifecycle.current.submitted) }) : load(),
    inspect: load, flush: save, prepareSubmit, failedSubmit, resume, complete: discard };
}
