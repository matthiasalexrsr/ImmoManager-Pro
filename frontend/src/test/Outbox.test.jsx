import { webcrypto } from 'node:crypto';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Outbox from '../pages/Outbox';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), confirm: vi.fn(), role: 'buchhaltung', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-user', role: mocks.role } }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: key => key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key }) }));
const text = de.pages.outbox;
const snapshot = { recipient: 'tenant@test.invalid', sender_name: 'Synthetic sender', sender_address: 'sender@test.invalid',
  subject: 'Synthetic subject', body_text: 'Synthetic body <script>display as text</script>', reviewed_by: 'Synthetic reviewer' };
const entry = changes => ({ id: 'job-1', portfolio_id: 'portfolio', revision: 0, state: 'ready', attempt_no: 0, message_id: '<fixed@outbox.invalid>',
  created_at: '2026-10-01T12:00:00Z', snapshot, wire_size: 600, wire_sha256: 'a'.repeat(64), ...changes });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
let current;
const view = () => render(<MemoryRouter><Outbox /></MemoryRouter>);
const choose = async (labels = text) => {
  await screen.findByRole('option', { name: 'Synthetic portfolio' });
  fireEvent.change(screen.getByLabelText(labels.portfolio), { target: { value: 'portfolio' } });
  await screen.findByText('Synthetic subject');
};
const show = async (labels = text) => {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(labels.view) }));
  await screen.findByText('<fixed@outbox.invalid>');
  await waitFor(() => expect(screen.getByRole('button', { name: labels.reload })).toBeEnabled());
};
const compose = async () => {
  fireEvent.click(screen.getByRole('button', { name: text.compose }));
  const form = screen.getByRole('button', { name: text.saveReviewed }).closest('form');
  for (const [label, value] of [[text.recipient, snapshot.recipient], [text.subject, snapshot.subject], [text.reviewedBy, snapshot.reviewed_by], [text.body, snapshot.body_text]]) {
    fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  }
  fireEvent.click(within(form).getByLabelText(text.reviewConfirmation));
  return form;
};
beforeEach(() => {
  current = entry(); mocks.role = 'buchhaltung'; mocks.locale = 'de-DE';
  mocks.getAll.mockReset().mockResolvedValue([{ id: 'portfolio', name: 'Synthetic portfolio' }]);
  mocks.get.mockReset().mockImplementation(async path => path.endsWith('/configuration') ? { configured: true, enabled: true, sender_name: 'Synthetic sender', sender_address: 'sender@test.invalid' }
    : path.includes('/events?') ? { total: 0, items: [] } : path.includes('portfolio_id=') ? { total: 1, items: [current] } : current);
  mocks.post.mockReset().mockImplementation(async path => {
    current = entry({ state: path.endsWith('/send') ? 'sent' : 'ready', revision: path.endsWith('/send') ? 3 : 0, attempt_no: path.endsWith('/send') ? 1 : 0 });
    return current;
  });
  mocks.confirm.mockReset().mockResolvedValue(true);
  vi.stubGlobal('crypto', webcrypto);
});
afterEach(() => vi.unstubAllGlobals());

