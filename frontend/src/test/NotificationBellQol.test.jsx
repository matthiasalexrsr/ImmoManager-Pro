import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import NotificationBell from '../components/NotificationBell';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'bell-qa' } }) }));

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ items: [], total: 0, unread_count: 0, snapshot: 'empty-inbox' });
});
afterEach(() => cleanup());

it('always previews unread notices even while the page is displaying the archive', async () => {
  render(<MemoryRouter initialEntries={['/notifications?status=archived&severity=critical']}><NotificationBell /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Benachrichtigungen' }));
  await screen.findByText('Keine Hinweise in dieser Ansicht.');
  const previews = api.get.mock.calls.filter(([path]) => path.includes('limit=10'));
  expect(previews.length).toBeGreaterThan(0);
  expect(previews.every(([path]) => new URL(path, 'http://local').searchParams.get('status') === 'unread')).toBe(true);
});

function renderBell() {
  return render(<MemoryRouter>
    <button type="button">Eine andere Aktion</button>
    <NotificationBell />
  </MemoryRouter>);
}

describe('Benachrichtigungsglocke ohne Fokusverlust', () => {
  it('ignoriert Escape vollständig, wenn die Vorschau geschlossen ist', async () => {
    renderBell();
    await act(async () => {});
    const unrelated = screen.getByRole('button', { name: 'Eine andere Aktion' });
    unrelated.focus();
    fireEvent.keyDown(unrelated, { key: 'Escape' });
    expect(unrelated).toHaveFocus();
    expect(screen.queryByRole('region', { name: 'Benachrichtigungs-Vorschau' })).not.toBeInTheDocument();
  });

  it('benennt die geöffnete Vorschau und schließt nur sie mit Escape', async () => {
    renderBell();
    const bell = screen.getByRole('button', { name: 'Benachrichtigungen' });
    fireEvent.click(bell);
    const preview = await screen.findByRole('region', { name: 'Benachrichtigungs-Vorschau' });
    expect(bell).toHaveAttribute('aria-expanded', 'true');
    expect(bell).toHaveAttribute('aria-controls', preview.id);
    const link = await screen.findByRole('link', { name: 'Vollständiger Eingang und Archiv' });
    link.focus();
    fireEvent.keyDown(link, { key: 'Escape' });
    expect(preview).not.toBeInTheDocument();
    expect(bell).toHaveFocus();
    expect(bell).toHaveAttribute('aria-expanded', 'false');
  });

  it('schließt beim Wechsel des Tastaturfokus aus dem Popover, ohne ihn zu stehlen', async () => {
    renderBell();
    const bell = screen.getByRole('button', { name: 'Benachrichtigungen' });
    fireEvent.click(bell);
    expect(await screen.findByRole('region', { name: 'Benachrichtigungs-Vorschau' })).toBeInTheDocument();
    await act(async () => {});
    const other = screen.getByRole('button', { name: 'Eine andere Aktion' });
    act(() => { other.focus(); fireEvent.focusIn(other); });
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Benachrichtigungs-Vorschau' })).not.toBeInTheDocument());
    expect(other).toHaveFocus();
  });
});
