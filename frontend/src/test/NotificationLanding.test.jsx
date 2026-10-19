import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { api } from '../api';
import NotificationLanding from '../pages/NotificationLanding';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({ 'status.badge.active': 'Aktiv' }[key] || key) }) }));
afterEach(cleanup);

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
