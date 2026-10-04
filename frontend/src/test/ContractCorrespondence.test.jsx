import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ContractCorrespondence from '../components/ContractCorrespondence';
import ContractLifecycle from '../components/ContractLifecycle';
import { bindEditRevision } from '../editRevision';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const m = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), blob: vi.fn(), confirm: vi.fn(), user: null,
  write: true, documents: true, locale: 'de', records: new Map(), events: [], templates: [], etag: '"source-1"', sourceState: 'current' }));
vi.mock('../api', () => ({ api: { get: m.get, post: m.post, getBlob: m.blob } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: m.user, canWrite: endpoint => m.write && (endpoint !== '/documents' || m.documents) }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => m.confirm }));
const languages = { de, en, es };
const tr = key => key.split('.').reduce((value, part) => value?.[part], languages[m.locale]) ?? key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: tr }) }));
const C = { id: 'contract-1', property_id: 'property-1', unit_id: 'unit-1', tenant_id: 'tenant-1',
  contract_number: 'MV-1', start_date: '2020-01-01', end_date: '2027-12-31', status: 'active', notice_period: 'Not a legal date', updated_at: '2026-10-02T11:12:13.123456' };
const data = { letter_date: '2026-10-02', deadline_date: '2026-10-31', deadline_basis: 'Personally checked management date',
  deadline_confirmed: true, recipient_name: 'Synthetic Recipient', recipient_address: 'Synthetic Address\n12345 Example',
  subject: 'Synthetic letter', body: 'Original reviewed text', template_id: null, lifecycle_command_id: null };
const source = () => bindEditRevision({ ...C }, { collection: 'contracts', id: C.id, path: '/contracts/contract-1',
  updatedAt: C.updated_at, etag: m.etag, source: { ...C } });
const review = (content = data) => ({ data: { ...content }, source_contract: { ...C }, source_contract_etag: m.etag,
  source_context: { portfolio_id: 'portfolio-1', property_etag: '"p"', unit_etag: '"u"', tenant_etag: '"t"', names: { contract_number: C.contract_number } },
  template: content.template_id ? { id: content.template_id, root_id: 'root-1', title: 'Template one', version: 1, body_sha256: 'c'.repeat(64) } : null,
  lifecycle: null, rendered_body: content.body || 'Rendered template text', pdf_sha256: 'b'.repeat(64) });
function row(options = {}) {
  const state = options.state || 'draft', content = options.data || data;
  return { id: 'letter-1', contract_id: C.id, property_id: C.property_id, unit_id: C.unit_id, tenant_id: C.tenant_id,
    portfolio_id: 'portfolio-1', actor_id: 'actor-1', revision: '11111111-1111-1111-1111-111111111111', state, data: { ...content },
    source_contract_etag: m.etag, current_contract_etag: m.etag, source_review_status: state === 'draft' ? 'not_reviewed' : m.sourceState,
    review: state === 'draft' ? null : review(content), review_hash: state === 'draft' ? null : 'a'.repeat(64),
    document_id: state === 'approved' ? 'document-1' : null, document_version_id: state === 'approved' ? 'version-1' : null,
    approved_at: state === 'approved' ? '2026-10-02T12:00:00+00:00' : null,
    created_at: '2026-10-02T10:00:00+00:00', persistent: true, delivery_policy: 'manual_observation_only',
    download_url: 'https://foreign.example.test/never-authorize', ...options };
}
const page = (items = [], next = null) => ({ items, next_before: next, has_more: Boolean(next), persistent: true });
const event = (options = {}) => ({ id: 'event-1', event_revision: 1, actor_id: 'actor-1', created_at: '2026-10-02T13:00:00+00:00',
  policy: 'manual_observation_only', data: { kind: 'dispatched', event_date: '2026-10-02', channel: 'post', reference: 'Synthetic dispatch proof',
    note: 'Actually observed', confirmed: true, dispatch_event_id: null }, ...options });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const error = (code, message = 'Synthetic server detail') => Object.assign(new Error(message), { statusCode: code });
