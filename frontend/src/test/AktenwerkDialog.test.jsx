import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AktenwerkDialog from '../features/aktenwerk/AktenwerkDialog';
import { aktenwerkApi, sendAll, SEND_BATCH } from '../features/aktenwerk/aktenwerkApi';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), getBlob: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const entry = { exchange_id: 'immomanager:document:old', title: 'Alter Vertrag', kind: 'vertrag' };
const show = () => render(<MemoryRouter><AktenwerkDialog ready onClose={vi.fn()} /></MemoryRouter>);

describe('Aktenwerk selection and transfer results', () => {
  it('cannot send the previous preview while changed filters load or fail', async () => {
    let rejectPreview;
    api.get.mockResolvedValueOnce({ entries: [entry] })
      .mockImplementationOnce(() => new Promise((resolve, reject) => { rejectPreview = reject; }));
    show();
    expect(await screen.findByText('Alter Vertrag')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Nur absetzbar/ }));
    expect(screen.queryByText('Alter Vertrag')).not.toBeInTheDocument();
    const send = screen.getByRole('button', { name: /An Aktenwerk übergeben/ });
    expect(send).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Exportpaket (ZIP)' })).toBeDisabled();
    await act(async () => rejectPreview(new Error('Auswahl nicht verfügbar')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Auswahl nicht verfügbar');
    expect(send).toBeDisabled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('retains completed batches if a later response is lost and stops further sending', async () => {
    const ids = Array.from({ length: SEND_BATCH * 2 + 1 }, (_, i) => `document:${i}`);
    const send = vi.fn().mockResolvedValueOnce({ sent: SEND_BATCH, failed: 0,
      results: ids.slice(0, SEND_BATCH).map(id => ({ exchange_id: id, status: 'sent' })) })
      .mockRejectedValueOnce(new Error('Verbindung unterbrochen'));
    const outcome = await sendAll(ids, send);
    expect(send).toHaveBeenCalledTimes(2);
    expect(outcome).toMatchObject({ sent: SEND_BATCH, unknown: SEND_BATCH, failed: 1 });
    expect(outcome.results[SEND_BATCH].status).toBe('unknown');
    expect(outcome.results[SEND_BATCH].reason).toMatch(/unbestätigt/);
    expect(outcome.results.at(-1).reason).toMatch(/nicht gesendet/);
  });

  it('shows a journal failure after a successful hand-over', async () => {
    vi.spyOn(aktenwerkApi, 'manifest').mockResolvedValue({ entries: [entry] });
    api.post.mockResolvedValue({ sent: 1, failed: 0,
      results: [{ exchange_id: entry.exchange_id, status: 'sent' }], history_warning: 'Versand nicht automatisch wiederholen.' });
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'An Aktenwerk übergeben (1)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Versand nicht automatisch wiederholen.');
    expect(screen.getByText('1 an Aktenwerk übergeben')).toBeInTheDocument();
  });
});

describe('Aktenwerk unconfirmed responses', () => {
  it('displays missing remote hash confirmation as unresolved, never as a success', async () => {
    api.get.mockResolvedValue({ entries: [entry] });
    api.post.mockResolvedValue({
      sent: 0, failed: 1, unknown: 0,
      results: [{ exchange_id: entry.exchange_id, status: 'conflict',
        reason: 'Gegenstelle hat Dokument-ID und SHA-256 nicht bestätigt.' }],
    });
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'An Aktenwerk übergeben (1)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('SHA-256');
    expect(screen.getByRole('alert')).toHaveTextContent('Nichts übergeben');
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('preserves an ambiguous remote acceptance without counting it as failed or sent', async () => {
    const result = await sendAll([entry.exchange_id], async ids => ({
      sent: 0, failed: 0, unknown: 1, results: ids.map(exchange_id => ({
        exchange_id, status: 'unknown', reason: 'Bitte bei Aktenwerk abgleichen.',
      })),
    }));
    expect(result).toMatchObject({ sent: 0, failed: 0, unknown: 1 });
    expect(result.message).toMatch(/Ausgang unklar/);
  });
});

describe('Aktenwerk response completeness', () => {
  it.each([
    { sent: 1, failed: 0, results: [] },
    { sent: 1, failed: 0, results: [{ exchange_id: 'immomanager:document:other', status: 'sent' }] },
    { sent: 1, failed: 0, results: [{ exchange_id: entry.exchange_id, status: 'failed' }] },
    { sent: 2, failed: 0, results: [
      { exchange_id: entry.exchange_id, status: 'sent' },
      { exchange_id: entry.exchange_id, status: 'sent' },
    ] },
  ])('treats incomplete, foreign or contradictory transfer receipts as unresolved', async reply => {
    const send = vi.fn().mockResolvedValue(reply);
    const result = await sendAll([entry.exchange_id], send);
    expect(send).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ sent: 0, failed: 0, unknown: 1 });
    expect(result.results).toEqual([expect.objectContaining({
      exchange_id: entry.exchange_id, status: 'unknown',
    })]);
    expect(result.message).toMatch(/Ausgang unklar/);
  });
});
