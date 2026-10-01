import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Login from '../pages/Login';

const mocks = vi.hoisted(() => ({ getSetupStatus: vi.fn(), setupOwner: vi.fn(), login: vi.fn(), navigate: vi.fn(), t: key => key }));
vi.mock('../api', () => mocks);
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('react-router-dom', () => ({ useNavigate: () => mocks.navigate }));

const fillLogin = async () => {
  fireEvent.change(await screen.findByLabelText('auth.login.username'), { target: { value: 'owner' } });
  fireEvent.change(screen.getByLabelText('auth.login.password'), { target: { value: 'Strong123' } });
};

describe('Private installation login', () => {
  beforeEach(() => {
    mocks.getSetupStatus.mockReset().mockResolvedValue({ setup_required: false, setup_allowed: true });
    mocks.setupOwner.mockReset().mockResolvedValue({ id: 'owner' });
    mocks.login.mockReset().mockResolvedValue({ access_token: 'access' });
    mocks.navigate.mockReset();
  });

  it('offers login and approved-account information without public self-registration', async () => {
    render(<Login />);
    await fillLogin();
    expect(screen.getByLabelText('auth.login.username')).toHaveFocus();
    expect(screen.queryByText('auth.register.title')).not.toBeInTheDocument();
    expect(screen.getByText('auth.setup.approvedOnly')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/'));
    expect(mocks.login).toHaveBeenCalledWith('owner', 'Strong123', '');
  });

  it('retries status/setup failures and preserves a committed owner when login fails', async () => {
    mocks.getSetupStatus.mockRejectedValueOnce(new Error('Status offline')).mockResolvedValue({ setup_required: true, setup_allowed: true });
    mocks.setupOwner.mockRejectedValueOnce(new Error('Setup offline')).mockResolvedValue({ id: 'owner' });
    mocks.login.mockRejectedValueOnce(new Error('Login offline')).mockResolvedValue({});
    render(<Login />);
    await screen.findByText('Status offline');
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.retry' }));
    await fillLogin();
    fireEvent.change(screen.getByLabelText('auth.register.email'), { target: { value: 'owner@example.com' } });
    fireEvent.change(screen.getByLabelText('auth.setup.fullName'), { target: { value: 'Owner Name' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.setup.submit' }));
    await screen.findByText('Setup offline');
    expect(screen.getByLabelText('auth.setup.fullName')).toHaveValue('Owner Name');
    fireEvent.click(screen.getByRole('button', { name: 'auth.setup.submit' }));
    await screen.findByText('Login offline');
    expect(screen.queryByLabelText('auth.setup.fullName')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/'));
    expect(mocks.setupOwner).toHaveBeenCalledTimes(2);
    expect(mocks.setupOwner).toHaveBeenLastCalledWith('owner', 'owner@example.com', 'Owner Name', 'Strong123');
  });

  it('asks for a two-factor code and allows retry of an incorrect code', async () => {
    mocks.login.mockRejectedValueOnce(Object.assign(new Error('Code required'), { requiresTwoFactor: true }))
      .mockRejectedValueOnce(new Error('Code invalid')).mockResolvedValue({});
    render(<Login />);
    await fillLogin();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    const code = await screen.findByLabelText('auth.twoFactor.code');
    expect(code).toHaveFocus();
    fireEvent.change(code, { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await screen.findByText('Code invalid');
    expect(code).toHaveFocus();
    expect(code).toHaveValue('123456');
    expect(screen.getByLabelText('auth.login.username')).toHaveValue('owner');
    fireEvent.change(code, { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/'));
    expect(mocks.login).toHaveBeenLastCalledWith('owner', 'Strong123', '654321');
  });

  it('explains local-only setup for an empty remote installation', async () => {
    mocks.getSetupStatus.mockResolvedValue({ setup_required: true, setup_allowed: false });
    render(<Login />);
    await screen.findByText('auth.setup.localOnly');
    expect(screen.queryByLabelText('auth.login.username')).not.toBeInTheDocument();
  });

  it('announces status loading and offers no form before setup status is known', async () => {
    let resolveStatus;
    mocks.getSetupStatus.mockImplementation(() => new Promise(resolve => { resolveStatus = resolve; }));
    render(<Login />);
    expect(screen.getByRole('status')).toHaveTextContent('ui.table.loading');
    expect(screen.queryByLabelText('auth.login.username')).not.toBeInTheDocument();
    resolveStatus({ setup_required: false, setup_allowed: true });
    expect(await screen.findByLabelText('auth.login.username')).toHaveFocus();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('blocks repeated submits and credential edits while login is pending, then focuses its error', async () => {
    let rejectLogin;
    mocks.login.mockImplementation(() => new Promise((_, reject) => { rejectLogin = reject; }));
    render(<Login />);
    await fillLogin();
    const form = screen.getByRole('form', { name: 'auth.login.title' });
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(mocks.login).toHaveBeenCalledTimes(1);
    expect(form).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByLabelText('auth.login.username')).toBeDisabled();
    expect(screen.getByLabelText('auth.login.password')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'ui.table.loading' })).toBeDisabled();
    rejectLogin(new Error('Credentials rejected'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Credentials rejected');
    expect(alert).toHaveFocus();
    expect(form).toHaveAttribute('aria-busy', 'false');
    expect(screen.getByLabelText('auth.login.username')).toBeEnabled();
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it('creates only one owner while setup is pending and never repeats setup after a committed login failure', async () => {
    let resolveSetup;
    mocks.getSetupStatus.mockResolvedValue({ setup_required: true, setup_allowed: true });
    mocks.setupOwner.mockImplementation(() => new Promise(resolve => { resolveSetup = resolve; }));
    mocks.login.mockRejectedValueOnce(new Error('Login retry needed')).mockResolvedValue({});
    render(<Login />);
    await fillLogin();
    fireEvent.change(screen.getByLabelText('auth.register.email'), { target: { value: 'owner@example.com' } });
    fireEvent.change(screen.getByLabelText('auth.setup.fullName'), { target: { value: 'Owner Name' } });
    const form = screen.getByRole('form', { name: 'auth.setup.title' });
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(mocks.setupOwner).toHaveBeenCalledTimes(1);
    expect(mocks.login).not.toHaveBeenCalled();
    expect(screen.getByLabelText('auth.register.email')).toBeDisabled();
    resolveSetup({ id: 'owner' });
    await screen.findByText('Login retry needed');
    expect(screen.queryByLabelText('auth.register.email')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/'));
    expect(mocks.setupOwner).toHaveBeenCalledTimes(1);
    expect(mocks.login).toHaveBeenCalledTimes(2);
  });

  it('clears a challenged account code when the username changes', async () => {
    mocks.login.mockRejectedValueOnce(Object.assign(new Error('Code required'), { requiresTwoFactor: true }));
    render(<Login />);
    await fillLogin();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    const code = await screen.findByLabelText('auth.twoFactor.code');
    fireEvent.change(code, { target: { value: '123456' } });
    fireEvent.change(screen.getByLabelText('auth.login.username'), { target: { value: 'another-owner' } });
    expect(screen.queryByLabelText('auth.twoFactor.code')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('auth.login.username')).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/'));
    expect(mocks.login).toHaveBeenLastCalledWith('another-owner', 'Strong123', '');
  });
});