const text = name => tr(`contractCorrespondence.${name}`);
const button = name => screen.getByRole('button', { name: text(name), exact: true });
const click = name => fireEvent.click(button(name));
async function ready() { await waitFor(() => expect(screen.queryByText(text('loading'))).not.toBeInTheDocument()); }
async function selectOwn() {
  click('drafts'); fireEvent.click(screen.getByRole('button', { name: /Synthetic letter/ }));
  await waitFor(() => expect(screen.getByLabelText(text('subject'))).toHaveValue('Synthetic letter'));
}
async function selectApproved() {
  fireEvent.click(screen.getByRole('button', { name: /Synthetic letter/ }));
  await waitFor(() => expect(screen.getByRole('heading', { name: text('events') })).toBeInTheDocument());
}
function install() {
  m.get.mockImplementation(async path => {
    if (path === '/contracts/contract-1') return source();
    if (path === '/properties/property-1') return { id: 'property-1', portfolio_id: 'portfolio-1' };
    if (path.startsWith('/contract-wizard/templates?')) {
      const offset = Number(new URLSearchParams(path.split('?')[1]).get('offset'));
      return { items: m.templates.slice(offset, offset + 25), total: m.templates.length, limit: 25, offset };
    }
    if (path.startsWith('/contracts/contract-1/lifecycle/')) return { items: [], next_before: null, persistent: true };
    if (path.includes('/events?limit=')) return { items: m.events, event_revision: Math.max(0, ...m.events.map(item => item.event_revision)), next_before: null,
      document_version_id: 'version-1', policy: 'manual_observation_only' };
    if (path.includes('/correspondence/drafts?')) return page([...m.records.values()].filter(item => item.actor_id === m.user.id));
    if (path.includes('/correspondence/history?')) return page([...m.records.values()].filter(item => item.state === 'approved'));
    if (path.includes('/correspondence/deadlines?')) return page([...m.records.values()].filter(item => item.state === 'approved').map(item => ({
      id: item.id, contract_id: C.id, date: item.data.deadline_date, basis: item.data.deadline_basis, review_hash: item.review_hash,
      source_review_status: item.source_review_status, policy: 'user_confirmed_management_date' })));
    if (path.includes('/correspondence/drafts/')) return m.records.get(decodeURIComponent(path.split('/').at(-1)));
    throw new Error(`Unexpected GET ${path}`);
  });
  m.post.mockImplementation(async (path, payload) => {
    if (path === '/contract-wizard/templates') {
      const found = { ...payload, id: 'template-1', root_id: 'root-1', version: 1 };
      m.templates.push(found); return found;
    }
    const old = m.records.get(path.split('/').at(-2)) || row();
    const content = payload.data || old.data;
    const state = path.endsWith('/approve') || path.endsWith('/events') ? 'approved' : path.endsWith('/review') ? 'reviewed' : 'draft';
    const found = row({ id: old.id, data: content, state, actor_id: old.actor_id,
      revision: '22222222-2222-2222-2222-222222222222' });
    if (path.endsWith('/events')) {
      const eventRevision = payload.expected_event_revision + 1;
      found.event = event({ id: `event-${eventRevision}`, event_revision: eventRevision, data: payload });
      m.events.unshift(found.event);
    }
    m.records.set(found.id, found);
    // Command receipts contain immutable command evidence, not live source flags.
    const { current_contract_etag: _current, source_review_status: _status, ...receipt } = found;
    return receipt;
  });
}
beforeEach(() => {
  vi.clearAllMocks(); m.user = { id: 'actor-1', role: 'verwalter', is_active: true, portfolio_access: 'selected', portfolio_ids: ['portfolio-1'], write_permissions: ['rental'] };
  m.write = true; m.documents = true; m.locale = 'de'; m.etag = '"source-1"'; m.sourceState = 'current'; m.records = new Map(); m.templates = []; m.events = [];
  m.confirm.mockResolvedValue(true); install();
  URL.createObjectURL = vi.fn(() => 'blob:synthetic'); URL.revokeObjectURL = vi.fn();
});

