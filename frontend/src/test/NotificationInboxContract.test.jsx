import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import NotificationInbox from '../components/NotificationInbox';

vi.mock('../api', () => ({ api: {
  captureSession: vi.fn(() => () => {}),
  get: vi.fn(),
  post: vi.fn(),
} }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-owner' } }) }));

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());

const show = () => render(<MemoryRouter initialEntries={['/notifications']}>
  <NotificationInbox />
</MemoryRouter>);

it('rejects incomplete notification responses as a visible retryable error instead of crashing', async () => {
  api.get.mockResolvedValue({ total: 1, unread_count: 1 });
  show();
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Benachrichtigungen sind unvollständig');
  expect(screen.getByRole('button', { name: 'Neu laden' })).toBeVisible();
  expect(screen.queryByText('Keine Hinweise in dieser Ansicht.')).not.toBeInTheDocument();
});

it('accepts a complete empty page without inventing unread notifications', async () => {
  api.get.mockResolvedValue({ items: [], total: 0, unread_count: 0, next_cursor: null, snapshot: 'synthetic' });
  show();
  expect(await screen.findByText('Keine Hinweise in dieser Ansicht.')).toBeVisible();
  expect(screen.getByText('0 ungelesen · 0 in dieser Ansicht')).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
