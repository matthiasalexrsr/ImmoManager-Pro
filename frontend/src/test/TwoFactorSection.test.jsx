import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import TwoFactorSection from '../pages/settings/TwoFactorSection';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), t: key => key }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'recorded-account-id' } }) }));

describe('Authenticator settings', () => {
  beforeEach(() => {
    mocks.get.mockReset().mockResolvedValue({ enabled: false });
    mocks.post.mockReset();
  });

  it('retries status failures without exposing enrollment until status is known', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Status offline')).mockResolvedValue({ enabled: false });
    render(<TwoFactorSection />);
    await screen.findByText('Status offline');
    expect(screen.queryByRole('button', { name: 'auth.twoFactor.setup' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.retry' }));
    await screen.findByRole('button', { name: 'auth.twoFactor.setup' });
    expect(screen.getByText('recorded-account-id')).toBeInTheDocument();
  });

  it('keeps enrollment on verification failure and requires a code to disable', async () => {
    mocks.post.mockRejectedValueOnce(new Error('Setup offline'))
      .mockResolvedValueOnce({ secret: 'MANUALSECRET', uri: 'otpauth://totp/example?secret=MANUALSECRET' })
      .mockRejectedValueOnce(new Error('Wrong verification code')).mockResolvedValueOnce({ enabled: true })
      .mockRejectedValueOnce(new Error('Wrong disable code')).mockResolvedValueOnce({ enabled: false });
    render(<TwoFactorSection />);
    fireEvent.click(await screen.findByRole('button', { name: 'auth.twoFactor.setup' }));
    await screen.findByText('Setup offline');
    fireEvent.click(screen.getByRole('button', { name: 'auth.twoFactor.setup' }));
    expect(await screen.findByLabelText('auth.twoFactor.secret')).toHaveValue('MANUALSECRET');
    fireEvent.change(screen.getByLabelText('auth.twoFactor.code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.twoFactor.verify' }));
    await screen.findByText('Wrong verification code');
    expect(screen.getByLabelText('auth.twoFactor.secret')).toHaveValue('MANUALSECRET');
    fireEvent.change(screen.getByLabelText('auth.twoFactor.code'), { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.twoFactor.verify' }));
    await screen.findByText('auth.twoFactor.enabledSuccess');
    expect(screen.queryByLabelText('auth.twoFactor.secret')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('auth.twoFactor.code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'auth.twoFactor.disable' }));
    await screen.findByText('Wrong disable code');
    expect(screen.getByText('auth.twoFactor.enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'auth.twoFactor.disable' }));
    await screen.findByText('auth.twoFactor.disabledSuccess');
    await waitFor(() => expect(screen.getByRole('button', { name: 'auth.twoFactor.setup' })).toBeEnabled());
    expect(mocks.post).toHaveBeenLastCalledWith('/auth/2fa/disable', { code: '123456' });
  });
});
