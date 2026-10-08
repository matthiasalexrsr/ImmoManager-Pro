import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { DevModeProvider, useDevMode } from '../contexts/DevModeContext';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));

function Consumer() {
  const auth = useAuth();
  const devMode = useDevMode();
  return (
    <div>
      <span data-testid="enabled">{String(devMode.enabled)}</span>
      <span data-testid="available">{String(devMode.available)}</span>
      <button onClick={() => auth.updateUser({ role: 'eigentuemer' })}>admin</button>
      <button onClick={() => auth.updateUser({ role: 'readonly' })}>viewer</button>
      <button onClick={() => devMode.toggle()}>toggle</button>
    </div>
  );
}

function renderDevMode() {
  return render(
    <AuthProvider>
      <DevModeProvider><Consumer /></DevModeProvider>
    </AuthProvider>
  );
}

describe('DevModeContext', () => {
  beforeEach(() => {
    localStorage.clear();
    api.get.mockReset();
  });

  it('is unavailable for non-admin users, even if stored as on', () => {
    localStorage.setItem('dev_mode', 'true');
    renderDevMode();
    act(() => screen.getByText('viewer').click());
    act(() => screen.getByText('toggle').click());
    expect(screen.getByTestId('available').textContent).toBe('false');
    expect(screen.getByTestId('enabled').textContent).toBe('false');
    expect(api.get).not.toHaveBeenCalled();
  });

  it('can be enabled by admins', async () => {
    api.get.mockResolvedValue([]);
    renderDevMode();
    act(() => screen.getByText('admin').click());
    act(() => screen.getByText('toggle').click());
    expect(screen.getByTestId('enabled').textContent).toBe('true');
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/dev-notes'));
  });

  it('switches itself off when the server blocks developer tools', async () => {
    api.get.mockRejectedValue(Object.assign(new Error('forbidden'), { statusCode: 403 }));
    renderDevMode();
    act(() => screen.getByText('admin').click());
    act(() => screen.getByText('toggle').click());
    await waitFor(() => expect(screen.getByTestId('enabled').textContent).toBe('false'));
    expect(screen.getByTestId('available').textContent).toBe('false');
  });
});
