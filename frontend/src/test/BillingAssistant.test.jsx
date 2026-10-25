import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import BillingAssistant from '../pages/BillingAssistant';
import { keyFor, segmentText } from '../features/billingAssistant/billingAssistantApi';

vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => ({ user: { full_name: 'Linda Reiser' } }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }) }));
afterEach(cleanup);

const view = {
  property: { id: 'p', name: 'Gohliser Straße 17', units: 3, residential: 2, commercial: 0, parking: 1, area_sqm: 100, meters: { cold_water: 2 } },
  periods: [{ id: 'bp', label: 'Nebenkosten 2025', start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' }],
  period: { id: 'bp', label: 'Nebenkosten 2025', start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' },
  suggested_period: { label: 'Nebenkosten 2026', start_date: '2026-01-01', end_date: '2026-12-31' },
  deadline: { date: '2026-12-31', days_left: 67 },
  occupancy: { units: [{ unit_id: 'u1', label: 'EG', area_sqm: 60, residential: true, rented_days: 334, segments: [
    { kind: 'tenancy', start: '2025-01-01', end: '2025-06-30', days: 181, tenant: 'Anna Alt', persons: 1, advances: 900 },
    { kind: 'vacancy', start: '2025-07-01', end: '2025-07-31', days: 31 },
    { kind: 'tenancy', start: '2025-08-01', end: '2025-12-31', days: 153, tenant: 'Bernd Neu', persons: 1, advances: 750 }] }],
    changes: [], vacancy_days: 31 },
  keys: { present: [{ id: 'area', name: 'Fläche', key_type: 'area_sqm', key_label: 'Wohn-/Nutzfläche', used: true },
    { id: 'persons', name: 'Personen', key_type: 'person_count', key_label: 'Personen', used: false }],
  suggested: [{ key_type: 'consumption', meter_type: 'cold_water', measure_unit: 'm³', name: 'Kaltwasser (Verbrauch)', reason: 'Alle 2 vermieteten Einheiten haben einen Kaltwasserzähler (m³).' }] },
  costs: { items: [{ id: 'c1', description: 'Grundsteuer', amount: 1300, key_name: 'Fläche', is_recoverable: true }], total: 1300,
    previous_period: { id: 'old', label: 'Nebenkosten 2024' },
    previous: [{ description: 'Wasser', amount: 800, category: 'water', allocation_key_id: 'persons', key_name: 'Personen', is_recoverable: true, missing: true }],
    service_contracts: [], catalogue: [{ category: 'garden', label: 'Gartenpflege', key: 'area_sqm' }, { category: 'water', label: 'Wasserversorgung und Entwässerung', key: 'consumption:cold_water' }] },
  readings: { needed: [{ meter_id: 'm1', serial_number: 'WZ 1', meter_label: 'Kaltwasser', unit_label: 'EG', day: '2025-06-30', reason: 'Auszug Anna Alt', present: false }], missing: 1 },
  checks: { blockers: [], warnings: [{ code: 'VACANCY', message: 'Leerstand: den Anteil trägt der Vermieter', context: 'EG: 31 Tage' }], metrics: {} },
  statements: { items: [], outdated: false, total_cost: 0, advances: 0, balance: 0 },
  hints: [{ step: 'keys', level: 'warning', text: 'Wasser kann nach Verbrauch verteilt werden.' }, { step: 'occupancy', level: 'info', text: 'Mieterwechsel im Zeitraum: EG' }],
  steps: [{ key: 'period', done: true }, { key: 'occupancy', done: true }, { key: 'keys', done: false }, { key: 'costs', done: true },
    { key: 'readings', done: false }, { key: 'check', done: true }, { key: 'result', done: false }],
};

const service = () => ({
  properties: vi.fn().mockResolvedValue([{ id: 'p', name: 'Gohliser Straße 17' }]),
  guide: vi.fn().mockResolvedValue(view),
  createPeriod: vi.fn().mockResolvedValue({ id: 'new' }),
  createKey: vi.fn().mockResolvedValue({ id: 'k' }),
  addCost: vi.fn().mockResolvedValue({ id: 'c2' }),
  removeCost: vi.fn().mockResolvedValue(null),
  addReading: vi.fn().mockResolvedValue({ id: 'r' }),
  generate: vi.fn().mockResolvedValue([]),
});
const mount = (search, api) => render(<MemoryRouter initialEntries={[`/statements/assistant${search}`]}>
  <Routes><Route path="/statements/assistant" element={<BillingAssistant service={api} />} /></Routes></MemoryRouter>);

describe('Nebenkosten-Assistent', () => {
  it('wählt den Schlüssel einer Kostenart und beschreibt Nutzungszeiten', () => {
    expect(keyFor('area_sqm', view.keys.present)).toBe('area');
    expect(keyFor('consumption:cold_water', view.keys.present)).toBe('persons');      // without a water key: persons
    expect(segmentText(view.occupancy.units[0].segments[0])).toBe('Anna Alt 01.01.2025–30.06.2025 (181 Tage, 1 Person)');
    expect(segmentText(view.occupancy.units[0].segments[1])).toBe('Leerstand 01.07.2025–31.07.2025 (31 Tage)');
  });

  it('führt durch die Schritte und zeigt die Hinweise des jeweiligen Schritts', async () => {
    const api = service();
    mount('?property_id=p&period_id=bp&step=keys', api);
    await screen.findByRole('heading', { name: '3. Verteilerschlüssel' });
    expect(api.guide).toHaveBeenCalledWith('p', 'bp', expect.anything());
    const hints = screen.getByRole('complementary', { name: 'Hinweise zu dieser Immobilie' });
    expect(within(hints).getByText('Wasser kann nach Verbrauch verteilt werden.')).toBeInTheDocument();
    expect(within(hints).queryByText(/Mieterwechsel/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Anlegen/ }));
    await waitFor(() => expect(api.createKey).toHaveBeenCalledWith({ property_id: 'p', name: 'Kaltwasser (Verbrauch)', key_type: 'consumption',
      meter_type: 'cold_water', measure_unit: 'm³' }));
    fireEvent.click(screen.getByRole('button', { name: 'Weiter: Kosten' }));
    await screen.findByRole('heading', { name: '4. Kosten' });
    expect(screen.getByText('Wasser')).toBeInTheDocument();                         // from the year before
    fireEvent.change(screen.getByLabelText('Kostenart (§ 2 BetrKV)'), { target: { value: 'garden' } });
    expect(screen.getByLabelText('Bezeichnung')).toHaveValue('Gartenpflege');
    fireEvent.change(screen.getByLabelText('Betrag (€)'), { target: { value: '250' } });
    fireEvent.click(screen.getByRole('button', { name: /Hinzufügen/ }));
    await waitFor(() => expect(api.addCost).toHaveBeenCalledWith({ billing_period_id: 'bp', description: 'Gartenpflege', amount: 250,
      allocation_key_id: 'area', is_recoverable: true, cost_category: 'garden', consumption_share: null }));
  });

  it('speichert fehlende Zählerstände und erzeugt die Einzelabrechnungen', async () => {
    const api = service();
    mount('?property_id=p&period_id=bp&step=readings', api);
    await screen.findByRole('heading', { name: '5. Zählerstände' });
    fireEvent.change(screen.getByLabelText('Stand EG am 30.06.2025'), { target: { value: '512.4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.addReading).toHaveBeenCalledWith('m1', { reading_date: '2025-06-30', value: 512.4 }));
    fireEvent.click(within(screen.getByRole('list', { name: 'Schritte' })).getByRole('button', { name: /Prüfen/ }));
    await screen.findByText('Leerstand: den Anteil trägt der Vermieter');
    expect(screen.getByText(/Keine Fehler/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weiter: Abrechnen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Einzelabrechnungen erzeugen' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('bp'));
  });

  it('legt eine neue Abrechnung mit dem vorgeschlagenen Zeitraum an', async () => {
    const api = service();
    api.guide.mockResolvedValue({ ...view, period: null, checks: null });
    mount('?property_id=p', api);
    await screen.findByRole('heading', { name: '1. Objekt & Zeitraum' });
    expect(within(screen.getByRole('list', { name: 'Schritte' })).getByRole('button', { name: /Nutzer & Zeiträume/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Weiter: Nutzer & Zeiträume' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Abrechnung anlegen' }));
    await waitFor(() => expect(api.createPeriod).toHaveBeenCalledWith({ property_id: 'p', label: 'Nebenkosten 2026',
      start_date: '2026-01-01', end_date: '2026-12-31', status: 'draft' }));
  });
});
