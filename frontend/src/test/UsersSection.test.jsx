import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import UsersSection from '../pages/settings/UsersSection';
import { api } from '../api';

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));
const t = (key) => key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t }) }));
const toast = { success: vi.fn(), error: vi.fn() };
vi.mock('../components/Toast', () => ({ useToast: () => toast }));
const confirm = vi.fn();
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => confirm }));

const owner = { id: 'o1', username: 'owner', full_name: 'Owner', email: 'o@x.de', role: 'eigentuemer', is_active: true };
const staff = { id: 's1', username: 'staff', full_name: 'Staff', email: 's@x.de', role: 'buchhaltung', is_active: true };
const reader = { id: 'r1', username: 'reader', full_name: 'Reader', email: 'r@x.de', role: 'readonly', is_active: true };

const row = async (username) => (await screen.findByText(username)).closest('tr');

describe('UsersSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue([owner, staff, reader]);
  });

  it('lets an owner manage others but not deactivate or delete themselves', async () => {
    render(<UsersSection currentUser={owner} />);
    const self = await row('owner');
    expect(within(self).queryByText('pages.settings.users.deactivate')).not.toBeInTheDocument();
    expect(within(self).queryByText('pages.settings.users.delete')).not.toBeInTheDocument();
    const other = await row('staff');
    expect(within(other).getByText('pages.settings.users.deactivate')).toBeInTheDocument();
    expect(within(other).getByText('pages.settings.users.delete')).toBeInTheDocument();
  });

  it('limits a manager to read-only accounts', async () => {
    const manager = { ...staff, id: 'm1', username: 'manager', role: 'verwalter' };
    api.get.mockResolvedValue([owner, manager, reader]);
    render(<UsersSection currentUser={manager} />);
    expect(within(await row('owner')).queryByText('pages.settings.users.edit')).not.toBeInTheDocument();
    const readerRow = await row('reader');
    expect(within(readerRow).getByText('pages.settings.users.edit')).toBeInTheDocument();
    expect(within(readerRow).queryByText('pages.settings.users.delete')).not.toBeInTheDocument();
    expect(screen.getByText('pages.settings.users.managerHint')).toBeInTheDocument();
  });

  it('deactivates a user only after confirmation', async () => {
    confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    api.patch.mockResolvedValue({ ...staff, is_active: false });
    render(<UsersSection currentUser={owner} />);
    const button = within(await row('staff')).getByText('pages.settings.users.deactivate');
    fireEvent.click(button);
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(api.patch).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/auth/users/s1', { is_active: false }));
  });

  it('creates a user through the form', async () => {
    api.post.mockResolvedValue({ ...reader, id: 'n1' });
    render(<UsersSection currentUser={owner} />);
    await row('owner');
    fireEvent.click(screen.getByText('pages.settings.users.add'));
    const dialog = await screen.findByRole('dialog');
    const fill = (label, value) => fireEvent.change(within(dialog).getByLabelText(new RegExp(label)), { target: { value } });
    fill('users.username', 'neu');
    fill('users.fullName', 'Neu Nutzer');
    fill('users.email', 'neu@x.de');
    fill('users.password', 'Secret123');
    fill('users.role', 'techniker');
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/auth/users', {
      username: 'neu', full_name: 'Neu Nutzer', email: 'neu@x.de', password: 'Secret123', role: 'techniker',
    }));
  });

  it('shows an error when the list cannot be loaded', async () => {
    api.get.mockRejectedValue(new Error('403'));
    render(<UsersSection currentUser={owner} />);
    expect(await screen.findByText('pages.settings.users.loadError')).toBeInTheDocument();
  });
});
