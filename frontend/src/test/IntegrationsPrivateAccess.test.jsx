import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import Integrations from '../pages/Integrations';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn(), role: 'eigentuemer', mode: 'all', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: { get: mocks.get, patch: mocks.patch, post: mocks.post } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({
  user: { id: 'synthetic-user', role: mocks.role, portfolio_access: mocks.mode },
}) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({
  t: key => key.split('.').reduce((node, part) => node?.[part],
    { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key,
}) }));

const result = name => ({ integrations: [{ id: 'synthetic', name, description: 'Private account settings',
  category: 'workflow', enabled: true, configured: true, planned: false, capabilities: [], required_config_keys: [] }] });
beforeEach(() => {
  mocks.get.mockReset().mockResolvedValue(result('Current private provider'));
  mocks.patch.mockReset(); mocks.post.mockReset();
  mocks.role = 'eigentuemer'; mocks.mode = 'all'; mocks.locale = 'de-DE';
});

it.each(['readonly', 'buchhaltung', 'techniker'])('does not request installation data for %s', role => {
  mocks.role = role;
  render(<Integrations />);
  expect(screen.getByRole('status')).toHaveTextContent(de.pages.integrations.administrationRequired);
  expect(mocks.get).not.toHaveBeenCalled();
});

it('does not request global provider data for a manager with selected properties', () => {
  mocks.role = 'verwalter'; mocks.mode = 'selected';
  render(<Integrations />);
  expect(screen.getByRole('status')).toBeInTheDocument();
  expect(mocks.get).not.toHaveBeenCalled();
});

it('immediately removes already loaded private data when administrative access is lost', async () => {
  const view = render(<Integrations />);
  await screen.findByText('Current private provider');
  mocks.role = 'techniker';
  view.rerender(<Integrations />);
  expect(screen.queryByText('Current private provider')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent(de.pages.integrations.administrationRequired);
  expect(mocks.get).toHaveBeenCalledTimes(1);
});

it('ignores an old response after revocation and subsequent reauthorization', async () => {
  let completeOld;
  mocks.get.mockImplementationOnce(() => new Promise(resolve => { completeOld = resolve; }));
  const view = render(<Integrations />);
  const firstSignal = mocks.get.mock.calls[0][1].signal;
  mocks.mode = 'selected'; mocks.role = 'verwalter';
  view.rerender(<Integrations />);
  expect(firstSignal.aborted).toBe(true);
  mocks.mode = 'all';
  view.rerender(<Integrations />);
  await screen.findByText('Current private provider');
  await act(async () => completeOld(result('Old revoked private provider')));
  expect(screen.queryByText('Old revoked private provider')).not.toBeInTheDocument();
  expect(screen.getByText('Current private provider')).toBeInTheDocument();
});

it.each([['en-US', en], ['es-ES', es]])('explains administrative access in %s', (locale, catalog) => {
  mocks.role = 'readonly'; mocks.locale = locale;
  render(<Integrations />);
  expect(screen.getByRole('status')).toHaveTextContent(catalog.pages.integrations.administrationRequired);
});

async function revokeAndRestore(view, role) {
  mocks.role = 'verwalter'; mocks.mode = 'selected';
  view.rerender(<Integrations />);
  expect(screen.getByRole('status')).toBeInTheDocument();
  mocks.role = role; mocks.mode = 'all';
  view.rerender(<Integrations />);
  await screen.findByText('Current private provider');
}

it.each(['eigentuemer', 'verwalter'])('ignores a late PATCH even after the same %s regains access', async role => {
  mocks.role = role;
  let finish;
  mocks.patch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<Integrations />);
  await screen.findByText('Current private provider');
  fireEvent.click(screen.getByRole('button', { name: de.pages.integrations.disable }));
  const signal = mocks.patch.mock.calls[0][2].signal;
  await revokeAndRestore(view, role);
  expect(signal.aborted).toBe(true);
  await act(async () => finish({}));
  expect(screen.getByRole('button', { name: de.pages.integrations.disable })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: de.pages.integrations.enable })).not.toBeInTheDocument();
});

