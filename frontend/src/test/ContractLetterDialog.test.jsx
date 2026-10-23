import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import { MemoryRouter } from 'react-router-dom';
import ContractLetterDialog from '../features/letters/ContractLetterDialog';
import LetterTemplates from '../pages/LetterTemplates';
import { downloadPath } from '../features/letters/lettersApi';

const mocks = vi.hoisted(() => ({ auth: { user: { id: 'owner', role: 'eigentuemer' }, write: null } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url }) => <div role="img" aria-label="Briefvorschau" data-url={url} /> }));
vi.mock('../api', () => ({ api: {} }));

const bytes = new TextEncoder().encode('%PDF-1.7 template letter');
const hash = createHash('sha256').update(bytes).digest('hex');
const blob = { arrayBuffer: async () => bytes.buffer };
const kinds = [
  { kind: 'rent_increase', label: 'Mieterhöhung (§ 558 BGB)', description: 'Prüft Fristen.', placeholders: [{ name: 'mieter.name', label: 'Name des Mieters' }], blocks: [{ name: 'tabelle.mieterhoehung', label: 'Tabelle' }], inputs: [
    { key: 'receipt_date', label: 'Voraussichtlicher Zugang beim Mieter', type: 'date', required: true },
    { key: 'new_cold_rent', label: 'Neue Nettokaltmiete (€ monatlich)', type: 'amount', required: true },
  ] },
  { kind: 'free', label: 'Freies Schreiben', description: 'Eigener Text.', placeholders: [{ name: 'mieter.name', label: 'Name des Mieters' }], blocks: [], inputs: [] },
];
const templates = [
  { id: 'builtin:rent_increase', kind: 'rent_increase', builtin: true, name: 'Mieterhöhung', revision: 1, subject: 'S', salutation: '', body: 'B', closing: 'C', appendix: '' },
  { id: 'builtin:free', kind: 'free', builtin: true, name: 'Freies Schreiben', revision: 1, subject: 'S', salutation: '', body: '', closing: 'C', appendix: '' },
];
const context = (extra = {}) => ({ source_revision: 'source-1', can_publish: true, templates, kinds, warnings: [], originals: [], letterhead: {}, ...extra });
const data = { recipient_name: 'Mia Muster', recipient_address: 'Weg 1\n01099 Dresden', issue_date: '2026-10-20', subject: 'Mieterhöhungsverlangen', salutation: 'Guten Tag Mia Muster,', body: 'Neue Miete **715,00 €**', closing: 'Mit freundlichen Grüßen', signature: 'Linda Reiser', appendix: '' };
const composed = (inputs, filled = true, checks = []) => ({ source_revision: 'source-1', template: { id: 'builtin:rent_increase', revision: 1, kind: 'rent_increase', name: 'Mieterhöhung' }, inputs, data: filled ? data : null, checks, blocks: {} });
const review = (body, draft = false, checks = []) => ({ state: 'preview', review_hash: 'b'.repeat(64), pdf_sha256: hash, review: { source_revision: body.source_revision, data: body.data, draft, checks, pdf_sha256: hash } });
const saved = { document_id: 'doc-7', review_hash: 'b'.repeat(64), pdf_sha256: hash, subject: 'Mieterhöhungsverlangen', issue_date: '2026-10-20', download_url: '/files/download?key=template-letters%2Fdoc-7.pdf' };

function serviceFor({ draft = false, checks = [] } = {}) {
  return {
    context: vi.fn().mockResolvedValue(context()),
    compose: vi.fn(async (_id, request) => request.inputs
      ? composed(request.inputs, true, checks)
      : composed({ receipt_date: '2026-10-23', new_cold_rent: null }, false)),
    preview: vi.fn(async (_id, body) => review(body, draft, checks)),
    previewPdf: vi.fn().mockResolvedValue(blob),
    publish: vi.fn().mockResolvedValue(saved),
    original: vi.fn().mockResolvedValue(blob),
  };
}
const mount = (service, props = {}) => render(<MemoryRouter><ContractLetterDialog contractId="contract-7" service={service} onClose={vi.fn()} {...props} /></MemoryRouter>);

