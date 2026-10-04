import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { PreferencesProvider, usePreferences } from '../contexts/PreferencesContext';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));

function Consumer() {
  const { prefs, toggleTheme } = usePreferences();
  return <button onClick={toggleTheme}>{prefs.theme}</button>;
}

describe('PreferencesContext', () => {
  beforeEach(() => {
    localStorage.clear();
    api.get.mockReset().mockResolvedValue({ theme: 'dark' });
    api.put.mockReset().mockResolvedValue({});
  });

  it('loads and saves preferences via the auth preferences endpoint', async () => {
    render(<PreferencesProvider><Consumer /></PreferencesProvider>);
    await waitFor(() => expect(screen.getByRole('button').textContent).toBe('dark'));
    expect(api.get).toHaveBeenCalledWith('/auth/users/me/preferences');

    act(() => screen.getByRole('button').click());
    expect(api.put).toHaveBeenCalledWith('/auth/users/me/preferences', expect.objectContaining({ theme: 'light' }));
  });
});
