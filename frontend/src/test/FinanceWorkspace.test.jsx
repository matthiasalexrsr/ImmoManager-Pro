import { beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import FinanceReports from '../features/FinanceReports';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'reports-owner' } }), useCanWrite: () => true }));
const props = [{ id: 'p1', name: 'Haus', portfolio_id: 'a' }, { id: 'p2', name: 'Haus', portfolio_id: 'b' }];
const units = [{ id: 'u1', property_id: 'p1', label: 'Wohnung A' }, { id: 'u2', property_id: 'p2', label: 'Wohnung B' }];
const result = (extra = {}) => ({ basis: 'cash-v2', definition_hash: 'definition-1', result_hash: 'result-1', currency: 'EUR',
  filters: { property_id: 'p1', unit_id: 'u1', date_from: '2026-01-01', date_to: '2026-01-31' },
  monthly: [{ month: '2026-01', income: '125.00', expense: '25.00', net: '100.00' }],
  totals: { income: '125.00', expense: '25.00', net: '100.00' }, warnings: [], sources: [], ...extra });
function Location() {
  const navigate = useNavigate();
  return <><output data-testid="location">{useLocation().search}</output><button onClick={() => navigate('/reports')}>Auswertungen ohne Objektauswahl</button></>;
}
function mount(path = '/reports') { return render(<MemoryRouter initialEntries={[path]}><FinanceReports standalone /><Location /></MemoryRouter>); }
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  api.captureSession.mockReturnValue(() => {});
  api.list.mockImplementation(path => Promise.resolve(path === '/properties' ? props : path === '/units' ? units : path === '/portfolios' ? [{ id: 'a', name: 'Bestand A' }, { id: 'b', name: 'Bestand B' }] : []));
  api.get.mockResolvedValue(result());
});
async function ready() { await waitFor(() => expect(screen.getByRole('button', { name: 'Berechnen' })).toBeEnabled()); }
async function calculate() { fireEvent.click(screen.getByRole('button', { name: 'Berechnen' })); return screen.findByRole('region', { name: 'Berechneter Bericht' }); }

it('opens exact record context and retains it in calculation, exports and source navigation', async () => {
  mount('/reports?kind=cash-v2&property_id=p1&unit_id=u1&as_of=2026-01-31'); await ready();
  expect(screen.getByLabelText('Immobilie')).toHaveValue('p1'); expect(screen.getByLabelText('Einheit')).toHaveValue('u1');
  expect(screen.getByRole('button', { name: 'CSV herunterladen' })).toBeDisabled();
  await calculate();
  const definition = JSON.parse(new URLSearchParams(api.get.mock.calls[0][0].split('?')[1]).get('definition'));
  expect(definition).toMatchObject({ kind: 'cash-v2', property_id: 'p1', unit_id: 'u1', as_of: '2026-01-31' });
  const income = screen.getAllByRole('link', { name: 'Buchungen prüfen →' })[0];
  expect(new URLSearchParams(income.getAttribute('href').split('?')[1]).get('unit_id')).toBe('u1');
  api.getBlob.mockRejectedValue(new Error('Quelle wurde geändert'));
  fireEvent.click(screen.getByRole('button', { name: 'CSV herunterladen' }));
  await screen.findByRole('alert');
  expect(api.getBlob.mock.calls[0][0]).toContain('expected_result_hash=result-1');
  fireEvent.change(screen.getByLabelText('Immobilie'), { target: { value: 'p2' } });
  expect(screen.getByLabelText('Einheit')).toHaveValue('');
  expect(screen.getByRole('button', { name: 'CSV herunterladen' })).toBeDisabled();
  expect(new URLSearchParams(screen.getByTestId('location').textContent).get('property_id')).toBe('p2');
});

it('restricts dependent selectors and clears a unit and scenario vacancy when changing portfolio', async () => {
  const definition = { version: 2, kind: 'liquidity-v2', as_of: '2026-01-01', months: 3, property_id: 'p1', unit_id: 'u1',
    rent_payment_day: 3, rent_collection_percent: '100', arrears_collection_percent: '0', vacant_unit_ids: ['u1'], planned_flows: [] };
  const base = api.list.getMockImplementation();
  api.list.mockImplementation(path => path === '/reports/v2/saved' ? Promise.resolve([{ id: 's1', name: 'Leerstand A', definition }]) : base(path));
  mount(); await ready();
  fireEvent.change(screen.getByLabelText('Gespeicherten Bericht öffnen'), { target: { value: 's1' } });
  expect(screen.getByLabelText('Einheit')).toHaveValue('u1');
  fireEvent.change(screen.getByLabelText('Portfolio'), { target: { value: 'b' } });
  expect(screen.getByLabelText('Immobilie')).toHaveValue(''); expect(screen.getByLabelText('Einheit')).toHaveValue('');
  expect(within(screen.getByLabelText('Einheit')).queryByRole('option', { name: /Wohnung A/ })).not.toBeInTheDocument();
  expect(screen.getByText('Im Szenario leerstehende Einheiten (0)')).toBeInTheDocument();
});

