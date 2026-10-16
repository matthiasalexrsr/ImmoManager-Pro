import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ChannelPanel from '../features/channels/ChannelPanel';
import MarketingPanel from '../features/channels/MarketingPanel';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true }));
const source = name => ({ source_sha256: 'a'.repeat(64), asset_count: 0, snapshot: { context: { title: name }, assets: [] } });
const record = { id: 'post-1', revision: 1, channel: 'post', state: 'prepared', source_id: 'a', progress: {}, snapshot: {
  parameters: { recipient_name: 'Mia', street: 'Prüfweg 1', postcode: '01099', city: 'Dresden' }, originals: [{ name: 'Brief.pdf' }],
} };
beforeEach(() => { vi.clearAllMocks(); api.captureSession.mockReturnValue(() => {}); });
afterEach(cleanup);

it('keeps late source A out of source B and preserves German input on failure', async () => {
  let resolveA;
  api.get.mockImplementation(path => {
    if (path.includes('/a/post/preview')) return new Promise(resolve => { resolveA = resolve; });
    if (path.includes('/post/preview')) return Promise.resolve(source('Brief B'));
    return Promise.resolve({ items: [], next_cursor: null });
  });
  const view = render(<ChannelPanel sourceId="a" mode="post" />);
  view.rerender(<ChannelPanel key="b" sourceId="b" mode="post" />);
  await screen.findByText(/Brief B/);
  await act(async () => resolveA(source('PRIVATER BRIEF A')));
  expect(screen.queryByText(/PRIVATER BRIEF A/)).toBeNull();
  fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 'Mia Muster' } });
  api.post.mockRejectedValue(new Error('Synthetischer Verbindungsfehler'));
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl prüfen und Vorgang vorbereiten' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Empfänger').value).toBe('Mia Muster');
  const first = api.post.mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl prüfen und Vorgang vorbereiten' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1][1].idempotency_key).toBe(first.idempotency_key);
});

it('requires the actually supplied purchased original before a posted action appears', async () => {
  api.get.mockImplementation(path => Promise.resolve(path.includes('/preview') ? source('Brief') : { items: [record] }));
  render(<ChannelPanel sourceId="a" mode="post" />);
  await screen.findByText('Vorbereitet');
  expect(screen.queryByRole('button', { name: 'Tatsächlichen manuellen Einwurf bestätigen' })).toBeNull();
  const attach = screen.getByRole('button', { name: 'Kaufbeleg zuordnen' }); expect(attach.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Dokument-ID des tatsächlich gekauften Frankaturoriginals'), { target: { value: 'purchased-original' } });
  fireEvent.change(screen.getByLabelText('Kaufreferenz'), { target: { value: 'K-731' } });
  fireEvent.click(screen.getByLabelText(/Dies ist das tatsächlich gekaufte Frankaturoriginal/));
  api.post.mockResolvedValue({ ...record, revision: 2, state: 'franked' });
  fireEvent.click(attach);
  await screen.findByRole('button', { name: 'Tatsächlichen manuellen Einwurf bestätigen' });
  expect(api.post.mock.calls[0][1].parameters).toEqual({ document_id: 'purchased-original', purchase_reference: 'K-731', purchased_original_confirmed: true });
});

it('does not apply a response after the session fence rejects it', async () => {
  let resolve;
  api.get.mockImplementation(path => path.includes('/preview') ? new Promise(done => { resolve = done; }) : Promise.resolve({ items: [] }));
  api.captureSession.mockReturnValue(() => { throw new Error('Sitzung gewechselt'); });
  render(<ChannelPanel sourceId="a" mode="post" />);
  await act(async () => resolve(source('PRIVATER ALTINHALT')));
  expect(screen.queryByText(/PRIVATER ALTINHALT/)).toBeNull();
});

it('offers the local expose and lead workflow without any provider connection', async () => {
  api.get.mockImplementation(path => Promise.resolve(path.endsWith('/marketing') ? { leads: [], viewings: [], contracts: [], confirmations: [] } : source('Lokale Wohnung')));
  render(<MarketingPanel listingId="local" />);
  await screen.findByRole('button', { name: 'Exposé als PDF herunterladen' });
  fireEvent.change(screen.getByLabelText('Neuer Interessent'), { target: { value: 'Mia Muster' } });
  api.post.mockResolvedValue({ lead: { id: 'lead-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Interessenten anlegen' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post.mock.calls[0][0]).toBe('/listings/local/marketing');
  expect(api.post.mock.calls[0][1].parameters.full_name).toBe('Mia Muster');
  expect(api.get.mock.calls.some(([path]) => path.includes('/channel-options'))).toBe(false);
});


it('shows an incomplete provider response as a recoverable loading error', async () => {
  api.get.mockResolvedValue({ items: [] });
  render(<ChannelPanel sourceId="malformed" mode="whatsapp" />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Kanalvorschau ist unvollständig');
  expect(screen.queryByRole('button', { name: 'Diese Template-Nachricht jetzt übergeben' })).toBeNull();
});
