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
    expect(outcome).toMatchObject({ sent: SEND_BATCH, failed: SEND_BATCH + 1 });
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