it('shows every term of the period result and can find sources after position 100', async () => {
  const sources = Array.from({ length: 101 }, (_, index) => ({ identity: `invoice:${index}`, contribution: index === 100 ? 'other_income' : 'costs', month: index === 100 ? '2026-02' : '2026-01', amount: '0.01', basis: `Quelle ${index}`, url: `/invoice-review/${index}` }));
  api.get.mockResolvedValue(result({ basis: 'performance-period-v2', sources, totals: { rent_due: '100.00', other_income: '20.00', costs: '5.00', result: '115.00' },
    monthly: [{ month: '2026-01', rent_due: '100.00', other_income: '20.00', costs: '5.00', result: '115.00' }, { month: '2026-02', rent_due: '0.00', other_income: '0.00', costs: '0.00', result: '0.00' }] }));
  mount('/reports?kind=performance-period-v2'); await ready(); await calculate();
  expect(screen.getByRole('columnheader', { name: 'Sonstige Einnahmen' })).toBeInTheDocument();
  const table = screen.getByRole('table', { name: 'Monatsverlauf' });
  expect(within(table).getByRole('row', { name: /2026-01/ })).toHaveTextContent('20,00');
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Quellen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Quellen' }));
  expect(screen.getByRole('link', { name: 'Quelle 100' })).toHaveAttribute('href', '/invoice-review/100');
  fireEvent.change(screen.getByLabelText('Quellen durchsuchen'), { target: { value: 'Quelle 100' } });
  expect(screen.getByText('1–1 von 1 Quellen')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Quellen für 2026-01 anzeigen' }));
  expect(screen.getByText('Keine Quellen entsprechen der Auswahl.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Quellen durchsuchen'), { target: { value: '' } });
  const metric = screen.getByText('Sonstige Einnahmen', { selector: '.finance-result-metric > span' }).closest('.finance-result-metric');
  fireEvent.click(within(metric).getByRole('button', { name: 'Quellen prüfen →' }));
  expect(screen.getByLabelText('Quellenart')).toHaveValue('other_income');
  expect(screen.getByText('1–1 von 1 Quellen')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Quelle 100' })).toBeInTheDocument();
});

it('applies complete period presets together and uses whole months for performance reports', async () => {
  mount('/reports?kind=cash-v2&as_of=2026-03-15'); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Letzte 12 Monate' }));
  expect(screen.getByLabelText('Zeitraum von')).toHaveValue('2025-04-01');
  expect(screen.getByLabelText('Zeitraum bis')).toHaveValue('2026-03-15');
  fireEvent.change(screen.getByLabelText('Berichtsart'), { target: { value: 'performance-period-v2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Letzte 12 Monate' }));
  expect(screen.getByLabelText('Zeitraum bis')).toHaveValue('2026-03-31');
  fireEvent.click(screen.getByRole('button', { name: 'Vorjahr' }));
  expect(screen.getByLabelText('Zeitraum von')).toHaveValue('2025-01-01');
  expect(screen.getByLabelText('Zeitraum bis')).toHaveValue('2025-12-31');
  fireEvent.click(screen.getByRole('button', { name: 'Zeitraum zurücksetzen' }));
  expect(screen.getByLabelText('Zeitraum von')).toHaveValue('');
});

it('starts a new planned payment after the cutoff, including month end', async () => {
  mount('/reports?kind=liquidity-v2&as_of=2026-01-31'); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Zahlung ergänzen' }));
  expect(screen.getByLabelText('Datum 1')).toHaveValue('2026-02-01');
  fireEvent.change(screen.getByLabelText('Datum 1'), { target: { value: '2026-01-31' } });
  expect(screen.getByText(/liegt am oder vor dem Stichtag/)).toBeInTheDocument();
});

it('keeps unavailable record IDs visible and lets the user clear them without losing the period', async () => {
  mount('/reports?kind=cash-v2&property_id=removed&unit_id=missing&date_from=2026-01-01'); await ready();
  expect(screen.getByLabelText('Immobilie')).toHaveValue('removed');
  expect(screen.getByRole('option', { name: 'Nicht verfügbare Immobilie (removed)' })).toBeInTheDocument();
  expect(screen.getByLabelText('Einheit')).toHaveValue('missing');
  fireEvent.click(screen.getByRole('button', { name: 'Objektauswahl zurücksetzen' }));
  expect(screen.getByLabelText('Immobilie')).toHaveValue('');
  expect(screen.getByLabelText('Einheit')).toHaveValue('');
  expect(screen.getByLabelText('Zeitraum von')).toHaveValue('2026-01-01');
});

it('recovers failed reference loading and rejects a malformed report instead of showing zero values', async () => {
  api.list.mockRejectedValueOnce(new Error('Objektauswahl nicht erreichbar'));
  mount(); expect(await screen.findByRole('alert')).toHaveTextContent('Objektauswahl nicht erreichbar');
  expect(screen.getByRole('button', { name: 'Berechnen' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Auswahldaten erneut laden' })); await ready();
  api.get.mockResolvedValue({ monthly: [{ month: '2026-01', income: null }] });
  fireEvent.click(screen.getByRole('button', { name: 'Berechnen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Berichtsantwort ist unvollständig');
  expect(screen.queryByRole('region', { name: 'Berechneter Bericht' })).not.toBeInTheDocument();
});

it('does not apply an old successful response after closing and reopening the report editor', async () => {
  let resolve;
  api.get.mockImplementation(() => new Promise(done => { resolve = done; }));
  render(<MemoryRouter><FinanceReports /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'Bericht erstellen oder öffnen' })); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Berechnen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Bericht erstellen oder öffnen' })); await ready();
  await act(async () => resolve(result()));
  expect(screen.queryByRole('region', { name: 'Berechneter Bericht' })).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each(['success', 'failure'])('ignores a late %s after same-route navigation and allows a fresh calculation', async outcome => {
  let resolve, reject;
  api.get.mockImplementationOnce(() => new Promise((done, fail) => { resolve = done; reject = fail; }));
  mount('/reports?kind=cash-v2&property_id=p1'); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Berechnen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Auswertungen ohne Objektauswahl' }));
  expect(screen.getByLabelText('Immobilie')).toHaveValue('');
  await ready();
  api.get.mockResolvedValue(result({ result_hash: 'all-records', sources: [{ identity: 'new', label: 'Aktuelle Auswahl', amount: '5.00' }] }));
  await calculate();
  await act(async () => outcome === 'success' ? resolve(result({ sources: [{ identity: 'old', label: 'Alte Auswahl', amount: '1.00' }] })) : reject(new Error('Veralteter Fehler')));
  expect(screen.getByText('Aktuelle Auswahl')).toBeInTheDocument();
  expect(screen.queryByText('Alte Auswahl')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('does not download a pending export after navigating to another report context', async () => {
  let resolve;
  api.getBlob.mockImplementation(() => new Promise(done => { resolve = done; }));
  const createObjectURL = vi.fn();
  vi.stubGlobal('URL', class extends URL { static createObjectURL = createObjectURL; });
  try {
    mount('/reports?kind=cash-v2&property_id=p1'); await ready(); await calculate();
    fireEvent.click(screen.getByRole('button', { name: 'PDF herunterladen' }));
    fireEvent.click(screen.getByRole('button', { name: 'Auswertungen ohne Objektauswahl' }));
    await ready();
    await act(async () => resolve(new Blob(['old report'])));
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'PDF herunterladen' })).toBeDisabled();
  } finally { vi.unstubAllGlobals(); }
});

it('keeps an uncertain save across navigation and confirms it with the original repeat key', async () => {
  let resolve;
  api.post.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  mount('/reports?kind=cash-v2&property_id=p1'); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Als neue Fassung speichern' }));
  const request = api.post.mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Auswertungen ohne Objektauswahl' }));
  await act(async () => resolve({ id: 'saved-1' }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('workspace:reports-owner:finance-command:report-definition')).request).toEqual(request);
  api.post.mockResolvedValue({ id: 'saved-1' });
  fireEvent.click(screen.getByRole('button', { name: 'Speicherung prüfen und fortsetzen' }));
  await screen.findByText('Definition gespeichert. Beim Öffnen gelten die aktuellen Rechte und Quellen.');
  expect(api.post.mock.calls[1][1]).toEqual(request);
  expect(localStorage.getItem('workspace:reports-owner:finance-command:report-definition')).toBeNull();
});
