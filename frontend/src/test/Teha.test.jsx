import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import Teha from '../pages/Teha';

const access = vi.hoisted(() => ({ write: true, generation: 0 }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.write }));
const connection = { id: 'c1', name: 'TEHA Test', enabled: true };
const item = { id: 'item1', kind: 'document', source_sha256: 'a'.repeat(64), content_sha256: 'b'.repeat(64),
  source: { title: 'Abrechnung.pdf', identity: { lieg_nr: '00017', reference: 'ref-a' }, raw: { unknown_field: [1, null] } } };
const preview = { state: 'new', mapping_revision: 1, targets: [{ kind: 'property', id: 'p1', revision: 'revision-p1' }],
  preview_sha256: 'c'.repeat(64), errors: [], evidence_gap: 'Kein belegter Schreibvertrag.' };
const receipt = { id: 'receipt1', item_id: 'item1', document_id: 'doc1', content_sha256: 'b'.repeat(64) };
const page = items => ({ items, total: items.length, next_cursor: null });
let currentPreview, runs, custom;

beforeEach(() => {
  vi.resetAllMocks(); access.write = true; access.generation = 0; currentPreview = preview; runs = []; custom = null;
  api.captureSession.mockImplementation(() => {
    const generation = access.generation;
    return () => { if (generation !== access.generation) throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); };
  });
  api.get.mockImplementation(url => {
    const override = custom?.(url); if (override !== undefined) return override;
    if (url.startsWith('/teha/connections?')) return Promise.resolve(page([connection]));
    if (url.endsWith('/evidence')) return Promise.resolve({ observed_on: '2026-10-18', source_sha256: 'e'.repeat(64),
      message: 'Öffentliche Portaldatei anonym geprüft; Schreibabnahme offen.', candidates: [], missing_acceptance: ['Portalbeleg und Ergebnisabgleich'] });
    if (url.includes('/runs?')) return Promise.resolve(page(runs));
    if (url.includes('/batches?')) return Promise.resolve(page([{ id: 'batch1', state: 'ready', next_index: 1, total: 1, revision: 2 }]));
    if (url.includes('/items?')) return Promise.resolve(page([item]));
    if (url.endsWith('/preview')) return Promise.resolve(currentPreview);
    if (url.includes('/choices/')) return Promise.resolve(page([{ kind: 'property', id: 'p1', revision: 'revision-p1', title: 'Haus A' }]));
    if (url.includes('/history?') || url.includes('/returns?')) return Promise.resolve(page([]));
    if (url === '/integration-connections/c1') return Promise.resolve({ ...connection, revision: 4 });
    throw new Error('Unexpected GET ' + url);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function open(url = '/teha?connection=c1&batch=batch1') {
  render(<MemoryRouter initialEntries={[url]}><Teha /></MemoryRouter>);
}
async function review() {
  open(); fireEvent.click(await screen.findByRole('button', { name: 'Abrechnung.pdf · Dokument' }));
  await screen.findByRole('button', { name: 'Geprüfte Übernahme bestätigen' });
}

it('does not import on open and clearly disables both unevidenced outbound actions', async () => {
  open(); await screen.findByText('TEHA Test');
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Kosten-/Nutzerdaten übertragen' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Wartungsauftrag senden' })).toBeDisabled();
});

it('confirms the exact server preview and offers the actual original receipt', async () => {
  api.post.mockResolvedValue(receipt);
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Geprüfte Übernahme bestätigen' }));
  await screen.findByRole('heading', { name: 'Übernahme bestätigt' });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe('/teha/c1/items/item1/confirm');
  expect(api.post.mock.calls[0][1]).toMatchObject({ preview_sha256: 'c'.repeat(64), confirm: true });
  expect(api.post.mock.calls[0][1].idempotency_key).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Original herunterladen' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Dokumentenakte' })).toHaveAttribute('href', '/documents?focus_id=doc1');
});

