import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import PortalApp from '../features/externalPortal/PortalApp';
import PortalAdmin from '../features/externalPortal/PortalAdmin';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner', role: 'eigentuemer' } }) }));
const profile = { email: 'tenant@example.test', grants: [{ id: 'grant-1', revision: 3, kind: 'tenant', property: 'Haus', unit: 'WE 1' }] };
const list = items => ({ items, skip: 0, limit: 25, total: items.length });
const ok = data => Promise.resolve({ ok: true, status: 200, json: async () => data });

beforeEach(() => {
  vi.resetAllMocks(); window.history.replaceState(null, '', '/portal');
  vi.stubGlobal('fetch', vi.fn(path => ok(path.endsWith('/me') ? profile : list([]))));
});

describe('isolated external portal', () => {
  it('returns keyboard focus to the cases heading when leaving a conversation', async () => {
    const item = { id: 'case-1', title: 'Tastaturschaden', status: 'open' };
    fetch.mockImplementation(path => ok(path.endsWith('/me') ? profile
      : path.startsWith('/api/v1/portal/me/cases/case-1?') ? { ...item, messages: [], skip: 0, limit: 50, total: 0 }
        : path.startsWith('/api/v1/portal/me/cases?') ? list([item]) : list([])));
    render(<PortalApp />);
    await userEvent.click(await screen.findByRole('button', { name: 'Meine Anliegen' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Verlauf und Rückfragen öffnen' }));
    expect(await screen.findByRole('heading', { name: 'Tastaturschaden' })).toHaveFocus();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück zu meinen Anliegen' }));
    expect(await screen.findByRole('heading', { name: 'Meine Anliegen', exact: true })).toHaveFocus();
    await screen.findByRole('button', { name: 'Verlauf und Rückfragen öffnen' });
    expect(screen.getByRole('heading', { name: 'Meine Anliegen', exact: true })).toHaveFocus();
  });

  it('loads only its own session and documents without internal authorization or API calls', async () => {
    localStorage.setItem('access_token', 'internal-secret');
    render(<PortalApp />);
    await screen.findByText('Keine freigegebenen Dokumente für diese Suche vorhanden.');
    expect(api.get).not.toHaveBeenCalled(); expect(api.list).not.toHaveBeenCalled();
    for (const [path, options] of fetch.mock.calls) {
      expect(path.startsWith('/api/v1/portal/')).toBe(true);
      expect(options.headers.Authorization).toBeUndefined();
      expect(JSON.stringify(options)).not.toContain('internal-secret');
      expect(options.credentials).toBe('same-origin');
    }
    localStorage.removeItem('access_token');
  });

  it('removes the invitation secret from the URL before any requests and sends it only on acceptance', async () => {
    const token = 'invitation'.repeat(5);
    window.history.replaceState(null, '', `/portal/accept#${token}`);
    render(<PortalApp />);
    await screen.findByRole('heading', { name: 'Einladung annehmen' });
    expect(window.location.hash).toBe(''); expect(fetch).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText('Passwort'), 'PersonalPassword123');
    await userEvent.click(screen.getByRole('button', { name: 'Einladung annehmen' }));
    await screen.findByRole('heading', { name: 'Meine Unterlagen und Anliegen' });
    const accepted = fetch.mock.calls.find(([path]) => path.endsWith('/accept'));
    expect(JSON.parse(accepted[1].body)).toEqual({ token, password: 'PersonalPassword123' });
    expect(fetch.mock.calls.every(([path]) => !path.includes(token))).toBe(true);
  });

  it('keeps damage submissions idempotent after a lost response and displays the server error', async () => {
    fetch.mockImplementation((path, options) => options.method === 'POST' ? Promise.reject(new Error('Antwort verloren')) : ok(path.endsWith('/me') ? profile : list([])));
    render(<PortalApp />);
    await userEvent.click(await screen.findByRole('button', { name: 'Schaden melden' }));
    await userEvent.type(screen.getByLabelText('Kurzer Titel'), 'Fenster undicht');
    await userEvent.type(screen.getByLabelText('Was ist passiert?'), 'Bei Regen tropft Wasser durch den Rahmen.');
    const form = screen.getByRole('button', { name: 'Schaden verbindlich melden' }).closest('form');
    fireEvent.submit(form); await screen.findByText('Antwort verloren'); fireEvent.submit(form);
    await waitFor(() => expect(fetch.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(2));
    const commands = fetch.mock.calls.filter(([, options]) => options.method === 'POST').map(([, options]) => JSON.parse(options.body.get('command')));
    expect(commands[0]).toEqual(commands[1]); expect(commands[0].expected_revision).toBe(3);
    expect(commands[0]).not.toHaveProperty('property_id');
  });

  it('uses a publication route for previews and removes the rendered document on session loss', async () => {
    fetch.mockImplementation(path => ok(path.endsWith('/me') ? profile : list([{ id: 'publication-1', title: 'Nur mein Vertrag', version: 2, filename: 'Vertrag.pdf' }])));
    render(<PortalApp />);
    expect(await screen.findByRole('link', { name: 'Vorschau öffnen' })).toHaveAttribute('href', '/api/v1/portal/me/documents/publication-1/preview');
    act(() => window.dispatchEvent(new Event('portal-session-lost')));
    expect(screen.queryByText('Nur mein Vertrag')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Am Portal anmelden' })).toBeInTheDocument();
  });
});

describe('explicit internal publication', () => {
  const access = { id: 'grant-1', email: profile.email, kind: 'tenant', contract_id: 'contract-1', active: true, identity_active: true,
    identity_revision: 2, revision: 3, verification: 'Identität persönlich geprüft.', binding: { property_id: 'property-1', unit_id: 'unit-1' } };
  beforeEach(() => {
    api.list.mockResolvedValue([]);
    api.get.mockImplementation(path => Promise.resolve(path.endsWith('/configuration') ? { available: true, url: 'https://portal.example.test' }
      : path.includes('/publications') ? [] : path.includes('/documents?') ? list([{ id: 'version-2', title: 'Meine Vertragsfassung', number: 2, filename: 'Vertrag.pdf', sha256: 'a'.repeat(64) }]) : list([access])));
  });

  it('restores the invitation action after dismissing the once-shown link', async () => {
    api.list.mockImplementation(path => Promise.resolve(path.startsWith('/contracts') ? [{ id: 'contract-1', tenant_id: 'tenant-1', property_id: 'property-1', contract_number: 'Vertrag 1' }]
      : path.startsWith('/tenants') ? [{ id: 'tenant-1', full_name: 'Testmieter', email: profile.email }] : []));
    api.post.mockResolvedValue({ email: profile.email, invitation_url: 'https://portal.example.test/portal/accept#one-use', expires_at: '2026-10-27T12:00:00Z' });
    render(<MemoryRouter><PortalAdmin /></MemoryRouter>);
    await userEvent.click(screen.getByText('Geprüfte Partei einladen'));
    await waitFor(() => expect(screen.getByLabelText('Geprüftes Verhältnis')).toBeEnabled());
    await userEvent.selectOptions(screen.getByLabelText('Geprüftes Verhältnis'), 'contract-1');
    await userEvent.type(screen.getByLabelText('Dokumentierte Identitäts- und Verhältnisprüfung'), 'Identität und Vertrag persönlich geprüft.');
    const create = screen.getByRole('button', { name: 'Einladungslink erstellen' });
    await userEvent.click(create);
    await screen.findByLabelText('Einmalig angezeigter Einladungslink');
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Linkanzeige schließen' }));
    expect(screen.queryByLabelText('Einmalig angezeigter Einladungslink')).not.toBeInTheDocument();
    expect(create).toHaveFocus();
  });

  it('requires a written reason and binds revocation to the displayed grant revision', async () => {
    render(<MemoryRouter><PortalAdmin /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Zugang und Freigaben verwalten' }));
    const button = screen.getByRole('button', { name: 'Diese Zuordnung widerrufen' }); expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Begründung für Änderung oder Widerruf'), 'Die Person hat den Widerruf angefordert.');
    api.put.mockRejectedValue(new Error('Antwort verloren'));
    await userEvent.click(button); await screen.findByText(/Antwort verloren/); await userEvent.click(button);
    expect(api.put.mock.calls[0][0]).toBe('/portal-admin/grants/grant-1');
    expect(api.put.mock.calls[0][1]).toMatchObject({ active: false, expected_revision: 3 });
    expect(api.put.mock.calls[0][1]).toEqual(api.put.mock.calls[1][1]);
  });

  it('publishes exactly a selected archived version for one party, never from listing alone', async () => {
    render(<MemoryRouter><PortalAdmin /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Zugang und Freigaben verwalten' }));
    await waitFor(() => expect(screen.getByLabelText('Passende Originalfassung')).toBeEnabled());
    expect(api.post).not.toHaveBeenCalled();
    await userEvent.selectOptions(screen.getByLabelText('Passende Originalfassung'), 'version-2');
    await userEvent.type(screen.getByLabelText('Grund und Prüfung der Veröffentlichung'), 'Eigene Vertragsunterlagen anhand Zuordnung geprüft.');
    api.post.mockResolvedValue({ id: 'publication-1' });
    await userEvent.click(screen.getByRole('button', { name: 'Diese Fassung für diese Partei veröffentlichen' }));
    expect(api.post.mock.calls[0][0]).toBe('/portal-admin/grants/grant-1/publications');
    expect(api.post.mock.calls[0][1]).toMatchObject({ grant_revision: 3, version_id: 'version-2', title: 'Meine Vertragsfassung' });
  });

  it('keeps a once-shown recovery link visible across the refreshed access listing', async () => {
    render(<MemoryRouter><PortalAdmin /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Zugang und Freigaben verwalten' }));
    await userEvent.click(screen.getByText('Vergessenes Portalpasswort zurücksetzen'));
    const button = screen.getByRole('button', { name: 'Zugang zurücksetzen und neuen Link erstellen' });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Erneute Identitätsprüfung dokumentieren'), 'Identität durch persönlich bekannten Rückruf geprüft.');
    api.post.mockResolvedValue({ email: profile.email, invitation_url: 'https://portal.example.test/portal/accept#one-use', expires_at: '2026-10-27T12:00:00Z' });
    await userEvent.click(button);
    expect(api.post.mock.calls[0][1]).toMatchObject({ expected_revision: 2, grant_revision: 3 });
    expect(await screen.findByLabelText('Einmalig angezeigter Wiederherstellungslink')).toHaveValue('https://portal.example.test/portal/accept#one-use');
    await userEvent.click(screen.getByRole('button', { name: 'Wiederherstellungslink ausblenden' }));
    expect(screen.queryByLabelText('Einmalig angezeigter Wiederherstellungslink')).not.toBeInTheDocument();
  });
});
