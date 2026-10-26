import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';
import { getRegistrationStatus, login } from '../api';

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
  beforeEach(() => { getRegistrationStatus.mockReset(); login.mockReset(); });

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

  it('collects the second factor, preserves a rejected attempt and allows returning to the password', async () => {
    getRegistrationStatus.mockResolvedValue({ open: false, initial_setup: false });
    login.mockRejectedValueOnce(Object.assign(new Error('Zwei-Faktor-Code erforderlich'), {requiresTotp:true}))
      .mockRejectedValueOnce(new Error('Ungültiger Zwei-Faktor-Code'))
      .mockResolvedValueOnce({access_token:'synthetic'});
    renderLogin();
    fireEvent.change(screen.getByLabelText('auth.login.userOrEmail'), {target:{value:'audit'}});
    fireEvent.change(screen.getByLabelText('auth.login.password'), {target:{value:'Secret123'}});
    fireEvent.click(screen.getByRole('button', {name:'auth.login.submit'}));
    fireEvent.change(await screen.findByLabelText('Zwei-Faktor-Code'), {target:{value:'123456'}});
    fireEvent.click(screen.getByRole('button', {name:'auth.login.submit'}));
    await screen.findByText('Ungültiger Zwei-Faktor-Code');
    expect(login).toHaveBeenLastCalledWith('audit','Secret123','123456');
    fireEvent.change(screen.getByLabelText('Zwei-Faktor-Code'), {target:{value:'654321'}});
    fireEvent.click(screen.getByRole('button', {name:'auth.login.submit'}));
    await waitFor(() => expect(login).toHaveBeenLastCalledWith('audit','Secret123','654321'));
    await waitFor(() => expect(screen.getByText('Zurück zur Passworteingabe')).toBeEnabled());
    fireEvent.click(screen.getByText('Zurück zur Passworteingabe'));
    expect(screen.queryByLabelText('Zwei-Faktor-Code')).not.toBeInTheDocument();
    expect(screen.getByLabelText('auth.login.password')).toHaveValue('');
  });
});
