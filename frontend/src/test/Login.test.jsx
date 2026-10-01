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
    fireEvent.change(code, { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.login.submit' }));
    await screen.findByText('Code invalid');
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
});
