import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { api } from '../api';
import NotificationLanding from '../pages/NotificationLanding';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({ 'status.badge.active': 'Aktiv' }[key] || key) }) }));
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

it('reloads and displays the changed source before acknowledging a revision conflict', async () => {
  const value = revision => ({ notice: { revision: 0, content: 'Bitte prüfen' }, source: {
    kind: 'category', entity_id: 'c1', revision, title: `Quelle ${revision}`, href: '/categories?focus_id=c1', values: {},
  } });
  api.get.mockResolvedValueOnce(value('first')).mockResolvedValueOnce(value('second'));
  api.post.mockRejectedValueOnce(Object.assign(new Error('Quelle wurde geändert'), { statusCode: 409 })).mockResolvedValue({});
  render(<MemoryRouter initialEntries={['/notifications/open/n1']}><Routes>
    <Route path="/notifications/open/:id" element={<NotificationLanding />} /></Routes></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Aktuelle Quelle laden' }));
  expect(await screen.findByRole('heading', { name: 'Quelle second' })).toBeInTheDocument();
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[1][1].source_revision).toBe('second');
  expect(api.post.mock.calls[1][1].idempotency_key).not.toBe(api.post.mock.calls[0][1].idempotency_key);
});

it('shows the source in words with its actions', async () => {
  api.get.mockResolvedValueOnce({
    notice: { revision: 1, content: 'Zahlungserinnerung über 1.704,00 €' },
    source: { kind: 'contract', entity_id: 'c1', revision: 3, title: 'MV-2019-058', href: '/contracts?focus_id=c1',
      values: { status: 'active', start_date: '2019-05-01', contract_number: 'MV-2019-058', amount_due: 1704 } },
  });
  api.post.mockResolvedValueOnce({});
  await act(async () => {
    render(<MemoryRouter initialEntries={['/notifications/open/n1']}><Routes>
      <Route path="/notifications/open/:id" element={<NotificationLanding />} /></Routes></MemoryRouter>);
  });
  expect(screen.getByRole('heading', { name: 'MV-2019-058' })).toBeInTheDocument();
  expect(screen.getByText('Aktiv')).toHaveClass('badge');
  expect(screen.queryByText('active')).toBeNull();
  expect(screen.getByText('01.05.2019')).toBeInTheDocument();
  expect(screen.getByText(/1\.704,00\s€/, { selector: 'dd' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Vollständige Akte öffnen' })).toHaveAttribute('href', '/contracts?focus_id=c1');
  expect(screen.getByRole('link', { name: 'Zum Eingang' })).toHaveClass('btn');
  expect(await screen.findByText('Persönlich gelesen und archiviert.')).toBeInTheDocument();
});

it('never mounts a previously loaded source under the next notification identifier', async () => {
  api.get.mockResolvedValueOnce({ notice: { revision: 1, content: 'Erster Hinweis' }, source: {
    kind: 'task', entity_id: 't1', revision: 1, title: 'Erste Aufgabe', href: '/tasks?focus_id=t1', values: { status: 'open' },
  } }).mockImplementation(() => new Promise(() => {}));
  api.post.mockResolvedValue({});
  function Next() { const navigate = useNavigate(); return <button onClick={() => navigate('/notifications/open/n2')}>Nächster Hinweis</button>; }
  render(<MemoryRouter initialEntries={['/notifications/open/n1']}><Next /><Routes>
    <Route path="/notifications/open/:id" element={<NotificationLanding />} /></Routes></MemoryRouter>);
  await screen.findByRole('heading', { name: 'Erste Aufgabe' });
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Nächster Hinweis' })));
  expect(screen.queryByRole('heading', { name: 'Erste Aufgabe' })).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Quelle wird geprüft');
  expect(api.post).not.toHaveBeenCalledWith('/notifications/n2/receipt', expect.anything());
});