it('retains the exact command after a lost response and reuses its repetition key', async () => {
  api.post.mockRejectedValueOnce(new Error('Speicherantwort verloren')).mockResolvedValueOnce(receipt);
  await review(); fireEvent.click(screen.getByRole('button', { name: 'Geprüfte Übernahme bestätigen' }));
  await screen.findByText('Speicherantwort verloren');
  const first = api.post.mock.calls[0];
  expect(screen.getByRole('button', { name: 'Geprüfte Übernahme bestätigen' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Speicherstatus prüfen' }));
  await screen.findByRole('heading', { name: 'Übernahme bestätigt' });
  expect(api.post.mock.calls[1]).toEqual(first);
});

it('keeps conflicts and unknown fields visible and prevents confirmation', async () => {
  currentPreview = { ...preview, state: 'conflict', errors: ['Quellstand geändert.'] };
  await review();
  expect(screen.getByRole('button', { name: 'Geprüfte Übernahme bestätigen' })).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('Quellstand geändert.');
  expect(screen.getByText(/unknown_field/)).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('separates preparation from explicit read dispatch', async () => {
  api.post.mockResolvedValue({ id: 'run1', revision: 1 });
  open(); await screen.findByText('TEHA Test');
  fireEvent.click(screen.getByRole('button', { name: 'Empfang vorbereiten' }));
  await screen.findByRole('button', { name: 'Lesenden Empfang ausdrücklich starten' });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe('/integration-connections/c1/runs');
  expect(api.post.mock.calls[0][1]).toMatchObject({ config_revision: 4, action: 'inventory', payload: {} });
  fireEvent.click(screen.getByRole('button', { name: 'Lesenden Empfang ausdrücklich starten' }));
  await act(async () => {});
  expect(api.post.mock.calls[1][0]).toBe('/integration-connections/c1/runs/run1/dispatch');
  expect(api.post.mock.calls[1][1]).toMatchObject({ base_revision: 1, confirm: true });
});

it('follows the server cursor and displays the complete count rather than just the page size', async () => {
  custom = url => url.includes('/items?') ? Promise.resolve(url.includes('cursor=next-page') ?
    { ...page([{ ...item, id: 'last', source: { ...item.source, title: 'Letzter Eintrag.pdf' } }]), total: 10007 } :
    { ...page([item]), total: 10007, next_cursor: 'next-page' }) : undefined;
  open(); await screen.findByText('10007 Einträge insgesamt');
  const section = screen.getByRole('heading', { name: 'Empfangene Einträge' }).closest('section');
  fireEvent.click(within(section).getByRole('button', { name: 'Weitere Einträge' }));
  await screen.findByRole('button', { name: 'Letzter Eintrag.pdf · Dokument' });
  expect(api.get.mock.calls.some(([url]) => url.includes('cursor=next-page'))).toBe(true);
  expect(within(section).getByRole('button', { name: 'Weitere Einträge' })).toBeDisabled();
});

it('ignores late publication success after a session switch', async () => {
  let resolve;
  api.post.mockReturnValue(new Promise(done => { resolve = done; }));
  await review(); fireEvent.click(screen.getByRole('button', { name: 'Geprüfte Übernahme bestätigen' }));
  await act(async () => { access.generation++; window.dispatchEvent(new Event('workspace-logout')); resolve(receipt); });
  expect(screen.queryByRole('heading', { name: 'Übernahme bestätigt' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Original herunterladen' })).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('shows the typed expired-auth error and never retries automatically', async () => {
  runs = [{ id: 'r1', action: 'inventory', state: 'retryable', safe_summary: 'Lesender Empfang fehlgeschlagen.', revision: 3 }];
  custom = url => url.endsWith('/diagnostic') ? Promise.resolve({ message: 'Die TEHA-Anmeldung ist abgelaufen.' }) : undefined;
  open(); await screen.findByText('Die TEHA-Anmeldung ist abgelaufen.');
  expect(screen.getByRole('button', { name: 'Lesenden Empfang erneut versuchen' })).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('prepares an original from the exact directory identity and leaves dispatch explicit', async () => {
  const directory = { ...item, content_sha256: null };
  custom = url => url.includes('/items?') ? Promise.resolve(page([directory])) : undefined;
  api.post.mockResolvedValue({ id: 'original-run', revision: 1 });
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Originalempfang vorbereiten' }));
  await screen.findByRole('button', { name: 'Lesenden Empfang ausdrücklich starten' });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][1]).toMatchObject({ action: 'document', payload: { lieg_nr: '00017', reference: 'ref-a' } });
});

it('downloads the exact frozen return hash and displays its stale-source validation', async () => {
  const draft = { id: 'draft1', snapshot_sha256: 'f'.repeat(64), source_changed: true, snapshot: { kind: 'cost_user_data' },
    validation: { local_valid: false, issues: [{ code: 'source_changed', message: 'Quelle verändert – neu vorbereiten.' }],
      warnings: [{ code: 'unverified', message: 'Kein Portalbeleg.' }], summary: { cost_count: 2, contract_count: 1, user_count: 1, total_decimal: '123.46', currency: 'EUR' } } };
  custom = url => url.includes('/returns?') ? Promise.resolve(page([draft])) : undefined;
  api.getBlob.mockResolvedValue(new Blob(['{}'], { type: 'application/json' }));
  URL.createObjectURL = vi.fn(() => 'blob:teha-packet'); URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  open(); await screen.findByText('Quelle verändert – neu vorbereiten.');
  expect(screen.getByText('Summe lokaler Kosten: 123.46 EUR')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Lokales Prüfpaket herunterladen' }));
  await act(async () => {});
  expect(api.getBlob).toHaveBeenCalledWith('/teha/c1/returns/draft1/export?snapshot_sha256=' + 'f'.repeat(64));
  expect(api.post).not.toHaveBeenCalled();
});

it('prepares a local follow-up using explicitly selected received users and no provider write', async () => {
  const order = { ...item, id: 'order1', kind: 'technical_order', content_sha256: null,
    source: { title: 'Techniktermin', identity: { termin_id: 41 }, raw: { auftragNummer: 501, liegenschaftsnummer: '00017' } } };
  currentPreview = { ...preview, state: 'unchanged', publication: { project_id: 'project1' } };
  custom = url => {
    if (url.includes('/items?')) return Promise.resolve(page([order]));
    if (url.includes('/follow-up-users?')) return Promise.resolve(page([{ id: 'user-item', source_sha256: 'd'.repeat(64), external_user_id: 23, name: 'Testperson', selectable: true }]));
    if (url === '/workspace/source/maintenance/project1') return Promise.resolve({ id: 'project1', revision: 'project-revision' });
    return undefined;
  };
  api.post.mockResolvedValue({ id: 'draft-order', snapshot_sha256: 'f'.repeat(64) });
  open(); fireEvent.click(await screen.findByRole('button', { name: 'Techniktermin · Techniktermin' }));
  const toggle = await screen.findByRole('checkbox', { name: 'Belegte Folgeauftrag-Feldstruktur in die lokale Vorschau aufnehmen' });
  fireEvent.click(toggle);
  expect(screen.getByRole('button', { name: 'Rückübertragung lokal vorbereiten (ohne Versand)' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Auftraggebername'), { target: { value: 'Testauftraggeber' } });
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Testperson · TEHA-Nutzer 23' }));
  fireEvent.click(screen.getByRole('button', { name: 'Rückübertragung lokal vorbereiten (ohne Versand)' }));
  await act(async () => {});
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe('/teha/c1/items/order1/prepare-return');
  expect(api.post.mock.calls[0][1]).toMatchObject({ follow_up: { orderer_name: 'Testauftraggeber', orderer_email: '',
    users: [{ item_id: 'user-item', source_sha256: 'd'.repeat(64) }] }, source: { kind: 'maintenance', id: 'project1', revision: 'project-revision' } });
});