async function writeLetter(service) {
  await screen.findByLabelText('Vorlage');
  fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
  const rent = await screen.findByLabelText('Neue Nettokaltmiete (€ monatlich) *');
  fireEvent.change(rent, { target: { value: '715' } });
  fireEvent.click(screen.getByRole('button', { name: 'Text erstellen' }));
  await screen.findByLabelText('Betreff *');
  expect(service.compose).toHaveBeenLastCalledWith('contract-7', expect.objectContaining({ template_id: 'builtin:rent_increase', inputs: { receipt_date: '2026-10-23', new_cold_rent: '715' } }), expect.anything());
  fireEvent.click(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' }));
  await screen.findByRole('img', { name: 'Briefvorschau' });
}

beforeEach(() => {
  mocks.auth = { user: { id: 'owner', role: 'eigentuemer' }, write: null };
  vi.stubGlobal('crypto', { subtle: webcrypto.subtle, randomUUID: vi.fn(() => 'letter-command-1') });
  URL.createObjectURL = vi.fn(() => 'blob:letter'); URL.revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('letter from a template', () => {
  it('asks for the inputs of the kind, fills the text and archives the reviewed PDF once', async () => {
    const service = serviceFor({ checks: [{ level: 'info', text: 'Kappungsgrenze eingehalten.' }] });
    const onPublished = vi.fn();
    mount(service, { onPublished });
    await writeLetter(service);
    expect(screen.getAllByText(/Kappungsgrenze eingehalten/).length).toBeGreaterThan(0);
    const archive = screen.getByRole('button', { name: 'Als Original archivieren' });
    expect(archive).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /PDF geprüft/ }));
    fireEvent.click(archive);
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(saved));
    expect(service.publish).toHaveBeenCalledWith('contract-7', expect.objectContaining({
      source_revision: 'source-1', template_id: 'builtin:rent_increase', review_hash: 'b'.repeat(64), idempotency_key: 'letter-command-1',
      data: expect.objectContaining({ subject: 'Mieterhöhungsverlangen' }),
    }), expect.anything());
    expect(screen.getByText(/als Original in den Dokumenten des Vertrags abgelegt/)).toBeInTheDocument();
    const history = screen.getByRole('region', { name: 'Archivierte Briefe' });
    expect(within(history).getByText('Mieterhöhungsverlangen')).toBeInTheDocument();
  });

  it('shows errors and keeps a draft from being archived', async () => {
    const service = serviceFor({ draft: true, checks: [{ level: 'error', text: 'Die neue Miete überschreitet die Kappungsgrenze.' }] });
    mount(service);
    await writeLetter(service);
    expect(screen.getByRole('heading', { name: 'Entwurf – so nicht archivierbar' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /PDF geprüft/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
    expect(screen.getByText('1 Fehler verhindert die Archivierung.')).toBeInTheDocument();
    expect(service.publish).not.toHaveBeenCalled();
  });

  it('locks the preview when inputs change after the text was made, and asks before discarding', async () => {
    const service = serviceFor();
    const onClose = vi.fn();
    mount(service, { onClose });
    await writeLetter(service);
    fireEvent.change(screen.getByLabelText('Neue Nettokaltmiete (€ monatlich) *'), { target: { value: '720' } });
    expect(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' })).toBeDisabled();
    expect(screen.getByText('Die Angaben wurden geändert: bitte den Text neu erstellen.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Geändert' } });
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(screen.getByRole('alertdialog', { name: 'Brief verwerfen?' })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('keeps an unclear archive answer locked and retries the same command', async () => {
    const service = serviceFor();
    service.publish.mockRejectedValueOnce(Object.assign(new Error('Netzwerkfehler'), { statusCode: 502 }));
    mount(service);
    await writeLetter(service);
    fireEvent.click(screen.getByRole('checkbox', { name: /PDF geprüft/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Als Original archivieren' }));
    const retry = await screen.findByRole('button', { name: 'Archivierung erneut prüfen' });
    fireEvent.click(retry);
    await waitFor(() => expect(service.publish).toHaveBeenCalledTimes(2));
    expect(service.publish.mock.calls[0][1]).toEqual(service.publish.mock.calls[1][1]);
  });

  it('only follows archived letter downloads', () => {
    expect(downloadPath('/files/download?key=template-letters%2Fdoc.pdf')).toBe('/files/download?key=template-letters%2Fdoc.pdf');
    expect(() => downloadPath('https://example.test/x.pdf')).toThrow();
    expect(() => downloadPath('/files/download?key=documents%2Fx.pdf')).toThrow();
  });
});

describe('letter templates page', () => {
  const list = { items: [...templates, { id: '11111111-1111-1111-1111-111111111111', kind: 'free', builtin: false, name: 'Hausordnung', revision: 3, subject: 'Hausordnung', salutation: '', body: 'Text', closing: 'Gruß', appendix: '', archived: false }], kinds };

  it('copies a built-in template with its kind and inserts placeholders at the cursor', async () => {
    const service = { list: vi.fn().mockResolvedValue(list), create: vi.fn().mockResolvedValue({ name: 'Mieterhöhung (eigene Fassung)' }), update: vi.fn() };
    render(<MemoryRouter><LetterTemplates service={service} /></MemoryRouter>);
    await screen.findByText('Hausordnung');
    fireEvent.click(screen.getAllByRole('button', { name: 'Als eigene Vorlage kopieren' })[0]);
    expect(screen.getByLabelText('Art')).toBeDisabled();
    const body = screen.getByLabelText('Text');
    fireEvent.focus(body);
    fireEvent.click(screen.getByRole('button', { name: /mieter\.name/ }));
    expect(body.value).toContain('{{mieter.name}}');
    fireEvent.click(screen.getByRole('button', { name: 'Vorlage speichern' }));
    await waitFor(() => expect(service.create).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'rent_increase', based_on: 'builtin:rent_increase', name: 'Mieterhöhung (eigene Fassung)', idempotency_key: 'letter-command-1',
    })));
  });

  it('edits an own template against its revision and archives it', async () => {
    const service = { list: vi.fn().mockResolvedValue(list), create: vi.fn(), update: vi.fn().mockResolvedValue({ name: 'Hausordnung' }) };
    render(<MemoryRouter><LetterTemplates service={service} /></MemoryRouter>);
    await screen.findByText('Hausordnung');
    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    fireEvent.click(screen.getByRole('button', { name: 'Archivieren' }));
    await waitFor(() => expect(service.update).toHaveBeenCalledWith('11111111-1111-1111-1111-111111111111',
      expect.objectContaining({ archived: true, base_revision: 3, name: 'Hausordnung' })));
    expect(service.update.mock.calls[0][1]).not.toHaveProperty('kind');
  });

  it('shows built-in templates read-only to accounts without the right to change them', async () => {
    mocks.auth = { user: { id: 'tech', role: 'techniker' }, write: ['/maintenance'] };
    const service = { list: vi.fn().mockResolvedValue(list), create: vi.fn(), update: vi.fn() };
    render(<MemoryRouter><LetterTemplates service={service} /></MemoryRouter>);
    await screen.findByText('Hausordnung');
    expect(screen.queryByRole('button', { name: 'Neue Vorlage' })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Ansehen' })[0]);
    expect(screen.getByLabelText('Text')).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Vorlage speichern' })).not.toBeInTheDocument();
  });
});
