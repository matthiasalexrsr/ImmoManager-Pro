import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { PreferencesProvider, usePreferences } from '../contexts/PreferencesContext';
import { api } from '../api';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { useEffect } from 'react';
import { formatDate, setDateFormat } from '../utils/format';

vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn(), captureSession: vi.fn(() => () => {}) } }));

function Consumer() {
  const { prefs, toggleTheme } = usePreferences();
  return <button onClick={toggleTheme}>{prefs.theme}</button>;
}

function SignIn({ user }) {
  const updateUser = useAuth().updateUser;
  useEffect(() => { if (user) updateUser(user); }, [user, updateUser]);
  return null;
}

function renderWith(user) {
  return render(
    <AuthProvider><SignIn user={user} /><PreferencesProvider><Consumer /></PreferencesProvider></AuthProvider>,
  );
}

describe('PreferencesContext', () => {
  beforeEach(() => {
    localStorage.clear();
    api.get.mockReset().mockResolvedValue({ theme: 'dark' });
    api.put.mockReset().mockResolvedValue({ response: { theme: 'light', _revision: 1 } });
  });

  it('loads existing preferences and saves with revision and replay key', async () => {
    renderWith({ id: 'u1', role: 'eigentuemer' });
    await waitFor(() => expect(screen.getByRole('button').textContent).toBe('dark'));
    expect(api.get).toHaveBeenCalledWith('/auth/users/me/preferences');

    act(() => screen.getByRole('button').click());
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/auth/users/me/settings', expect.objectContaining({ values: { theme: 'light' }, base_revision: 0, idempotency_key: expect.any(String) })));
    await waitFor(() => expect(screen.getByRole('button').textContent).toBe('light'));
  });

  it('does not request preferences while signed out', async () => {
    // Regression: the 401 made the API client redirect /login -> /login forever.
    renderWith(null);
    await act(async () => {});
    expect(api.get).not.toHaveBeenCalled();
  });
  it('applies loaded date and density preferences to actual consumers', async () => {
    api.get.mockResolvedValue({ theme: 'dark', date_format: 'YYYY-MM-DD', density: 'compact', _revision: 2 });
    renderWith({ id: 'u-density', role: 'readonly' });
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-density', 'compact'));
    expect(formatDate('2026-02-03')).toBe('2026-02-03');
    setDateFormat(null);
  });

  it('ignores a delayed previous-account preference response', async () => {
    const pending = [];
    api.get.mockImplementation(path => path === '/auth/users/me/preferences' ? new Promise(resolve => pending.push(resolve)) : Promise.resolve({ write: [] }));
    const tree = user => <AuthProvider><SignIn user={user} /><PreferencesProvider><Consumer /></PreferencesProvider></AuthProvider>;
    const page = render(tree({ id: 'old-owner', role: 'readonly' }));
    await waitFor(() => expect(pending).toHaveLength(1));
    page.rerender(tree({ id: 'new-owner', role: 'readonly' }));
    await waitFor(() => expect(pending).toHaveLength(2));
    await act(async () => pending[1]({ theme: 'dark' }));
    await act(async () => pending[0]({ theme: 'light' }));
    expect(screen.getByRole('button')).toHaveTextContent('dark');
  });

});
