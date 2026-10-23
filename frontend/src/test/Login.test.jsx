import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';
import { getRegistrationStatus } from '../api';

vi.mock('../api', () => ({
  getRegistrationStatus: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
}));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: (key) => key }) }));

function renderLogin() {
  return render(<MemoryRouter><Login /></MemoryRouter>);
}

describe('Login registration gating', () => {
  beforeEach(() => getRegistrationStatus.mockReset());

  it('hides sign-up when the server has it closed', async () => {
    getRegistrationStatus.mockResolvedValue({ open: false, initial_setup: false });
    renderLogin();
    await waitFor(() => expect(getRegistrationStatus).toHaveBeenCalled());
    expect(screen.queryByText('auth.register.title')).not.toBeInTheDocument();
    expect(screen.getByText('auth.login.submit')).toBeInTheDocument();
  });

  it('offers sign-up when self-registration is enabled', async () => {
    getRegistrationStatus.mockResolvedValue({ open: true, initial_setup: false });
    renderLogin();
    expect(await screen.findByText('auth.register.title')).toBeInTheDocument();
  });

  it('starts in owner sign-up mode on a fresh install', async () => {
    getRegistrationStatus.mockResolvedValue({ open: true, initial_setup: true });
    renderLogin();
    expect(await screen.findByText('auth.register.initialSetup')).toBeInTheDocument();
    expect(screen.getByText('auth.register.submit')).toBeInTheDocument();
    expect(screen.queryByText('auth.register.title')).not.toBeInTheDocument();
  });
});