it.each(['eigentuemer', 'verwalter'])('does not publish a late POST or request history after %s loses access', async role => {
  mocks.role = role;
  let finish;
  mocks.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<Integrations />);
  await screen.findByText('Current private provider');
  fireEvent.click(screen.getByRole('button', { name: de.pages.integrations.runTest }));
  const signal = mocks.post.mock.calls[0][2].signal;
  await revokeAndRestore(view, role);
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ message: 'SYNTHETIC_OLD_PRIVATE_POST' }));
  expect(screen.queryByText('SYNTHETIC_OLD_PRIVATE_POST')).not.toBeInTheDocument();
  expect(mocks.get.mock.calls.every(([url]) => url === '/integrations')).toBe(true);
});

const probe = (changes = {}) => ({ integration_id: 'email', status: 'not_supported',
  configured: true, probe_supported: false, network_checked: false,
  business_action_performed: false, test_message_sent: false, ...changes });

it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('checks configured SMTP without a message or history request in %s', async (locale, catalog) => {
  mocks.locale = locale;
  mocks.get.mockResolvedValue({ integrations: [{ ...result('Configured SMTP').integrations[0], id: 'email', category: 'communication' }] });
  mocks.post.mockResolvedValue(probe());
  render(<Integrations />);
  await screen.findByText('Configured SMTP');
  fireEvent.click(screen.getByRole('button', { name: catalog.pages.integrations.runTest }));
  await screen.findByText(catalog.pages.integrations.connectionConfigOnly);
  expect(mocks.post).toHaveBeenCalledExactlyOnceWith('/integrations/email/connection-test', {}, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(mocks.get).toHaveBeenCalledTimes(1);
});

it.each([
  [{ status: 'checked', probe_supported: true, network_checked: true }, 'connectionChecked'],
  [{ status: 'checked', network_checked: false }, 'connectionUnconfirmed'],
  [{ status: 'checked', probe_supported: true, network_checked: true, test_message_sent: true }, 'connectionUnconfirmed'],
  [{ status: 'checked', probe_supported: true, network_checked: true, integration_id: 'other' }, 'connectionUnconfirmed'],
  [{ status: 'configuration_invalid', configured: false }, 'connectionConfigInvalid'],
  [{ status: 'failed' }, 'connectionFailed'],
])('describes the actual probe outcome without invented success: %j', async (changes, key) => {
  mocks.get.mockResolvedValue({ integrations: [{ ...result('Configured SMTP').integrations[0], id: 'email' }] });
  mocks.post.mockResolvedValue(probe(changes));
  render(<Integrations />);
  await screen.findByText('Configured SMTP');
  fireEvent.click(screen.getByRole('button', { name: de.pages.integrations.runTest }));
  await screen.findByText(de.pages.integrations[key]);
});

it('keeps one pending probe and permits a deliberate retry after a recoverable error', async () => {
  let fail;
  mocks.post.mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
  mocks.post.mockResolvedValue(probe({ integration_id: 'synthetic' }));
  render(<Integrations />);
  await screen.findByText('Current private provider');
  fireEvent.click(screen.getByRole('button', { name: de.pages.integrations.runTest }));
  const pending = screen.getByRole('button', { name: de.pages.integrations.connectionChecking });
  expect(pending).toBeDisabled();
  fireEvent.click(pending);
  expect(mocks.post).toHaveBeenCalledTimes(1);
  await act(async () => fail(new Error('SYNTHETIC_RECOVERABLE_PROBE_ERROR')));
  expect(screen.getByRole('status')).toHaveTextContent('SYNTHETIC_RECOVERABLE_PROBE_ERROR');
  expect(mocks.post).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: de.pages.integrations.runTest }));
  await screen.findByText(de.pages.integrations.connectionConfigOnly);
  expect(mocks.post).toHaveBeenCalledTimes(2);
});

it.each(['patch', 'post'])('discards a late private %s error after revocation and reauthorization', async operation => {
  let fail;
  mocks[operation].mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
  const view = render(<Integrations />);
  await screen.findByText('Current private provider');
  fireEvent.click(screen.getByRole('button', { name: de.pages.integrations[operation === 'patch' ? 'disable' : 'runTest'] }));
  await revokeAndRestore(view, 'eigentuemer');
  await act(async () => fail(new Error('SYNTHETIC_PRIVATE_OLD_ERROR')));
  expect(screen.queryByText(/SYNTHETIC_PRIVATE_OLD_ERROR/)).not.toBeInTheDocument();
});
