import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PrivacyCenter from '../features/privacy/PrivacyCenter';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
const resource = { kind: 'document', id: 'doc', title: 'Vertrag Haushalt Eins', revision: 4, source_sha256: 'a'.repeat(64),
  held: false, restricted: false, can_erase: false, blockers: ['Originalakte bleibt erhalten.'], decisions: [] };
const page = items => ({ items, total: items.length });

beforeEach(() => {
  vi.resetAllMocks(); api.list.mockResolvedValue([{ id: 'tenant', full_name: 'Haushalt Eins' }]);
  api.get.mockImplementation(path => Promise.resolve(path.includes('/resources/') ? resource : page([{ id: 'doc', title: resource.title }])));
});

it('binds a decision to the reviewed source and keeps the key after a lost response', async () => {
  api.post.mockRejectedValue(new Error('Antwort verloren'));
  render(<PrivacyCenter />);
  await userEvent.selectOptions(await screen.findByLabelText('Datensatz'), 'doc');
  const button = await screen.findByRole('button', { name: 'Aufbewahrung sperren' });
  expect(button).toBeDisabled();
  await userEvent.type(screen.getByLabelText('Begründung der Entscheidung'), 'Belege wegen laufender Rückfrage aufbewahren.');
  await userEvent.click(button); await screen.findByText('Antwort verloren'); await userEvent.click(button);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
  expect(api.post.mock.calls[0]).toEqual(api.post.mock.calls[1]);
  expect(api.post.mock.calls[0][1]).toMatchObject({ expected_revision: 4, source_sha256: 'a'.repeat(64), action: 'hold' });
  expect(screen.queryByRole('button', { name: 'Löschung ausführen' })).not.toBeInTheDocument();
});

it('clears the old source when another data type is chosen', async () => {
  render(<PrivacyCenter />);
  await userEvent.selectOptions(await screen.findByLabelText('Datensatz'), 'doc');
  await screen.findByRole('heading', { name: resource.title });
  await userEvent.selectOptions(screen.getByLabelText('Datenart'), 'portal_case');
  expect(screen.queryByRole('heading', { name: resource.title })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aufbewahrung sperren' })).not.toBeInTheDocument();
});

it('requires explicit erasure confirmation in addition to the checked fingerprint', async () => {
  api.get.mockImplementation(path => Promise.resolve(path.includes('/resources/') ? { ...resource, can_erase: true, blockers: [] } : page([{ id: 'doc', title: resource.title }])));
  api.post.mockResolvedValue({ outcome: { retained: 'Historische Geschäftsakte' } });
  render(<PrivacyCenter />);
  await userEvent.selectOptions(await screen.findByLabelText('Datensatz'), 'doc');
  await userEvent.type(await screen.findByLabelText('Begründung der Entscheidung'), 'Aufbewahrungsgründe und Fristablauf sind geprüft.');
  const button = screen.getByRole('button', { name: 'Löschung ausführen' }); expect(button).toBeDisabled();
  await userEvent.click(screen.getByRole('checkbox')); await userEvent.click(button);
  await screen.findByText('Entscheidung gespeichert. Weiterhin erhalten: Historische Geschäftsakte.');
  expect(api.post.mock.calls[0][1].action).toBe('erase');
});

it('does not enable restore approval while a previously erased source still exists', async () => {
  api.get.mockImplementation(path => Promise.resolve(path.endsWith('/restore-review') ? { pending: true, revision: 2, journal_sha256: 'b'.repeat(64), reason: 'Alte Sicherung', pending_erasure: [{ kind: 'portal_case', id: 'case' }] } : page([])));
  render(<PrivacyCenter />);
  await userEvent.click(screen.getByRole('button', { name: 'Journal und Wiederherstellung' }));
  await screen.findByRole('heading', { name: 'Wiederherstellung noch gesperrt' });
  fireEvent.change(screen.getByLabelText('Begründung und Grundlage des Abgleichs'), { target: { value: 'Aktuelles Journal aus separater Ablage geprüft.' } });
  await userEvent.click(screen.getByRole('checkbox'));
  expect(screen.getByRole('button', { name: 'Geprüften Abgleich bestätigen' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

it('shows a stale request decision as a conflict without marking the request fulfilled', async () => {
  api.get.mockImplementation(path => Promise.resolve(path === '/privacy/requests/request' ? { id: 'request', state: 'open', revision: 3, source_sha256: 'c'.repeat(64), retained_records: { contracts: 1 },
    data: { subject: { full_name: 'Haushalt Eins' }, extensions: { portal_messages: [], portal_images: [], e_invoice_intakes: [] } } }
    : path.includes('/privacy/requests?') ? page([{ id: 'request', state: 'open', request_type: 'erasure', due_on: '2026-12-01' }]) : page([])));
  api.post.mockRejectedValue(new Error('Prüfstand inzwischen geändert'));
  render(<PrivacyCenter />);
  await userEvent.click(screen.getByRole('button', { name: 'Auskunfts- und Löschanfragen' }));
  await userEvent.click(await screen.findByRole('button', { name: 'Bestand und Entscheidung prüfen' }));
  await userEvent.type(await screen.findByLabelText('Begründung einschließlich zurückbehaltener Daten'), 'Vertragsakte bleibt begründet erhalten.');
  await userEvent.click(screen.getByRole('button', { name: 'Entscheidung für diesen Prüfstand speichern' }));
  await screen.findByText('Prüfstand inzwischen geändert');
  expect(api.post.mock.calls[0][1]).toMatchObject({ expected_revision: 3, source_sha256: 'c'.repeat(64) });
  expect(screen.getByRole('heading', { name: 'Haushalt Eins · Offen' })).toBeInTheDocument();
});
