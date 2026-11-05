import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';
import { DemoIndicator } from '../components/DemoMode';
import useRuntimeInfo from '../hooks/useRuntimeInfo';
import { getRegistrationStatus, login, register } from '../api';

vi.mock('../api', () => ({ getRegistrationStatus: vi.fn(), login: vi.fn(), register: vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));

const credentials = { username: 'demo.bw', password: 'Immo-Demo-BW-2026!' };
const health = value => vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => value }));
const renderLogin = () => render(<MemoryRouter><Login /></MemoryRouter>);
function RuntimeProbe() {
  const runtime = useRuntimeInfo();
  return runtime.demo ? <DemoIndicator /> : <span>Normalbetrieb</span>;
}

describe('Demo mode presentation', () => {
  beforeEach(() => {
    getRegistrationStatus.mockReset().mockResolvedValue({ open: false, initial_setup: false });
    login.mockReset().mockResolvedValue({ access_token: 'test-session' });
    register.mockReset();
    health({ demo: false });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('shows reviewed demo credentials and fills them only after an explicit click', async () => {
    health({ demo: true, demo_login: credentials });
    renderLogin();
    expect(await screen.findByText(credentials.username)).toBeInTheDocument();
    expect(screen.getByText(credentials.password)).toBeInTheDocument();
    expect(screen.getByLabelText('auth.login.userOrEmail')).toHaveValue('');
    expect(login).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Demozugang übernehmen' }));
    expect(screen.getByLabelText('auth.login.userOrEmail')).toHaveValue(credentials.username);
    expect(screen.getByLabelText('auth.login.password')).toHaveValue(credentials.password);
    expect(login).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(login).toHaveBeenCalledWith(credentials.username, credentials.password));
    expect(register).not.toHaveBeenCalled();
  });

  it.each([false, 'true', undefined])('does not offer demo credentials without the strict backend flag (%s)', async demo => {
    health({ demo, demo_login: credentials });
    renderLogin();
    await waitFor(() => expect(getRegistrationStatus).toHaveBeenCalled());
    expect(screen.queryByText(credentials.password)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Demozugang übernehmen' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('auth.login.userOrEmail')).toHaveValue('');
  });

  it('keeps the ordinary sign-in available if runtime information cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('health unavailable')));
    renderLogin();
    await waitFor(() => expect(getRegistrationStatus).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'auth.login.submit' })).toBeEnabled();
    expect(screen.queryByText('Demozugang übernehmen')).not.toBeInTheDocument();
  });

  it('shows the compact Demo indicator from the backend mode', async () => {
    health({ demo: true, demo_login: credentials });
    render(<RuntimeProbe />);
    expect(await screen.findByLabelText('Demo')).toHaveTextContent('Demo');
    expect(screen.getByText('Verwaltung Baden-Württemberg')).toBeInTheDocument();
    expect(screen.queryByText(credentials.password)).not.toBeInTheDocument();
  });

  it('keeps demo sign-in out of owner registration even with a stale registration reply', async () => {
    health({ demo: true, demo_login: credentials });
    getRegistrationStatus.mockResolvedValue({ open: true, initial_setup: true });
    renderLogin();
    await screen.findByRole('button', { name: 'Demozugang übernehmen' });
    expect(screen.queryByLabelText('auth.register.email')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Demozugang übernehmen' }));
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(login).toHaveBeenCalledWith(credentials.username, credentials.password));
    expect(register).not.toHaveBeenCalled();
  });
});
