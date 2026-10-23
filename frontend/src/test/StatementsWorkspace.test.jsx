import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BrowserRouter, MemoryRouter, useNavigate } from 'react-router-dom';
import Statements from '../pages/Statements';
import { api } from '../api';
import { mayWrite } from '../utils/permissions';

const auth = vi.hoisted(() => ({ current: null }));
const confirm = vi.hoisted(() => vi.fn(async () => true));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.current,
  useCanWrite: area => !auth.current?.user || mayWrite(auth.current.write, area || '/billing/periods') }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => confirm }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../features/billing/StatementLetterDialog', () => ({ default: ({ statementId }) => <div role="dialog" aria-label="Persönliches Schreiben">{statementId}</div> }));

const first = { id: 'bp1', property_id: 'p1', label: 'Abrechnung A', start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' };
const second = { id: 'bp2', property_id: 'p2', label: 'Abrechnung B', start_date: '2026-01-01', end_date: '2026-12-31', status: 'finalized' };
let data;
const page = (entry = '/statements') => <MemoryRouter initialEntries={[entry]}><Statements /></MemoryRouter>;
const open = async (name = 'Haus A') => {
  const cell = await screen.findByRole('cell', { name });
  await act(async () => { fireEvent.click(cell.closest('tr')); });
};
beforeEach(() => {
  vi.clearAllMocks(); auth.current = null;
  data = {
    '/billing/periods': [first, second], '/properties': [{ id: 'p1', name: 'Haus A' }, { id: 'p2', name: 'Haus B' }],
    '/units': [{ id: 'u', label: 'Wohnung A' }], '/contracts': [{ id: 'ct', tenant_id: 'tn' }], '/tenants': [{ id: 'tn', full_name: 'Musterpartei' }],
    '/billing/allocation-keys': [{ id: 'key1', property_id: 'p1', name: 'Fläche Haus A', key_type: 'area_sqm' },
      { id: 'key2', property_id: 'p2', name: 'Fläche Haus B', key_type: 'area_sqm' }],
    '/billing/cost-items': [{ id: 'cost', billing_period_id: 'bp1', description: 'Wasser', amount: 123.45,
      allocation_key_id: 'key1', is_recoverable: true, source_document_id: 'doc1', cost_category: 'water',
      vat_rate: 7, net_amount: 115.37, gross_amount: 123.45, service_contract_invoice_id: 'source-bill' }],
    '/billing/statements': [{ id: 'stmt1', billing_period_id: 'bp1', unit_id: 'u', contract_id: 'ct', party: 'tenant',
      total_cost: 123.45, advance_paid: 100, balance: 23.45, status: 'draft', line_items: [{ description: 'Wasser', total_amount: 123.45, allocated_amount: 123.45 }] }],
  };
  api.list.mockImplementation(async path => data[path] || []);
  api.get.mockImplementation(async path => path.endsWith('/preflight') ? { has_blockers: false, blockers: [], warnings: [], metrics: {} } : []);
  api.put.mockImplementation(async (path, body) => { data['/billing/cost-items'][0] = { ...body }; return body; });
  api.post.mockImplementation(async (path, body) => ({ id: 'saved', ...body }));
  api.del.mockImplementation(async () => { data['/billing/cost-items'] = []; });
});
afterEach(() => { window.history.replaceState({}, '', '/'); });

describe('Billing workspace', () => {
  it('filters periods by property, year and status without hiding the remaining full stock', async () => {
    render(page()); await screen.findByRole('cell', { name: 'Haus A' });
    fireEvent.change(screen.getByLabelText('Jahr'), { target: { value: '2026' } });
    expect(screen.queryByRole('cell', { name: 'Haus A' })).not.toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Haus B' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Jahr'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Immobilie'), { target: { value: 'p1' } });
    expect(screen.getByRole('cell', { name: 'Haus A' })).toBeInTheDocument();
    expect(screen.queryByRole('cell', { name: 'Haus B' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Immobilie'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'finalized' } });
    expect(screen.queryByRole('cell', { name: 'Haus A' })).not.toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Haus B' })).toBeInTheDocument();
  });

  it('opens a personal letter directly from the overview of individual statements', async () => {
    render(page('/statements?filter=statements'));
    fireEvent.click(await screen.findByRole('button', { name: 'Anschreiben & PDF' }));
    expect(screen.getByRole('dialog', { name: 'Persönliches Schreiben' })).toHaveTextContent('stmt1');
  });

  it('preserves all source and VAT fields when changing an amount in its fixed period', async () => {
    render(page()); await open();
    const table = screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' });
    fireEvent.click(within(table).getByLabelText('ui.buttons.edit'));
    const form = screen.getByRole('dialog', { name: 'Kostenposition bearbeiten' });
    expect(within(form).queryByLabelText('pages.statements.formPeriod')).not.toBeInTheDocument();
    expect(within(form).queryByRole('option', { name: /Fläche Haus B/ })).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText(/pages.statements.formAmount/), { target: { value: '150.25' } });
    await act(async () => { fireEvent.submit(within(form).getByRole('button', { name: 'ui.buttons.save' }).closest('form')); });
    expect(api.put).toHaveBeenCalledWith('/billing/cost-items/cost', expect.objectContaining({ billing_period_id: 'bp1', amount: 150.25,
      cost_category: 'water', source_document_id: 'doc1', service_contract_invoice_id: 'source-bill', vat_rate: 7, net_amount: 115.37, gross_amount: 123.45 }));
    expect(api.get.mock.calls.filter(([path]) => path === '/billing/periods/bp1/preflight')).toHaveLength(2);
  });

  it('offers a named cost template without silently inventing its amount or distribution', async () => {
    render(page()); await open();
    fireEvent.click(screen.getByRole('button', { name: '+ Grundsteuer' }));
    const form = screen.getByRole('dialog', { name: 'Kostenposition hinzufügen' });
    expect(within(form).getByLabelText(/pages.statements.formCostType/)).toHaveValue('Grundsteuer');
    expect(within(form).getByLabelText(/pages.statements.formAmount/)).toHaveValue(null);
    expect(within(form).getByLabelText(/pages.statements.formAllocationKey/)).toHaveValue('');
  });

  it('deletes a source cost only after the named confirmation and refreshes the preflight', async () => {
    render(page()); await open();
    const region = screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' });
    await act(async () => { fireEvent.click(within(region).getByLabelText('ui.buttons.delete')); });
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Wasser'), { action: 'delete' });
    expect(api.del).toHaveBeenCalledWith('/billing/cost-items/cost');
    expect(within(region).queryByRole('cell', { name: 'Wasser' })).not.toBeInTheDocument();
  });

  it('shows the calculation and routes editing back to the shared cost sources', async () => {
    render(page()); await open();
    fireEvent.click(screen.getByRole('button', { name: 'Aufschlüsselung öffnen' }));
    const detail = screen.getByRole('dialog', { name: 'Aufschlüsselung der Abrechnung' });
    expect(within(detail).getByText('Wasser')).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole('button', { name: 'Kostenpositionen bearbeiten' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' })).toHaveFocus();
  });

  it('keeps an issued period read-only and records delivery with an explicit channel', async () => {
    data['/billing/statements'][0] = { ...data['/billing/statements'][0], billing_period_id: 'bp2', status: 'finalized' };
    render(page()); await open('Haus B');
    const costs = screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' });
    expect(within(costs).queryByLabelText('ui.buttons.edit')).not.toBeInTheDocument();
    expect(screen.queryByText('Häufige Kostenarten hinzufügen')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'pages.statements.markDelivered' }));
    const form = screen.getByRole('dialog', { name: 'Bereits erfolgte Zustellung vermerken' });
    expect(within(form).getByText(/Ein Versand wird hierdurch nicht ausgelöst/)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not replace a newer preflight with a late response from the previous period', async () => {
    let finishFirst;
    api.get.mockImplementation(path => path === '/billing/periods/bp1/preflight' ? new Promise(resolve => { finishFirst = resolve; })
      : Promise.resolve(path.endsWith('/preflight') ? { has_blockers: true, blockers: [{ code: 'NEW', message: 'Neue Prüfung B' }], warnings: [], metrics: {} } : []));
    render(page()); await open();
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    await open('Haus B'); await screen.findByText('Neue Prüfung B');
    await act(async () => { finishFirst({ has_blockers: false, blockers: [], warnings: [], metrics: {} }); });
    expect(screen.getByText('Neue Prüfung B')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Abrechnung B' })).toBeInTheDocument();
  });

  it('shows shared costs and individual statements below a direct period focus link', async () => {
    render(page('/statements?focus_id=bp1'));
    await screen.findByRole('heading', { name: 'Abrechnung A' });
    expect(within(screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' })).getByRole('cell', { name: 'Wasser' })).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Einzelabrechnungen als Verteilungsquelle' })).getByRole('cell', { name: 'Musterpartei' })).toBeInTheDocument();
  });

  it.each([
    ['readonly', [], false, false],
    ['cost-editor', ['/billing/cost-items'], true, false],
    ['period-editor', ['/billing/periods'], false, true],
  ])('respects separate cost and period permissions for %s while row opening remains readable', async (role, write, costWrite, periodWrite) => {
    auth.current = { user: { id: role, role }, write };
    render(page()); await open();
    const costs = screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' });
    expect(Boolean(within(costs).queryByLabelText('ui.buttons.edit'))).toBe(costWrite);
    expect(Boolean(within(costs).queryByLabelText('ui.buttons.delete'))).toBe(costWrite);
    expect(Boolean(screen.queryByRole('button', { name: 'Zeitraum bearbeiten' }))).toBe(periodWrite);
    fireEvent.click(screen.getByRole('button', { name: 'Aufschlüsselung öffnen' }));
    const breakdown = screen.getByRole('dialog', { name: 'Aufschlüsselung der Abrechnung' });
    expect(Boolean(within(breakdown).queryByRole('button', { name: 'Kostenpositionen bearbeiten' }))).toBe(costWrite);
    fireEvent.click(within(breakdown).getByLabelText('Schließen'));
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    expect(screen.queryByRole('button', { name: 'Vorjahr kopieren' })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled(); expect(api.del).not.toHaveBeenCalled();
  });

  it('keeps period B selected when a review response for period A arrives late', async () => {
    let finish;
    api.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    api.get.mockImplementation(async path => path.endsWith('/bp2/preflight')
      ? { has_blockers: true, blockers: [{ code: 'B', message: 'Prüfung gehört zu B' }], warnings: [], metrics: {} }
      : path.endsWith('/preflight') ? { has_blockers: false, blockers: [], warnings: [], metrics: {} } : []);
    render(page()); await open();
    fireEvent.click(screen.getByRole('button', { name: 'pages.statements.submitReview' }));
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    await open('Haus B'); await screen.findByText('Prüfung gehört zu B');
    await act(async () => { data['/billing/periods'][0] = { ...first, status: 'review' }; finish(data['/billing/periods'][0]); });
    expect(screen.getByRole('heading', { name: 'Abrechnung B' })).toBeInTheDocument();
    expect(screen.getByText('Prüfung gehört zu B')).toBeInTheDocument();
  });

  it('does not clear period B preflight after an earlier source deletion finishes for period A', async () => {
    let finish;
    api.del.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    api.get.mockImplementation(async path => path.endsWith('/bp2/preflight')
      ? { has_blockers: true, blockers: [{ code: 'B', message: 'Prüfung gehört zu B' }], warnings: [], metrics: {} }
      : path.endsWith('/preflight') ? { has_blockers: false, blockers: [], warnings: [], metrics: {} } : []);
    render(page()); await open();
    fireEvent.click(within(screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' })).getByLabelText('ui.buttons.delete'));
    await waitFor(() => expect(api.del).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    await open('Haus B'); await screen.findByText('Prüfung gehört zu B');
    await act(async () => { data['/billing/cost-items'] = []; finish(); });
    expect(screen.getByRole('heading', { name: 'Abrechnung B' })).toBeInTheDocument();
    expect(screen.getByText('Prüfung gehört zu B')).toBeInTheDocument();
    expect(api.get.mock.calls.filter(([path]) => path === '/billing/periods/bp1/preflight')).toHaveLength(1);
  });

  it('edits mutable period metadata through the existing form while keeping its property and workflow fixed', async () => {
    api.put.mockImplementation(async (_path, body) => {
      const saved = { ...first, ...body }; data['/billing/periods'][0] = saved; return saved;
    });
    render(page()); await open();
    fireEvent.click(screen.getByRole('button', { name: 'Zeitraum bearbeiten' }));
    const form = screen.getByRole('dialog', { name: 'Abrechnung bearbeiten' });
    expect(within(form).queryByLabelText(/pages.statements.formProperty/)).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText(/pages.statements.formLabel/), { target: { value: 'Geprüfter Zeitraum' } });
    fireEvent.change(within(form).getByLabelText(/pages.statements.formEnd/), { target: { value: '2024-12-31' } });
    fireEvent.submit(form.querySelector('form'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Das Ende darf nicht vor dem Beginn liegen.');
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.change(within(form).getByLabelText(/pages.statements.formEnd/), { target: { value: '2025-12-31' } });
    await act(async () => { fireEvent.submit(form.querySelector('form')); });
    expect(api.put).toHaveBeenCalledWith('/billing/periods/bp1', expect.objectContaining({ property_id: 'p1', label: 'Geprüfter Zeitraum' }));
    expect(api.put.mock.calls[0][1]).not.toHaveProperty('status');
    expect(screen.getByRole('heading', { name: 'Geprüfter Zeitraum' })).toBeInTheDocument();
  });

  it('reports a partial year copy persistently without retrying the already created period', async () => {
    data['/billing/cost-items'].push({ ...data['/billing/cost-items'][0], id: 'heat', description: 'Heizung', source_document_id: null, service_contract_invoice_id: null });
    api.post.mockImplementation(async (path, body) => {
      if (path === '/billing/periods') { const period = { ...body, id: 'copy', status: 'draft' }; data[path].push(period); return period; }
      if (body.description === 'Wasser') throw new Error('Schlüssel muss geprüft werden');
      const row = { ...body, id: 'copied-heat' }; data[path].push(row); return row;
    });
    render(page()); await open();
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Vorjahr kopieren' }));
    const form = screen.getByRole('dialog', { name: 'Abrechnung kopieren (neuer Zeitraum)' });
    fireEvent.change(within(form).getByLabelText(/pages.statements.formStart/), { target: { value: '2027-01-01' } });
    fireEvent.change(within(form).getByLabelText(/pages.statements.formEnd/), { target: { value: '2027-12-31' } });
    await act(async () => { fireEvent.submit(form.querySelector('form')); });
    const result = screen.getByRole('alert', { name: 'Ergebnis der Abrechnungskopie' });
    expect(result).toHaveTextContent('1 von 2 Kostenpositionen');
    expect(result).toHaveTextContent('Wasser: Schlüssel muss geprüft werden');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.post.mock.calls.filter(([path]) => path === '/billing/periods')).toHaveLength(1);
    fireEvent.click(within(result).getByRole('button', { name: 'Neuen Zeitraum prüfen' }));
    expect(screen.getByRole('heading', { name: 'Abrechnung A (Kopie)' })).toBeInTheDocument();
  });

  it('uses frozen advance facts for an issued breakdown and opens it from a readable statement row', async () => {
    data['/billing/periods'][0] = { ...first, status: 'finalized' };
    data['/billing/statements'][0] = { ...data['/billing/statements'][0], status: 'finalized',
      final_document: { title: 'Gespeicherte Fassung', rows: [['Ursprüngliche Kosten', '600,00 €', 'Verteilt', '600,00 €']],
        facts: [], totals: [['Vorauszahlungen', '600,00 €']], advances: [['01.01.2025 – 31.12.2025', '50,00 € / Monat', '600,00 €']] },
      advance_sections: [{ start: '2099-01-01', end: '2099-12-31', monthly: 9999, amount: 9999 }] };
    auth.current = { user: { id: 'reader', role: 'readonly' }, write: [] };
    render(page('/statements?filter=statements'));
    fireEvent.click((await screen.findByRole('cell', { name: 'Wohnung A' })).closest('tr'));
    const breakdown = screen.getByRole('dialog', { name: 'Aufschlüsselung der Abrechnung' });
    expect(within(breakdown).getByText('Gespeicherte Fassung')).toBeInTheDocument();
    expect(within(breakdown).getByText('50,00 € / Monat')).toBeInTheDocument();
    expect(within(breakdown).queryByText(/2099|9\.999/)).not.toBeInTheDocument();
    expect(within(breakdown).queryByRole('button', { name: 'Kostenpositionen bearbeiten' })).not.toBeInTheDocument();
  });

  it('routes OCR drafts into the shared cost editor without an invented amount or foreign property key', async () => {
    api.upload.mockResolvedValue({ file_url: '/uploads/ocr.pdf' });
    api.post.mockImplementation(async (path, body) => path.startsWith('/billing/cost-items/import-ocr')
      ? { success: true, draft: { billing_period_id: 'bp1', description: 'OCR-Beleg', amount: null, allocation_key_id: 'key2',
        source_document_id: 'ocr-doc', vat_rate: 19, net_amount: 84.03, gross_amount: 100 }, ocr_fields: {} }
      : { ...body, id: 'ocr-cost' });
    render(page()); await open();
    fireEvent.change(screen.getByLabelText('pages.statements.ocrImport'), { target: { files: [new File(['fixture'], 'beleg.pdf', { type: 'application/pdf' })] } });
    const preview = await screen.findByRole('dialog', { name: 'Erkannten Text prüfen' });
    fireEvent.click(within(preview).getByRole('button', { name: 'Kostenposition prüfen und ergänzen' }));
    const editor = screen.getByRole('dialog', { name: 'Kostenposition hinzufügen' });
    expect(within(editor).getByLabelText(/pages.statements.formAmount/)).toHaveValue(null);
    expect(within(editor).getByLabelText(/pages.statements.formAllocationKey/)).toHaveValue('');
    expect(api.post.mock.calls.filter(([path]) => path === '/billing/cost-items')).toHaveLength(0);
    fireEvent.change(within(editor).getByLabelText(/pages.statements.formAmount/), { target: { value: '100' } });
    fireEvent.change(within(editor).getByLabelText(/pages.statements.formAllocationKey/), { target: { value: 'key1' } });
    await act(async () => { fireEvent.submit(editor.querySelector('form')); });
    expect(api.post).toHaveBeenCalledWith('/billing/cost-items', expect.objectContaining({ billing_period_id: 'bp1', allocation_key_id: 'key1',
      amount: 100, source_document_id: 'ocr-doc', vat_rate: 19, net_amount: 84.03, gross_amount: 100 }));
  });

  it('keeps manual revision selection in the URL across refresh and restores its list context without a foreign notification receipt', async () => {
    const revision = { ...first, id: 'revision', label: 'Korrektur B', revision: 2, corrects_period_id: first.id };
    data['/billing/periods'] = [first, revision];
    data['/billing/cost-items'].push({ ...data['/billing/cost-items'][0], id: 'revision-cost', billing_period_id: revision.id });
    const normal = api.get.getMockImplementation();
    api.get.mockImplementation(async path => path === '/notifications/n1/source'
      ? { notice: { revision: 1 }, source: { entity_id: first.id, kind: 'billing_period', revision: 'source-revision',
        href: '/statements?focus_id=bp1', values: first } }
      : normal(path));
    function Routing() {
      const navigate = useNavigate();
      return <><button onClick={() => navigate(-1)}>Browser zurück</button><Statements /></>;
    }
    window.history.replaceState({}, '', '/statements?focus_id=bp1&suche=Haus+A&year=2025&notice_id=n1');
    render(<BrowserRouter><Routing /></BrowserRouter>);
    await screen.findByRole('heading', { name: 'Abrechnung A' });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/n1/receipt', expect.objectContaining({ source_id: 'bp1' })));
    fireEvent.click(screen.getByRole('button', { name: 'pages.statements.show' }));
    await screen.findByRole('heading', { name: 'Korrektur B' });
    expect(new URLSearchParams(window.location.search).get('period_id')).toBe('revision');
    expect(new URLSearchParams(window.location.search).has('focus_id')).toBe(false);
    expect(new URLSearchParams(window.location.search).has('notice_id')).toBe(false);
    fireEvent.click(within(screen.getByRole('region', { name: 'Kostenquellen dieser Abrechnung' })).getByLabelText('ui.buttons.delete'));
    await waitFor(() => expect(api.del).toHaveBeenCalledWith('/billing/cost-items/revision-cost'));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/billing/periods/revision/preflight'));
    expect(screen.getByRole('heading', { name: 'Korrektur B' })).toBeInTheDocument();
    const receipts = api.post.mock.calls.filter(([path]) => path.includes('/receipt'));
    expect(receipts.length).toBeGreaterThan(0);
    expect(receipts.every(([, body]) => body.source_id === 'bp1')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByRole('heading', { name: 'Abrechnung A' });
    fireEvent.click(screen.getByRole('button', { name: /pages.statements.back/ }));
    await screen.findByLabelText('Jahr');
    const returned = new URLSearchParams(window.location.search);
    expect(returned.get('suche')).toBe('Haus A'); expect(returned.get('year')).toBe('2025');
    expect(returned.has('period_id')).toBe(false); expect(returned.has('focus_id')).toBe(false);
    expect(returned.has('notice_id')).toBe(false); expect(returned.has('source_id')).toBe(false);
  });
});
