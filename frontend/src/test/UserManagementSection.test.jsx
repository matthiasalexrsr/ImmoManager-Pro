import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import UserManagementSection from '../pages/settings/UserManagementSection';
import Settings from '../pages/Settings';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), patch: vi.fn(), updateUser: vi.fn(), updatePrefs: vi.fn(), retrySave: vi.fn(), saveError: null, setLocale: vi.fn(), auth: null, locale: 'de-DE', t: null }));
vi.mock('../api', () => ({ api: { get: mocks.get, getAll: mocks.getAll, post: mocks.post, patch: mocks.patch } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t, locale: mocks.locale, setLocale: mocks.setLocale }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => ({ prefs: {}, toggleTheme: vi.fn(), toggleSidebar: vi.fn(), updatePrefs: mocks.updatePrefs, saveError: mocks.saveError, retrySave: mocks.retrySave }) }));
vi.mock('../contexts/DevModeContext', () => ({ useDevMode: () => ({ enabled: false }) }));
vi.mock('../pages/settings/TwoFactorSection', () => ({ default: () => <p>Authenticator</p> }));
vi.mock('../pages/settings/BackupSection', () => ({ default: () => null }));
vi.mock('../pages/settings/UpdateSection', () => ({ default: () => null }));
vi.mock('../pages/settings/AutotestSection', () => ({ default: () => null }));

const dictionaries = { 'de-DE': de, 'en-US': en, 'es-ES': es };
function translate(key, params = {}) {
  let value = key.split('.').reduce((current, part) => current?.[part], dictionaries[mocks.locale]) || key;
  for (const [name, replacement] of Object.entries(params)) value = value.replaceAll(`{{${name}}}`, replacement);
  return value;
}
const fixtures = [
  { id: 'owner', username: 'own', full_name: 'Olivia Eigentümer', email: 'olivia@example.com', role: 'eigentuemer', is_active: true },
  { id: 'owner2', username: 'second', full_name: 'Sven Eigentümer', email: 'sven@example.com', role: 'eigentuemer', is_active: true },
  { id: 'manager', username: 'manager', full_name: 'Mara Verwaltung', email: 'mara@example.com', role: 'verwalter', is_active: true },
  { id: 'reader', username: 'reader', full_name: 'Rene Lesen', email: 'rene@example.com', role: 'readonly', is_active: false },
];
let records;
function setRole(role, id = role === 'verwalter' ? 'manager' : role === 'readonly' ? 'reader' : 'owner') {
  mocks.auth = { role, user: { ...fixtures.find(row => row.id === id), id, role }, isAdmin: ['eigentuemer', 'verwalter'].includes(role), isReadonly: role === 'readonly', updateUser: mocks.updateUser };
}
const renderSection = () => render(<UserManagementSection />);
const edit = async name => { fireEvent.click(await screen.findByRole('button', { name: `${name} bearbeiten`, exact: true })); return screen.getByRole('dialog'); };
const submit = () => fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
function fillCreate(password = 'lange geheime passphrase') {
  const dialog = screen.getByRole('dialog');
  for (const [label, value] of [['Benutzername', 'newreader'], ['Vollständiger Name', 'Neue Person'], ['E-Mail-Adresse', 'new@example.com'], ['Startpassphrase', password]]) fireEvent.change(within(dialog).getByLabelText(`${label} *`), { target: { value } });
}

beforeEach(() => {
  vi.clearAllMocks();
  records = fixtures.map(row => ({ ...row }));
  mocks.locale = 'de-DE'; mocks.t = translate; setRole('eigentuemer');
  mocks.saveError = null; mocks.retrySave.mockResolvedValue(undefined);
  mocks.get.mockResolvedValue({ version: '1.0' });
  mocks.getAll.mockImplementation(async () => records);
  mocks.post.mockImplementation(async (_path, payload) => ({ id: 'new-account', ...payload, is_active: true }));
  mocks.patch.mockImplementation(async (path, payload) => ({ ...records.find(row => row.id === path.split('/').at(-1)), ...payload }));
});