describe('manual contract correspondence', () => {
  it('requires explicit dates and management confirmation, preserving the exact body', async () => {
    render(<ContractCorrespondence contract={C} />); await ready(); click('drafts');
    expect(screen.getByLabelText(text('deadline_date'))).toHaveValue('');
    for (const name of ['letter_date', 'deadline_date', 'deadline_basis', 'recipient_name', 'recipient_address', 'subject', 'body']) {
      fireEvent.change(screen.getByLabelText(text(name)), { target: { value: name === 'body' ? '  Original text\n' : data[name] } });
    }
    click('saveDraft'); await screen.findByRole('alert'); expect(m.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(text('deadlineConfirmed'))); click('saveDraft');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(1));
    expect(m.post.mock.calls[0][1]).toMatchObject({ expected_contract_etag: '"source-1"', data: { ...data, body: '  Original text\n' } });
    expect(m.post.mock.calls[0][1].idempotency_key).toMatch(/^g06-letter:/);
  });

  it('saves, reviews and approves only after fresh consent and a separate confirmation', async () => {
    m.records.set('letter-1', row()); render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    click('review'); await screen.findByRole('heading', { name: text('reviewTitle') });
    expect(button('approve')).toBeDisabled();
    fireEvent.click(screen.getByLabelText(text('approveConsent'))); click('approve');
    await screen.findByText(text('immutable')); expect(m.confirm).toHaveBeenCalledWith(text('approvePrompt'));
    const call = m.post.mock.calls.find(([path]) => path.endsWith('/approve'));
    expect(call[1]).toMatchObject({ confirmed: true, reviewed_hash: 'a'.repeat(64), expected_revision: '22222222-2222-2222-2222-222222222222' });
    expect(m.post.mock.calls.every(([path]) => !/smtp|send-email/.test(path))).toBe(true);
  });

  it('local edits invalidate consent; a successful edit removes the prior review', async () => {
    m.records.set('letter-1', row({ state: 'reviewed' })); render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.click(screen.getByLabelText(text('approveConsent')));
    fireEvent.change(screen.getByLabelText(text('subject')), { target: { value: 'Edited subject' } });
    expect(screen.getByLabelText(text('approveConsent'))).not.toBeChecked(); expect(button('approve')).toBeDisabled(); expect(button('review')).toBeDisabled();
    click('saveChanges'); await waitFor(() => expect(screen.queryByRole('heading', { name: text('reviewTitle') })).not.toBeInTheDocument());
    expect(m.post.mock.calls[0][1].data.subject).toBe('Edited subject');
  });

  it('freezes an unknown command and retries the exact key, body and expected revision', async () => {
    m.records.set('letter-1', row()); const savedPost = m.post.getMockImplementation();
    m.post.mockRejectedValueOnce(error(503)).mockImplementation(savedPost);
    render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.change(screen.getByLabelText(text('subject')), { target: { value: 'Lost response' } }); click('saveChanges');
    await screen.findByText(text('unknown')); expect(screen.getByLabelText(text('subject'))).toBeDisabled();
    const original = m.post.mock.calls[0][1]; click('retryExact');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(2)); expect(m.post.mock.calls[1][1]).toEqual(original);
    await waitFor(() => expect(screen.queryByText(text('unknown'))).not.toBeInTheDocument());
  });

  it('does not treat a failed refresh after acknowledgement as an unknown command', async () => {
    m.records.set('letter-1', row()); const get = m.get.getMockImplementation(); let block = false;
    m.get.mockImplementation(path => block && path === '/contracts/contract-1' ? Promise.reject(error(500)) : get(path));
    const post = m.post.getMockImplementation(); m.post.mockImplementation(async (...args) => { const value = await post(...args); block = true; return value; });
    render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn(); click('saveChanges');
    await screen.findByRole('alert'); expect(screen.queryByText(text('unknown'))).not.toBeInTheDocument();
    expect(m.post).toHaveBeenCalledTimes(1); expect(button('reload')).toBeEnabled();
  });

  it('preserves edited values across a CAS conflict and adopts fresh explicit source/revision', async () => {
    m.records.set('letter-1', row()); const post = m.post.getMockImplementation(); m.post.mockRejectedValueOnce(error(412)).mockImplementation(post);
    render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.change(screen.getByLabelText(text('subject')), { target: { value: 'Keep my subject' } }); click('saveChanges');
    await screen.findByRole('alert'); m.etag = '"source-2"'; m.records.set('letter-1', row({ revision: '33333333-3333-3333-3333-333333333333' }));
    click('reloadConflict'); await waitFor(() => expect(button('saveChanges')).toBeEnabled());
    expect(screen.getByLabelText(text('subject'))).toHaveValue('Keep my subject'); click('saveChanges');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(2)); expect(m.post.mock.calls[1][1]).toMatchObject({
      expected_contract_etag: '"source-2"', expected_revision: '33333333-3333-3333-3333-333333333333', data: { subject: 'Keep my subject' } });
    expect(m.post.mock.calls[1][1].idempotency_key).not.toBe(m.post.mock.calls[0][1].idempotency_key);
  });

  it('blocks duplicate commands while the first response is pending', async () => {
    m.records.set('letter-1', row()); const delayed = pending(); m.post.mockReturnValueOnce(delayed.promise);
    const busy = vi.fn(); const view = render(<ContractCorrespondence contract={C} onBusyChange={busy} />); await ready(); await selectOwn();
    click('saveChanges'); click('saveChanges'); await waitFor(() => expect(m.post).toHaveBeenCalledTimes(1));
    expect(busy).toHaveBeenLastCalledWith(true); view.unmount();
    expect(m.post.mock.calls[0][2].signal.aborted).toBe(true); expect(busy).toHaveBeenLastCalledWith(false);
    await act(async () => delayed.resolve(row()));
  });

  it.each(['property_id', 'unit_id', 'tenant_id'])('rejects foreign reviewed %s before displaying its content', async name => {
    const found = row({ state: 'reviewed' }); found.review.source_contract[name] = 'foreign'; found.review.rendered_body = 'FOREIGN SECRET'; m.records.set(found.id, found);
    render(<ContractCorrespondence contract={C} />); await screen.findByRole('alert');
    expect(screen.queryByText('FOREIGN SECRET')).not.toBeInTheDocument(); expect(m.post).not.toHaveBeenCalled();
  });

  it('rejects a reviewed data mismatch regardless of JSON key ordering', async () => {
    const found = row({ state: 'reviewed' }); found.review.data.subject = 'Foreign subject'; m.records.set(found.id, found);
    render(<ContractCorrespondence contract={C} />); await screen.findByRole('alert'); expect(screen.queryByText('Foreign subject')).not.toBeInTheDocument();
  });

  it('allows readonly approved history from another actor without any write controls', async () => {
    m.write = false; m.user.role = 'readonly'; m.records.set('letter-1', row({ state: 'approved', actor_id: 'other-actor' }));
    render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved();
    expect(button('download')).toBeEnabled(); expect(screen.queryByRole('button', { name: text('recordEvent') })).not.toBeInTheDocument();
    click('drafts'); expect(screen.queryByRole('button', { name: text('saveDraft') })).not.toBeInTheDocument(); expect(m.post).not.toHaveBeenCalled();
  });

  it('forgets all private values on a server scope denial', async () => {
    m.records.set('letter-1', row()); render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    m.post.mockRejectedValueOnce(error(403, 'Access revoked')); click('saveChanges'); await screen.findByText('Access revoked');
    expect(screen.queryByDisplayValue('Synthetic letter')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: /Synthetic letter/ })).not.toBeInTheDocument();
  });

  it('aborts late replies and starts a separate private context after an actor change', async () => {
    m.records.set('letter-1', row()); const view = render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    const delayed = pending(); m.post.mockReturnValueOnce(delayed.promise); click('saveChanges');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(1)); const signal = m.post.mock.calls[0][2].signal;
    m.user = { ...m.user, id: 'actor-2' }; m.records.clear(); view.rerender(<ContractCorrespondence contract={C} />); await ready();
    expect(signal.aborted).toBe(true); await act(async () => delayed.resolve(row()));
    expect(screen.queryByDisplayValue('Synthetic letter')).not.toBeInTheDocument(); expect(screen.queryByText(text('saved'))).not.toBeInTheDocument();
  });

  it.each([new Blob(['<html>error</html>'], { type: 'text/html' }), new Blob(['broken'], { type: 'application/pdf' })])('refuses a non-PDF response without downloading', async blob => {
    m.records.set('letter-1', row({ state: 'approved' })); m.blob.mockResolvedValueOnce(blob);
    render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved(); click('download');
    await screen.findByText(text('invalidDownload')); expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('constructs an authenticated document path from IDs and revokes its owned blob URL', async () => {
    m.records.set('letter-1', row({ state: 'approved' })); m.blob.mockResolvedValueOnce(new Blob(['%PDF-synthetic'], { type: 'application/pdf' }));
    const link = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const view = render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved(); click('download');
    await waitFor(() => expect(link).toHaveBeenCalledTimes(1));
    expect(m.blob.mock.calls[0][0]).toBe('/contracts/contract-1/correspondence/drafts/letter-1/download');
    view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:synthetic'); link.mockRestore();
  });

  it('blocks stale dispatch while retaining explicit receipt of an existing dispatch', async () => {
    m.sourceState = 'requires_review'; m.records.set('letter-1', row({ state: 'approved' })); m.events = [event()];
    render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved();
    expect(button('recordEvent')).toBeDisabled();
    fireEvent.change(screen.getByLabelText(text('eventKind')), { target: { value: 'received' } });
    fireEvent.change(screen.getByLabelText(text('dispatchReference')), { target: { value: 'event-1' } });
    for (const [field, value] of [['eventDate', '2026-10-03'], ['reference', 'Receipt proof'], ['note', 'Observed receipt']]) {
      fireEvent.change(screen.getByLabelText(text(field)), { target: { value } });
    }
    fireEvent.click(screen.getByLabelText(text('eventConsent'))); click('recordEvent');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(1));
    expect(m.post.mock.calls[0][1]).toMatchObject({ kind: 'received', dispatch_event_id: 'event-1', confirmed: true, expected_event_revision: 1 });
    expect(m.post.mock.calls[0][1]).not.toHaveProperty('expected_contract_etag');
  });

  it('changing an observation invalidates its explicit confirmation', async () => {
    m.records.set('letter-1', row({ state: 'approved' })); render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved();
    fireEvent.click(screen.getByLabelText(text('eventConsent')));
    fireEvent.change(screen.getByLabelText(text('note')), { target: { value: 'Different evidence' } });
    expect(screen.getByLabelText(text('eventConsent'))).not.toBeChecked(); expect(button('recordEvent')).toBeDisabled();
  });

  it('paginates templates with bounded requests and preserves an unlisted saved version', async () => {
    m.templates = Array.from({ length: 27 }, (_, index) => ({ id: `template-${index}`, root_id: `root-${index}`, portfolio_id: 'portfolio-1', version: 1, title: `Template ${index}`, body: 'Text' }));
    render(<ContractCorrespondence contract={C} />); await ready(); click('drafts');
    await waitFor(() => expect(screen.getByRole('option', { name: 'Template 0 · v1' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(text('template')), { target: { value: 'template-0' } }); click('nextTemplates');
    await waitFor(() => expect(screen.getByRole('option', { name: 'Template 26 · v1' })).toBeInTheDocument());
    expect(screen.getByLabelText(text('template'))).toHaveValue('template-0');
    expect(screen.getByRole('option', { name: text('savedTemplate') })).toBeInTheDocument();
    expect(m.get.mock.calls.some(([path]) => path.includes('offset=25&limit=25'))).toBe(true);
  });

  it('creates a new immutable template only after explicit confirmation and retains an unknown exact retry', async () => {
    const post = m.post.getMockImplementation(); m.post.mockRejectedValueOnce(error(500)).mockImplementation(post);
    render(<ContractCorrespondence contract={C} />); await ready(); click('drafts'); click('newTemplate');
    fireEvent.change(screen.getByLabelText(text('templateTitle')), { target: { value: 'My template' } });
    fireEvent.change(screen.getByLabelText(text('templateBody')), { target: { value: 'Dear {{tenant_name}}' } }); click('saveTemplate');
    await screen.findByRole('alert'); expect(m.confirm).toHaveBeenCalledWith(text('saveTemplateConfirm')); click('retryExact');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(2)); expect(m.post.mock.calls[1][1]).toEqual(m.post.mock.calls[0][1]);
    await waitFor(() => expect(screen.getByLabelText(text('template'))).toHaveValue('template-1'));
  });

  it.each(['de', 'en', 'es'])('renders translated controls and policy in %s', async locale => {
    m.locale = locale; render(<ContractCorrespondence contract={C} />); await ready(); click('drafts');
    expect(button('saveDraft')).toBeInTheDocument(); expect(screen.getByText(text('policy'))).toBeInTheDocument();
    click('newTemplate');
    await waitFor(() => expect(screen.getByLabelText(text('template'))).toBeEnabled());
    expect(screen.getByText(text('placeholders'))).toBeInTheDocument(); expect(document.body.textContent).not.toMatch(/contractCorrespondence\./);
  });

  it('retains a private letter across outer tabs and blocks dialog closing during a command', async () => {
    const onClose = vi.fn(), delayed = pending(); m.records.set('letter-1', row());
    render(<ContractLifecycle contract={C} onClose={onClose} />);
    await waitFor(() => expect(screen.queryByText(de.contractLifecycle.loading)).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: text('tab') })); await ready(); await selectOwn();
    fireEvent.change(screen.getByLabelText(text('subject')), { target: { value: 'Keep private letter' } });
    fireEvent.click(screen.getByRole('button', { name: de.contractLifecycle.historyTab }));
    fireEvent.click(screen.getByRole('button', { name: text('tab') })); expect(screen.getByLabelText(text('subject'))).toHaveValue('Keep private letter');
    m.post.mockReturnValueOnce(delayed.promise); click('saveChanges'); await waitFor(() => expect(m.post).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true');
    screen.getAllByRole('button', { name: de.contractLifecycle.close }).forEach(item => expect(item).toBeDisabled());
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' }); expect(onClose).not.toHaveBeenCalled();
    await act(async () => delayed.resolve(row({ data: { ...data, subject: 'Keep private letter' } })));
  });

  it('keeps navigation and input labels usable by keyboard', async () => {
    const user = userEvent.setup(); render(<ContractCorrespondence contract={C} />); await ready();
    button('drafts').focus(); await user.keyboard('{Enter}');
    expect(screen.getByLabelText(text('letter_date'))).toBeInTheDocument();
    screen.getByLabelText(text('recipient_name')).focus(); await user.type(screen.getByLabelText(text('recipient_name')), 'Keyboard Recipient');
    expect(screen.getByLabelText(text('recipient_name'))).toHaveValue('Keyboard Recipient'); expect(m.post).not.toHaveBeenCalled();
  });

  it('requires new approval consent when a reviewed revision is explicitly reloaded', async () => {
    m.records.set('letter-1', row({ state: 'reviewed' })); render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.click(screen.getByLabelText(text('approveConsent')));
    fireEvent.click(screen.getByRole('button', { name: /Synthetic letter/ }));
    await waitFor(() => expect(screen.getByLabelText(text('approveConsent'))).not.toBeChecked());
    expect(button('approve')).toBeDisabled();
  });

  it('explains the additional document publication permission while leaving drafting available', async () => {
    m.documents = false; m.records.set('letter-1', row({ state: 'reviewed' }));
    render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    expect(screen.getByText(text('documentPermission'))).toBeInTheDocument(); expect(button('approve')).toBeDisabled();
    expect(button('saveChanges')).toBeEnabled(); expect(button('review')).toBeEnabled(); expect(m.post).not.toHaveBeenCalled();
  });

  it('a dismissed confirmation sends no approval command', async () => {
    m.confirm.mockResolvedValue(false); m.records.set('letter-1', row({ state: 'reviewed' }));
    render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.click(screen.getByLabelText(text('approveConsent'))); click('approve');
    await waitFor(() => expect(button('approve')).toBeEnabled()); expect(m.confirm).toHaveBeenCalledTimes(1); expect(m.post).not.toHaveBeenCalled();
  });

  it('permission changes during the approval confirmation abort the command', async () => {
    const prompt = pending(); m.confirm.mockReturnValueOnce(prompt.promise); m.records.set('letter-1', row({ state: 'reviewed' }));
    const view = render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.click(screen.getByLabelText(text('approveConsent'))); click('approve'); await waitFor(() => expect(m.confirm).toHaveBeenCalledTimes(1));
    m.write = false; m.user = { ...m.user, write_permissions: [] }; view.rerender(<ContractCorrespondence contract={C} />);
    await act(async () => prompt.resolve(true)); await ready(); expect(m.post).not.toHaveBeenCalled();
  });

  it('an unknown approval can replay its historical result after the source has changed', async () => {
    m.records.set('letter-1', row({ state: 'reviewed' })); let result;
    m.post.mockImplementationOnce(async () => { result = row({ state: 'approved' }); m.records.set(result.id, result); throw error(500); })
      .mockImplementationOnce(async () => result);
    render(<ContractCorrespondence contract={C} />); await ready(); await selectOwn();
    fireEvent.click(screen.getByLabelText(text('approveConsent'))); click('approve'); await screen.findByText(text('unknown'));
    m.etag = '"source-new"'; m.records.set('letter-1', { ...result, current_contract_etag: m.etag, source_review_status: 'requires_review' });
    click('retryExact'); await screen.findByText(text('immutable'));
    expect(m.post.mock.calls[1][1]).toEqual(m.post.mock.calls[0][1]); expect(button('recordEvent')).toBeDisabled();
    expect(screen.getByText(text('requiresReview'))).toBeInTheDocument();
  });

  it('a delayed PDF after unmount cannot create a download', async () => {
    const delayed = pending(); m.blob.mockReturnValueOnce(delayed.promise); m.records.set('letter-1', row({ state: 'approved' }));
    const view = render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved(); click('download');
    await waitFor(() => expect(m.blob).toHaveBeenCalledTimes(1)); view.unmount();
    expect(m.blob.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => delayed.resolve(new Blob(['%PDF-synthetic'], { type: 'application/pdf' })));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('rejects a foreign management date on subsequent cursor pages', async () => {
    const get = m.get.getMockImplementation(); m.get.mockImplementation(path => {
      if (path.includes('/deadlines?')) return page([{ id: 'letter-1', contract_id: path.includes('before=') ? 'foreign-contract' : C.id,
        date: data.deadline_date, basis: 'Date evidence', review_hash: 'a'.repeat(64), policy: 'user_confirmed_management_date', source_review_status: 'current' }],
      path.includes('before=') ? null : 'opaque-next');
      return get(path);
    });
    render(<ContractCorrespondence contract={C} />); await ready(); click('deadlines'); click('nextPage');
    await screen.findByText(text('invalidResponse')); expect(m.get.mock.calls.some(([path]) => path.endsWith('before=opaque-next'))).toBe(true);
  });

  it('retains a first-page recovery path after switching a paged list to another tab', async () => {
    const get = m.get.getMockImplementation(); m.records.set('letter-1', row({ state: 'approved' }));
    m.get.mockImplementation(path => path.includes('/history?') ? Promise.resolve(page([row({ state: 'approved' })], path.includes('before=') ? null : 'next-cursor')) : get(path));
    render(<ContractCorrespondence contract={C} />); await ready(); click('nextPage');
    await waitFor(() => expect(button('firstPage')).toBeEnabled()); click('drafts'); click('history');
    expect(button('firstPage')).toBeEnabled(); click('firstPage'); await waitFor(() => expect(screen.queryByRole('button', { name: text('firstPage') })).not.toBeInTheDocument());
  });

  it('template editor Enter does not implicitly submit a letter', async () => {
    const user = userEvent.setup(); render(<ContractCorrespondence contract={C} />); await ready(); click('drafts'); click('newTemplate');
    await user.type(screen.getByLabelText(text('templateTitle')), 'Title{Enter}');
    expect(m.post).not.toHaveBeenCalled(); expect(screen.queryByText(text('completeFields'))).not.toBeInTheDocument();
  });

  it('template source denial clears private letter content as well', async () => {
    const get = m.get.getMockImplementation(); m.get.mockImplementation(path => path.startsWith('/contract-wizard/templates?') ? Promise.reject(error(403, 'Source rights revoked')) : get(path));
    m.records.set('letter-1', row()); render(<ContractCorrespondence contract={C} />); await ready(); click('drafts');
    await waitFor(() => expect(screen.queryByLabelText(text('subject'))).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Synthetic letter/ })).not.toBeInTheDocument(); expect(m.post).not.toHaveBeenCalled();
  });

  it('uses a deliberately selected new template predecessor after a conflict without losing edited text', async () => {
    m.templates = [1, 2].map(version => ({ id: `template-${version}`, root_id: 'root-1', portfolio_id: 'portfolio-1', version, title: 'Versioned template', body: `Text ${version}` }));
    const post = m.post.getMockImplementation(); m.post.mockRejectedValueOnce(error(409, 'Newer template exists')).mockImplementation(post);
    render(<ContractCorrespondence contract={C} />); await ready(); click('drafts');
    await waitFor(() => expect(screen.getByLabelText(text('template'))).toBeEnabled());
    fireEvent.change(screen.getByLabelText(text('template')), { target: { value: 'template-1' } }); click('newTemplateVersion');
    fireEvent.change(screen.getByLabelText(text('templateBody')), { target: { value: 'Keep my edited template' } }); click('saveTemplate');
    await screen.findByText('Newer template exists'); click('reloadSources');
    await waitFor(() => expect(screen.getByLabelText(text('template'))).toBeEnabled());
    fireEvent.change(screen.getByLabelText(text('template')), { target: { value: 'template-2' } }); click('usePredecessor');
    expect(screen.getByLabelText(text('templateBody'))).toHaveValue('Keep my edited template'); click('saveTemplate');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(2)); expect(m.post.mock.calls[1][1]).toMatchObject({ previous_id: 'template-2', body: 'Keep my edited template' });
  });

  it('retains template editing and its exact uncertain command across inner sections', async () => {
    const post = m.post.getMockImplementation(); m.post.mockRejectedValueOnce(error(500)).mockImplementation(post);
    render(<ContractCorrespondence contract={C} />); await ready(); click('drafts'); click('newTemplate');
    fireEvent.change(screen.getByLabelText(text('templateTitle')), { target: { value: 'Keep this template' } });
    fireEvent.change(screen.getByLabelText(text('templateBody')), { target: { value: 'Keep this source text' } });
    click('history'); click('drafts'); expect(screen.getByLabelText(text('templateBody'))).toHaveValue('Keep this source text'); click('saveTemplate');
    await screen.findByText(text('unknown')); const original = m.post.mock.calls[0][1];
    click('history'); click('drafts'); expect(button('saveDraft')).toBeDisabled(); click('retryExact');
    await waitFor(() => expect(m.post).toHaveBeenCalledTimes(2)); expect(m.post.mock.calls[1][1]).toEqual(original);
  });

  it('an event CAS refresh keeps evidence fields but requires renewed observation consent', async () => {
    m.records.set('letter-1', row({ state: 'approved' })); m.post.mockRejectedValueOnce(error(409, 'Event head changed'));
    render(<ContractCorrespondence contract={C} />); await ready(); await selectApproved();
    for (const [field, value] of [['eventDate', '2026-10-03'], ['reference', 'Keep this evidence'], ['note', 'Keep this observation']]) {
      fireEvent.change(screen.getByLabelText(text(field)), { target: { value } });
    }
    fireEvent.click(screen.getByLabelText(text('eventConsent'))); click('recordEvent'); await screen.findByText('Event head changed');
    m.events = [event()]; click('reloadConflict'); await waitFor(() => expect(screen.getByLabelText(text('eventConsent'))).toBeEnabled());
    expect(screen.getByLabelText(text('reference'))).toHaveValue('Keep this evidence');
    expect(screen.getByLabelText(text('note'))).toHaveValue('Keep this observation');
    expect(screen.getByLabelText(text('eventConsent'))).not.toBeChecked(); expect(button('recordEvent')).toBeDisabled();
  });

  it('offers effective read recovery when the configured page budget is smaller than 25', async () => {
    const get = m.get.getMockImplementation(); m.get.mockImplementation(path => path.includes('/correspondence/') && path.includes('limit=25')
      ? Promise.reject(error(422, 'Synthetic small page budget')) : get(path));
    render(<ContractCorrespondence contract={C} />); await screen.findByRole('alert'); click('smallPages'); await ready();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(m.get.mock.calls.some(([path]) => path === '/contracts/contract-1/correspondence/drafts?limit=1')).toBe(true);
    expect(m.post).not.toHaveBeenCalled();
  });

  it('budget 1 reaches another history page and its event list without changing the cursor', async () => {
    const get = m.get.getMockImplementation(); const first = row({ state: 'approved' });
    const second = row({ id: 'letter-2', state: 'approved', document_id: 'document-2', document_version_id: 'version-2', data: { ...data, subject: 'Second approved letter' } });
    m.records.set(first.id, first); m.records.set(second.id, second);
    m.get.mockImplementation(path => {
      if (path.includes('/correspondence/') && path.includes('limit=25')) return Promise.reject(error(422, 'Budget 1'));
      if (path.includes('/history?')) return Promise.resolve(path.includes('before=') ? page([second]) : page([first], 'opaque-cursor'));
      if (path.endsWith('/letter-2/events?limit=1')) return Promise.resolve({ items: [], event_revision: 0, next_before: null,
        document_version_id: 'version-2', policy: 'manual_observation_only' });
      return get(path);
    });
    render(<ContractCorrespondence contract={C} />); await screen.findByRole('alert'); click('smallPages'); await ready(); click('nextPage');
    await screen.findByRole('button', { name: /Second approved letter/ });
    expect(m.get.mock.calls.some(([path]) => path === '/contracts/contract-1/correspondence/history?limit=1&before=opaque-cursor')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Second approved letter/ }));
    await screen.findByRole('heading', { name: text('events') });
    expect(m.get.mock.calls.some(([path]) => path.endsWith('/letter-2/events?limit=1'))).toBe(true); expect(m.post).not.toHaveBeenCalled();
  });

  it('never offers the small-page recovery for a scope denial', async () => {
    const get = m.get.getMockImplementation(); m.get.mockImplementation(path => path.includes('/correspondence/drafts?')
      ? Promise.reject(error(403, 'Budget-independent denial')) : get(path));
    render(<ContractCorrespondence contract={C} />); await screen.findByText('Budget-independent denial');
    expect(screen.queryByRole('button', { name: text('smallPages') })).not.toBeInTheDocument();
    expect(m.get.mock.calls.some(([path]) => path.includes('limit=1'))).toBe(false); expect(m.post).not.toHaveBeenCalled();
  });

  it('aborts the explicit limit-1 recovery on unmount and ignores its late page', async () => {
    const get = m.get.getMockImplementation(), delayed = pending();
    m.get.mockImplementation(path => {
      if (path.includes('/correspondence/') && path.includes('limit=25')) return Promise.reject(error(422, 'Budget 1'));
      if (path.includes('/correspondence/history?limit=1')) return delayed.promise;
      return get(path);
    });
    const view = render(<ContractCorrespondence contract={C} />); await screen.findByRole('alert'); click('smallPages');
    await waitFor(() => expect(m.get.mock.calls.some(([path]) => path.includes('/history?limit=1'))).toBe(true));
    const signal = m.get.mock.calls.find(([path]) => path.includes('/history?limit=1'))[1].signal;
    view.unmount(); expect(signal.aborted).toBe(true); await act(async () => delayed.resolve(page([row({ state: 'approved' })])));
    expect(document.body.textContent).not.toContain('Synthetic letter'); expect(m.post).not.toHaveBeenCalled();
  });
});
