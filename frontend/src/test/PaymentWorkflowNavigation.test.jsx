import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CasesTab, OutboxTab, RepliesTab } from '../features/dunning/DunningTabs';
import { dunningText } from '../features/dunning/dunningText';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
const say = (key, values) => dunningText('de-DE', key, values);
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const entry = i => ({ id: `entry-${i}`, contract_id: `lease-${i}`, letter_id: `letter-${i}`,
  subject: `Mahnung ${i}`, status: 'ready', channel: 'letter', recipient_name: `Partei ${i}` });

describe('complete dunning lists and source navigation', () => {
  beforeEach(() => vi.resetAllMocks());

  it.each(['outbox', 'replies'])('makes the 201st %s entry reachable', async kind => {
    api.get.mockImplementation(path => {
      const params = new URLSearchParams(path.split('?')[1]);
      const offset = Number(params.get('offset') || 0);
      const limit = Number(params.get('limit'));
      const rows = Array.from({ length: 201 }, (_, i) => kind === 'outbox' ? entry(i) : {
        id: `reply-${i}`, received_on: '2026-10-01', sender: `Partei ${i}`, body: `Antwort ${i}`, review_reason: 'no_reference' });
      return Promise.resolve({ total: rows.length, offset, limit, items: rows.slice(offset, offset + limit) });
    });
    render(<MemoryRouter>{kind === 'outbox' ? <OutboxTab say={say} canWrite={false} /> : <RepliesTab say={say} canWrite={false} />}</MemoryRouter>);
    await screen.findByText(kind === 'outbox' ? 'Mahnung 0' : 'Antwort 0');
    for (const shown of [100, 150, 200, 201]) {
      fireEvent.click(screen.getByRole('button', { name: say('more') }));
      await screen.findByText(kind === 'outbox' ? `Mahnung ${shown - 1}` : `Antwort ${shown - 1}`);
    }
    expect(screen.queryByRole('button', { name: say('more') })).not.toBeInTheDocument();
    if (kind === 'outbox') expect(screen.getAllByRole('link', { name: say('openFile') }).at(-1))
      .toHaveAttribute('href', '/dunning/contracts/lease-200');
  });

  it('keeps existing cases after a page failure and discards a delayed page when the status changes', async () => {
    const delayed = deferred();
    let fail = true;
    api.get.mockImplementation(path => {
      const p = new URLSearchParams(path.split('?')[1]);
      const row = { ...entry(0), reference: 'Offene Akte', contract_number: 'MV-1', outstanding: 10, stage_label: 'Erinnerung' };
      if (p.get('status') === 'closed') return Promise.resolve({ total: 1, items: [{ ...row, id: 'closed', reference: 'Abgeschlossene Akte', status: 'closed' }] });
      if (Number(p.get('offset')) > 0) {
        if (fail) { fail = false; return Promise.reject(new Error('Nächste Seite nicht erreichbar')); }
        return delayed.promise;
      }
      return Promise.resolve({ total: 2, items: [row] });
    });
    render(<MemoryRouter><CasesTab say={say} /></MemoryRouter>);
    await screen.findByText('Offene Akte');
    fireEvent.click(screen.getByRole('button', { name: say('more') }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Nächste Seite nicht erreichbar');
    expect(screen.getByText('Offene Akte')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: say('retry') }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'closed' } });
    await screen.findByText('Abgeschlossene Akte');
    await act(async () => delayed.resolve({ total: 2, items: [{ ...entry(1), reference: 'Veraltete Seite' }] }));
    expect(screen.queryByText('Veraltete Seite')).not.toBeInTheDocument();
    expect(screen.queryByText('Offene Akte')).not.toBeInTheDocument();
  });

  it('shows a failed initial read without asserting an empty case inventory', async () => {
    api.get.mockRejectedValue(new Error('Mahnlisten nicht erreichbar'));
    render(<MemoryRouter><CasesTab say={say} /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Mahnlisten nicht erreichbar');
    expect(screen.queryByText(say('noCases'))).not.toBeInTheDocument();
  });
});