describe('durable manual SMTP outbox', () => {
  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('explains transport outcomes and explicit sending in %s', async (locale, catalog) => {
    mocks.locale = locale; const labels = catalog.pages.outbox;
    const { container } = view(); await choose(labels); await show(labels);
    expect(container).toHaveTextContent(labels.scope); expect(container).toHaveTextContent(labels.budget);
    expect(container.textContent).not.toMatch(/pages\.outbox\./);
    expect(screen.getByRole('link', { name: labels.messages })).toHaveAttribute('href', '/messages');
    expect(container.querySelector('script')).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('saves only reviewed content and does not send it automatically', async () => {
    view(); await choose(); const form = await compose(); fireEvent.submit(form);
    await screen.findByText('<fixed@outbox.invalid>');
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post.mock.calls[0][0]).toBe('/messages/outbox');
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ ...snapshot, portfolio_id: 'portfolio', review_confirmed: true });
    expect(mocks.confirm).not.toHaveBeenCalled();
  });

  it('content edits and reloading a changed sender require a new review while retaining the draft', async () => {
    view(); await choose(); const form = await compose();
    expect(within(form).getByLabelText(text.reviewConfirmation)).toBeChecked();
    fireEvent.change(within(form).getByLabelText(text.subject), { target: { value: 'Changed reviewed subject' } });
    expect(within(form).getByLabelText(text.reviewConfirmation)).not.toBeChecked();
    fireEvent.click(within(form).getByLabelText(text.reviewConfirmation));
    const existing = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(path => path.endsWith('/configuration') ? Promise.resolve({ configured: true, enabled: true, sender_address: 'new@test.invalid', sender_name: 'New sender' }) : existing(path));
    fireEvent.click(screen.getByRole('button', { name: text.refreshSmtp }));
    await waitFor(() => expect(within(form).getByLabelText(text.sender)).toHaveValue('New sender <new@test.invalid>'));
    expect(within(form).getByLabelText(text.body)).toHaveValue(snapshot.body_text);
    expect(within(form).getByLabelText(text.reviewConfirmation)).not.toBeChecked();
  });

  it('keeps reviewed draft and idempotency reference after rejection and prevents duplicate save', async () => {
    view(); await choose(); const form = await compose();
    const inFlight = pending(); mocks.post.mockReturnValueOnce(inFlight.promise);
    fireEvent.submit(form); fireEvent.submit(form);
    expect(mocks.post).toHaveBeenCalledTimes(1); expect(form).toHaveAttribute('aria-busy', 'true');
    await act(async () => inFlight.resolve(Promise.reject(new Error('422: message_too_large; split reviewed content'))));
    expect(await screen.findByRole('alert')).toHaveTextContent('message_too_large');
    expect(within(form).getByLabelText(text.body)).toHaveValue(snapshot.body_text);
    mocks.post.mockRejectedValueOnce(new Error('503: journal unavailable'));
    fireEvent.submit(form); await screen.findByText('503: journal unavailable');
    expect(mocks.post.mock.calls[0][1].idempotency_key).toBe(mocks.post.mock.calls[1][1].idempotency_key);
  });

  it('rejects malformed save response while retaining the complete draft', async () => {
    view(); await choose(); const form = await compose(); mocks.post.mockResolvedValueOnce({ status: 'ok' });
    fireEvent.submit(form); expect(await screen.findByRole('alert')).toHaveTextContent(text.malformed);
    expect(within(form).getByLabelText(text.body)).toHaveValue(snapshot.body_text);
    expect(screen.queryByText(text.acceptedHint)).not.toBeInTheDocument();
  });

  it('requires confirmation and one action while another send is pending', async () => {
    view(); await choose(); await show();
    const confirm = pending(); mocks.confirm.mockReturnValueOnce(confirm.promise);
    const button = screen.getByRole('button', { name: text.send });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.confirm).toHaveBeenCalledTimes(1); expect(mocks.post).not.toHaveBeenCalled();
    const send = pending(); mocks.post.mockReturnValueOnce(send.promise);
    await act(async () => confirm.resolve(true));
    expect(mocks.post).toHaveBeenCalledTimes(1); expect(button).toBeDisabled();
    current = entry({ state: 'sent', revision: 3, attempt_no: 1 });
    await act(async () => send.resolve(current));
    expect(await screen.findByText(text.acceptedHint)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.send })).not.toBeInTheDocument();
  });

  it('cancelling confirmation leaves the approved message unsent', async () => {
    view(); await choose(); await show(); mocks.confirm.mockResolvedValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: text.send }));
    await waitFor(() => expect(screen.getByRole('button', { name: text.send })).toBeEnabled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('unknown has no send action; documented retry only approves and requires a separate send', async () => {
    current = entry({ state: 'unknown', revision: 3, attempt_no: 1 });
    view(); await choose(); await show();
    expect(screen.getByRole('alert')).toHaveTextContent(text.unknownHint);
    expect(screen.queryByRole('button', { name: text.send })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(text.note), { target: { value: 'Synthetic provider investigation' } });
    mocks.post.mockImplementationOnce(async () => { current = entry({ revision: 4, attempt_no: 1 }); return current; });
    fireEvent.click(screen.getByRole('button', { name: text.saveDecision }));
    await screen.findByRole('button', { name: text.send });
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post.mock.calls[0][0]).toBe('/messages/outbox/job-1/decision');
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ action: 'retry', note: 'Synthetic provider investigation', expected_revision: 3 });
  });

  it('ready cancellation and failed retry send their actual fixed decision action', async () => {
    view(); await choose(); await show();
    fireEvent.change(screen.getByLabelText(text.note), { target: { value: 'Withdraw reviewed content' } });
    mocks.post.mockImplementationOnce(async () => { current = entry({ state: 'failed', revision: 1 }); return current; });
    fireEvent.click(screen.getByRole('button', { name: text.saveDecision }));
    await waitFor(() => expect(screen.getByLabelText(text.decisionAction)).toHaveValue('retry'));
    expect(mocks.post.mock.calls[0][1].action).toBe('cancel');
    fireEvent.change(screen.getByLabelText(text.note), { target: { value: 'Deliberately retry after provider check' } });
    fireEvent.click(screen.getByRole('button', { name: text.saveDecision }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1].action).toBe('retry');
  });

  it('readonly can read persisted preview and journal without mutation controls', async () => {
    mocks.role = 'readonly'; current = entry({ state: 'unknown', revision: 3 });
    view(); await choose(); await show();
    expect(screen.queryByRole('button', { name: text.compose })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.saveDecision })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.send })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('rights removed during confirmation block the later network command', async () => {
    const mounted = view(); await choose(); await show();
    const confirm = pending(); mocks.confirm.mockReturnValueOnce(confirm.promise);
    fireEvent.click(screen.getByRole('button', { name: text.send }));
    mocks.role = 'readonly'; mounted.rerender(<MemoryRouter><Outbox /></MemoryRouter>);
    await act(async () => confirm.resolve(true));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('loading an expired claim does not recover or resend it', async () => {
    current = entry({ state: 'claimed', revision: 2, attempt_no: 1, lease_until: '2026-10-01T10:00:00Z' });
    view(); await choose(); await show();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: text.recover })).toBeEnabled();
    expect(screen.queryByRole('button', { name: text.send })).not.toBeInTheDocument();
  });

  it('preserves server error details and decision note after a failed command', async () => {
    current = entry({ state: 'unknown', revision: 3 });
    view(); await choose(); await show();
    fireEvent.change(screen.getByLabelText(text.note), { target: { value: 'Synthetic investigation retained' } });
    mocks.post.mockRejectedValueOnce(new Error('412: outbox_revision_changed'));
    fireEvent.click(screen.getByRole('button', { name: text.saveDecision }));
    await waitFor(() => expect(screen.getAllByRole('alert').some(alert => alert.textContent.includes('outbox_revision_changed'))).toBe(true));
    expect(screen.getByLabelText(text.note)).toHaveValue('Synthetic investigation retained');
  });
});