describe('User account management', () => {
  it('loads the complete list, reports actual counts and renders only public fields', async () => {
    records.push(...Array.from({ length: 110 }, (_, index) => ({ ...fixtures[3], id: `extra-${index}`, username: `extra${index}`, full_name: `Extra ${index}`, hashed_password: 'PRIVATE-HASH', totp_secret: 'PRIVATE-TOTP' })));
    renderSection();
    await screen.findByText('Extra 109');
    expect(mocks.getAll).toHaveBeenCalledWith('/auth/users', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getAllByRole('row')).toHaveLength(115);
    expect(document.body).not.toHaveTextContent('PRIVATE-HASH'); expect(document.body).not.toHaveTextContent('PRIVATE-TOTP');
    expect(screen.getByLabelText('Benutzer im Überblick')).toHaveTextContent('114Konten insgesamt3Aktiv111Deaktiviert');
  }, 20_000);

  it('combines search, role and status filters and resets no-match results', async () => {
    renderSection(); await screen.findByText('Rene Lesen');
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'RENE@' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    fireEvent.change(screen.getByRole('combobox', { name: 'Kontostatus' }), { target: { value: 'active' } });
    expect(screen.getByRole('heading', { name: 'Keine passenden Konten' })).toBeVisible();
    fireEvent.click(screen.getAllByRole('button', { name: 'Filter zurücksetzen' })[0]);
    fireEvent.change(screen.getByRole('combobox', { name: 'Rolle' }), { target: { value: 'verwalter' } });
    expect(screen.getByRole('table')).toHaveTextContent('Mara Verwaltung');
    expect(screen.queryByText('Olivia Eigentümer')).not.toBeInTheDocument();
  });

  it('shows source failure without zero counts or empty confirmation and retries', async () => {
    mocks.getAll.mockRejectedValueOnce(new Error('Datenbank vorübergehend offline'));
    renderSection();
    expect(await screen.findByRole('alert')).toHaveTextContent('Datenbank vorübergehend offline');
    expect(screen.queryByLabelText('Benutzer im Überblick')).not.toBeInTheDocument();
    expect(screen.queryByText('Keine Benutzerkonten vorhanden')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Benutzer anlegen', exact: true })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByText('Rene Lesen')).toBeVisible();
    expect(mocks.getAll).toHaveBeenCalledTimes(2);
  });

  it('rejects an incomplete or duplicate-ID list and distinguishes a confirmed empty list', async () => {
    mocks.getAll.mockResolvedValueOnce([{ ...fixtures[0], is_active: undefined }]);
    renderSection();
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Benutzerliste ist unvollständig oder ungültig.');
    mocks.getAll.mockResolvedValueOnce([fixtures[0], fixtures[0]]);
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    await waitFor(() => expect(mocks.getAll).toHaveBeenCalledTimes(2));
    await screen.findByRole('alert');
    mocks.getAll.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('heading', { name: 'Keine Benutzerkonten vorhanden' })).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('aborts loading on unmount and ignores a late response', async () => {
    let resolve;
    mocks.getAll.mockImplementation(() => new Promise(done => { resolve = done; }));
    const view = renderSection();
    const signal = mocks.getAll.mock.calls[0][1].signal;
    expect(screen.getByRole('status')).toHaveTextContent('Benutzerkonten werden geladen');
    view.unmount(); expect(signal.aborted).toBe(true);
    await act(async () => resolve(records));
    expect(screen.queryByText('Rene Lesen')).not.toBeInTheDocument();
  });

  it('creates a read-only account by default with a 12+ character passphrase and no invented invitation', async () => {
    renderSection(); await screen.findByText('Rene Lesen');
    fireEvent.click(screen.getByRole('button', { name: 'Benutzer anlegen', exact: true }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText('Rolle *')).toHaveValue('readonly');
    expect(within(dialog).getByLabelText('Startpassphrase *')).toHaveAttribute('type', 'password');
    expect(within(dialog).getByLabelText('Startpassphrase *')).toHaveAttribute('minlength', '12');
    expect(dialog).toHaveTextContent('Es wird keine Einladung per E-Mail versendet.');
    fillCreate(); submit();
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/auth/users', { username: 'newreader', full_name: 'Neue Person', email: 'new@example.com', password: 'lange geheime passphrase', role: 'readonly' }, expect.objectContaining({ signal: expect.any(AbortSignal) })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('table')).toHaveTextContent('Neue Person');
    expect(screen.getByRole('table')).not.toHaveTextContent('lange geheime passphrase');
    expect(screen.getByRole('status')).toHaveTextContent('Konto für Neue Person wurde angelegt.');
  });

  it('rejects a short passphrase without sending a creation request', async () => {
    renderSection(); await screen.findByText('Rene Lesen');
    fireEvent.click(screen.getByRole('button', { name: 'Benutzer anlegen', exact: true })); fillCreate('Short123'); submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Mindestens 12 Zeichen');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('discards a password on cancel and restores opener focus', async () => {
    const user = userEvent.setup(); renderSection(); await screen.findByText('Rene Lesen');
    const opener = screen.getByRole('button', { name: 'Benutzer anlegen', exact: true });
    await user.click(opener); fillCreate();
    await user.click(screen.getByRole('button', { name: 'Abbrechen', exact: true }));
    expect(opener).toHaveFocus();
    await user.click(opener);
    expect(screen.getByLabelText('Startpassphrase *')).toHaveValue('');
    expect(screen.getByLabelText('Benutzername *')).toHaveValue('');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('keeps a failed creation editable, focuses the error and retries with the same draft', async () => {
    mocks.post.mockRejectedValueOnce(new Error('E-Mail-Adresse ist bereits vergeben'));
    renderSection(); await screen.findByText('Rene Lesen');
    fireEvent.click(screen.getByRole('button', { name: 'Benutzer anlegen', exact: true })); fillCreate(); submit();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('E-Mail-Adresse ist bereits vergeben');
    expect(alert).toHaveFocus(); expect(screen.getByLabelText('Benutzername *')).toHaveValue('newreader');
    fireEvent.change(screen.getByLabelText('E-Mail-Adresse *'), { target: { value: 'another@example.com' } }); submit();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ email: 'another@example.com' });
  });

  it('blocks duplicate submits and closing while the real save is pending', async () => {
    let resolve;
    mocks.post.mockImplementation(() => new Promise(done => { resolve = done; }));
    renderSection(); await screen.findByText('Rene Lesen');
    fireEvent.click(screen.getByRole('button', { name: 'Benutzer anlegen', exact: true })); fillCreate(); submit(); submit();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('button', { name: 'Abbrechen', exact: true })).toBeDisabled();
    fireEvent.keyDown(document, { key: 'Escape' }); expect(dialog).toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledOnce();
    await act(async () => resolve({ ...fixtures[3], id: 'new' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('patches only changed fields including a boolean activation and owner role assignment', async () => {
    renderSection(); await edit('Rene Lesen');
    expect(screen.getByLabelText('Benutzername')).toHaveAttribute('readonly');
    expect(screen.queryByLabelText('Startpassphrase *')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Rolle *'), { target: { value: 'techniker' } });
    fireEvent.change(screen.getByLabelText('Kontostatus *'), { target: { value: 'active' } }); submit();
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledWith('/auth/users/reader', { role: 'techniker', is_active: true }, expect.objectContaining({ signal: expect.any(AbortSignal) })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('table')).toHaveTextContent('Technik');
  });

  it('does not send a patch for an unchanged account', async () => {
    renderSection(); await edit('Rene Lesen'); submit();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Es wurden keine Änderungen vorgenommen.');
  });

  it('allows only personal fields on the current owner and updates its shared profile', async () => {
    renderSection(); const dialog = await edit('Olivia Eigentümer');
    expect(within(dialog).queryByRole('combobox')).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent('Rolle und Aktivierung bleiben geschützt.');
    fireEvent.change(screen.getByLabelText('Vollständiger Name *'), { target: { value: 'Olivia Neu' } }); submit();
    await waitFor(() => expect(mocks.patch.mock.calls[0][1]).toEqual({ full_name: 'Olivia Neu' }));
    expect(mocks.updateUser).toHaveBeenCalledWith(expect.objectContaining({ full_name: 'Olivia Neu', role: 'eigentuemer', is_active: true }));
  });

  it('shows manager-specific row actions and cannot edit either owner or assign roles', async () => {
    setRole('verwalter'); renderSection(); await screen.findByText('Rene Lesen');
    expect(screen.queryByRole('button', { name: 'Benutzer anlegen', exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Olivia Eigentümer bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sven Eigentümer bearbeiten' })).not.toBeInTheDocument();
    const dialog = await edit('Rene Lesen');
    expect(within(dialog).queryByLabelText('Rolle *')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('E-Mail-Adresse *'), { target: { value: 'new-rene@example.com' } });
    fireEvent.change(screen.getByLabelText('Kontostatus *'), { target: { value: 'active' } }); submit();
    await waitFor(() => expect(mocks.patch.mock.calls[0][1]).toEqual({ email: 'new-rene@example.com', is_active: true }));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('protects the current manager activation while allowing its own contact details', async () => {
    setRole('verwalter'); renderSection(); const dialog = await edit('Mara Verwaltung');
    expect(within(dialog).queryByRole('combobox')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Vollständiger Name *'), { target: { value: 'Mara Neu' } }); submit();
    await waitFor(() => expect(mocks.patch.mock.calls[0][1]).toEqual({ full_name: 'Mara Neu' }));
  });

  it('shows server integrity rejection in the editor without changing the displayed account', async () => {
    mocks.patch.mockRejectedValue(new Error('Mindestens ein aktiver Eigentümer muss erhalten bleiben'));
    renderSection(); await edit('Sven Eigentümer');
    fireEvent.change(screen.getByLabelText('Kontostatus *'), { target: { value: 'inactive' } }); submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Mindestens ein aktiver Eigentümer');
    expect(screen.getByRole('dialog')).toBeVisible();
    const row = screen.getByText('Sven Eigentümer', { exact: true }).closest('tr');
    expect(within(row).getByText('Aktiv', { exact: true })).toBeVisible();
  });

  it.each(['readonly', 'techniker', 'buchhaltung'])('does not render management or make user calls for %s', role => {
    setRole(role); renderSection();
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(mocks.getAll).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.patch).not.toHaveBeenCalled();
  });

  it('mounts the Settings user tab lazily for administrators and hides it from read-only accounts', async () => {
    const view = render(<Settings />);
    expect(mocks.getAll).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Benutzer', exact: true }));
    expect(await screen.findByRole('heading', { name: 'Benutzerverwaltung' })).toBeVisible();
    view.unmount(); setRole('readonly'); render(<Settings />);
    expect(screen.queryByRole('button', { name: 'Benutzer', exact: true })).not.toBeInTheDocument();
    expect(mocks.getAll).toHaveBeenCalledOnce();
  });

  it('persists a language choice for the account as well as updating the visible locale', () => {
    render(<Settings />);
    fireEvent.click(screen.getByRole('button', { name: 'EN', exact: true }));
    expect(mocks.setLocale).toHaveBeenCalledWith('en-US');
    expect(mocks.updatePrefs).toHaveBeenCalledWith({ locale: 'en-US' });
  });

  it('does not request a protected admin version for non-administrators', async () => {
    setRole('readonly'); render(<Settings />);
    await act(async () => {});
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('shows a failed preferences sync with a translated retry and prevents duplicate retries', async () => {
    let resolve; mocks.retrySave.mockImplementation(() => new Promise(done => { resolve = done; }));
    mocks.saveError = 'Serverspeicherung fehlgeschlagen';
    const view = render(<Settings />);
    expect(screen.getByRole('alert')).toHaveTextContent('Persönliche Einstellungen konnten nicht mit dem Server abgeglichen werden.');
    const button = screen.getByRole('button', { name: 'Einstellungen erneut speichern' });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.retrySave).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Einstellungen werden gespeichert…' })).toBeDisabled();
    await act(async () => { mocks.saveError = null; resolve(); });
    view.rerender(<Settings />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports and retries an actual administrator version error without a toast loop', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Versionsquelle offline'));
    render(<Settings />);
    fireEvent.click(screen.getByRole('button', { name: /System/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Versionsquelle offline');
    fireEvent.click(screen.getByRole('button', { name: 'Version erneut laden' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(screen.getByText('1.0', { exact: true })).toBeVisible();
  });

  it.each(['de-DE', 'en-US', 'es-ES'])('translates management and all five roles in %s with matching locale keys', async locale => {
    mocks.locale = locale; renderSection(); await screen.findByText('Rene Lesen');
    expect(screen.getByRole('heading', { name: dictionaries[locale].userManagement.title })).toBeVisible();
    expect(screen.getByRole('combobox', { name: dictionaries[locale].userManagement.role })).toHaveTextContent(dictionaries[locale].userManagement.roles.readonly);
    expect(Object.keys(dictionaries[locale].userManagement)).toEqual(Object.keys(de.userManagement));
    expect(Object.keys(dictionaries[locale].userManagement.roles)).toEqual(Object.keys(de.userManagement.roles));
  });
});
