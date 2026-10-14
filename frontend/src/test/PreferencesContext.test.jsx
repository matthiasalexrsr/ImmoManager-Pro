import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { PreferencesProvider, usePreferences } from '../contexts/PreferencesContext';
import { api } from '../api';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { useEffect } from 'react';

vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));

function Consumer() {
  const { prefs, toggleTheme } = usePreferences();
  return <button onClick={toggleTheme}>{prefs.theme}</button>;
}

function SignIn({ user }) {
  const auth = useAuth();
  useEffect(() => { if (user) auth.updateUser(user); }, []); // eslint-disable-line react-hooks/exhaustive-deps
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
    api.put.mockReset().mockResolvedValue({});
  });

  it('loads and saves preferences via the auth preferences endpoint', async () => {
    renderWith({ id: 'u1', role: 'eigentuemer' });
    await waitFor(() => expect(screen.getByRole('button').textContent).toBe('dark'));
    expect(api.get).toHaveBeenCalledWith('/auth/users/me/preferences');

    act(() => screen.getByRole('button').click());
    expect(api.put).toHaveBeenCalledWith('/auth/users/me/preferences', expect.objectContaining({ theme: 'light' }));
  });

  it('does not request preferences while signed out', async () => {
    // Regression: the 401 made the API client redirect /login -> /login forever.
    renderWith(null);
    await act(async () => {});
    expect(api.get).not.toHaveBeenCalled();
  });
});
