import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import Properties from '../pages/Properties';
import PropertyDetail from '../pages/PropertyDetail';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), confirm: vi.fn(),
  invalidateRelated: vi.fn(), readonly: false, locale: 'de-DE', t: null, cache: {},
}));
vi.mock('../api', () => ({ api: { get: mocks.get, getAll: mocks.getAll, post: mocks.post, put: mocks.put, del: mocks.del } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t, locale: mocks.locale }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: mocks.readonly ? 'readonly' : 'eigentuemer', isReadonly: mocks.readonly }) }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: mocks.invalidateRelated }),
  useEntities: key => mocks.cache[key],
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));

const dictionaries = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const props = [
  { id: 'p1', name: 'Villa Lindenhof', address_line: 'Schillerstraße 12', postal_code: '80336', city: 'München', portfolio_id: 'portfolio-1', property_type: 'residential', status: 'active', purchase_price: 0 },
  { id: 'p2', name: 'Stadthaus am Park', address_line: 'Parkallee 4', postal_code: '70173', city: 'Stuttgart', portfolio_id: 'portfolio-2', property_type: 'mixed', status: 'inactive' },
];
const units = [
  { id: 'u1', property_id: 'p1', label: 'Dachgeschoss', status: 'vacant', cold_rent: 1234.56, area_sqm: 80, service_charge_advance: 120, heating_advance: 60 },
  ...Array.from({ length: 9 }, (_, index) => ({ id: `park-${index}`, property_id: 'p2', label: `Wohnung ${index}`, status: index ? 'occupied' : 'rented', cold_rent: 850, area_sqm: 45, service_charge_advance: 90, heating_advance: 40 })),
];
let records, failedPaths;
function translate(key, params = {}) {
  let text = key.split('.').reduce((value, part) => value?.[part], dictionaries[mocks.locale]) || key;
  for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{{${name}}}`, value);
  return text;
}
function renderList() { return render(<MemoryRouter><Properties /></MemoryRouter>); }
function renderDetail(path = '/properties/p1', extra = null) {
  return render(<MemoryRouter initialEntries={[path]}>{extra}<Routes><Route path="/properties/:id" element={<PropertyDetail />} /></Routes></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.locale = 'de-DE';
  mocks.t = translate;
  mocks.readonly = false;
  records = props.map(prop => ({ ...prop }));
  failedPaths = new Set();
  mocks.cache = {
    portfolios: { items: [{ id: 'portfolio-1', name: 'Privater Bestand' }, { id: 'portfolio-2', name: 'Süddeutschland' }], loading: false, error: null, reload: vi.fn() },
    units: { items: units, loading: false, error: null, reload: vi.fn() },
    maintenance: { items: [{ id: 'm1', property_id: 'p1', title: 'Dach prüfen', status: 'open' }], loading: false, error: null, reload: vi.fn() },
  };
  mocks.get.mockImplementation(async path => {
    if (failedPaths.has(path)) throw new Error('Quelle vorübergehend nicht erreichbar');
    if (path === '/properties') return records;
    if (path.startsWith('/properties/')) return records.find(prop => prop.id === path.split('/').at(-1));
    if (path.startsWith('/units?')) return units.filter(unit => unit.property_id === path.split('=').at(-1));
    if (path.startsWith('/maintenance?')) return mocks.cache.maintenance.items.filter(item => item.property_id === path.split('=').at(-1));
    if (path.startsWith('/contracts?')) return [{ id: 'contract-1', contract_number: 'MV-2026-01', status: 'active', start_date: '2026-01-01', end_date: null }];
    return [];
  });
  mocks.confirm.mockResolvedValue(true);
  mocks.getAll.mockImplementation((path, options) => mocks.get(path, options));
  mocks.post.mockResolvedValue({ id: 'new' });
  mocks.put.mockResolvedValue({ id: 'p1' });
  mocks.del.mockResolvedValue(null);
});

describe('Property inventory', () => {
  it('requests the complete inventory and keeps properties beyond the default page visible', async () => {
    records = [...records, ...Array.from({ length: 100 }, (_, index) => ({ ...props[0], id: `extra-${index}`, name: `Haus ${index}` }))];
    renderList();
    await screen.findByText('Haus 99');
    expect(mocks.getAll).toHaveBeenCalledWith('/properties', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(document.querySelectorAll('article')).toHaveLength(102);
    const summary = screen.getByRole('region', { name: 'Bestand im Überblick' });
    expect(within(summary).getByText('102')).toBeVisible();
  }, 15_000);

  it('shows address identity and occupancy weighted by units, including rented status', async () => {
    renderList();
    const link = await screen.findByRole('link', { name: 'Villa Lindenhof' });
    expect(link).toHaveAttribute('href', '/properties/p1');
    expect(screen.getByText('Schillerstraße 12, 80336 München')).toBeVisible();
    const summary = screen.getByRole('region', { name: 'Bestand im Überblick' });
    expect(within(summary).getByText('90%')).toBeVisible();
    expect(within(summary).getByText('9 von 10 Einheiten belegt')).toBeVisible();
    expect(screen.getByText(/Mietwerte aus aktuellen Einheiten-Stammdaten/)).toBeVisible();
  });

  it('searches addresses, combines portfolio filters and can reset an empty result', async () => {
    renderList();
    await screen.findByRole('link', { name: 'Villa Lindenhof' });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Immobilien durchsuchen' }), { target: { value: 'Parkallee' } });
    expect(screen.queryByRole('link', { name: 'Villa Lindenhof' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Stadthaus am Park' })).toBeVisible();
    fireEvent.change(screen.getByRole('combobox', { name: 'Portfolio' }), { target: { value: 'portfolio-1' } });
    expect(screen.getByRole('heading', { name: 'Keine passenden Immobilien' })).toBeVisible();
    fireEvent.click(screen.getAllByRole('button', { name: 'Filter zurücksetzen' })[0]);
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });

  it('counts only explicit vacancies and preserves all properties in table view', async () => {
    mocks.cache.units.items = units.map(unit => ({ ...unit, status: unit.id === 'u1' ? 'reserved' : unit.status }));
    renderList();
    await screen.findByRole('link', { name: 'Villa Lindenhof' });
    fireEvent.click(screen.getByRole('button', { name: 'Mit freien Einheiten' }));
    expect(screen.getByRole('heading', { name: 'Keine passenden Immobilien' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Alle', exact: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Tabellenansicht' }));
    expect(screen.getByRole('table')).toBeVisible();
    expect(screen.getByRole('link', { name: /Villa Lindenhof/ })).toHaveAttribute('href', '/properties/p1');
    expect(screen.getByRole('button', { name: 'CSV' })).toBeVisible();
  });

  it('renders a real property load error rather than empty inventory and retries', async () => {
    failedPaths.add('/properties');
    renderList();
    expect(await screen.findByRole('alert')).toHaveTextContent('Immobilien konnten nicht geladen werden');
    expect(screen.queryByText('Ihr Bestand beginnt hier')).not.toBeInTheDocument();
    failedPaths.clear();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('link', { name: 'Villa Lindenhof' })).toBeVisible();
  });

  it('keeps failed source metrics unknown, exposes retry and disables dependent filtering', async () => {
    mocks.cache.units.error = 'Einheiten offline';
    renderList();
    await screen.findByRole('link', { name: 'Villa Lindenhof' });
    expect(screen.getByRole('alert')).toHaveTextContent('Einheitendaten nicht verfügbar');
    const summary = screen.getByRole('region', { name: 'Bestand im Überblick' });
    expect(within(summary).queryByText('90%')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mit freien Einheiten' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(mocks.cache.units.reload).toHaveBeenCalledOnce();
  });

  it('hides all create, edit and delete actions for a readonly user', async () => {
    mocks.readonly = true;
    renderList();
    await screen.findByRole('link', { name: 'Villa Lindenhof' });
    expect(screen.queryByRole('button', { name: 'Immobilie anlegen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Villa Lindenhof bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Villa Lindenhof löschen' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tabellenansicht' }));
    expect(screen.queryByRole('button', { name: /bearbeiten|löschen/i })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.del).not.toHaveBeenCalled();
  });

  it('preserves edit CRUD and actual zero values in the existing form', async () => {
    renderList();
    fireEvent.click(await screen.findByRole('button', { name: 'Villa Lindenhof bearbeiten' }));
    const dialog = screen.getByRole('dialog');
    const nameLabel = translate('properties.form.general.name');
    fireEvent.change(within(dialog).getByLabelText(nameLabel, { exact: false }), { target: { value: 'Villa neu' } });
    fireEvent.click(within(dialog).getByRole('button', { name: translate('ui.buttons.save') }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/properties/p1', expect.objectContaining({ name: 'Villa neu', purchase_price: 0 })));
    expect(mocks.invalidateRelated).toHaveBeenCalled();
  });

  it('keeps the property visible and reports a refused deletion', async () => {
    mocks.del.mockRejectedValue(new Error('Zahlungsbelege bleiben erhalten'));
    renderList();
    fireEvent.click(await screen.findByRole('button', { name: 'Villa Lindenhof löschen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Zahlungsbelege bleiben erhalten');
    expect(screen.getByRole('link', { name: 'Villa Lindenhof' })).toBeVisible();
    expect(mocks.confirm).toHaveBeenCalledOnce();
  });

  it('provides a distinct first-use state and prevents creating without a portfolio', async () => {
    records = [];
    mocks.cache.portfolios.items = [];
    renderList();
    expect(await screen.findByRole('heading', { name: 'Ihr Bestand beginnt hier' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Immobilie anlegen' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Portfolios öffnen' })).toHaveAttribute('href', '/portfolios');
  });
});

describe('Property detail', () => {
  it('shows actual property identity, unit links and missing ratios as unknown', async () => {
    renderDetail();
    expect(await screen.findByRole('heading', { name: 'Villa Lindenhof' })).toBeVisible();
    expect(screen.getByRole('link', { name: /Dachgeschoss/ })).toHaveAttribute('href', '/units/u1');
    for (const source of ['units', 'contracts', 'documents', 'maintenance']) expect(mocks.getAll).toHaveBeenCalledWith(`/${source}?property_id=p1`, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText('0 von 1 Einheiten belegt')).toBeVisible();
    fireEvent.click(screen.getByRole('tab', { name: 'Finanzen' }));
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Kaltmiete × 12');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('1.234,56');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('14.814,72');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('0,00');
    expect(screen.getByText(/Die Hochrechnung basiert auf aktuellen Stammdaten/)).toBeVisible();
  });

  it('supports arrow, Home and End navigation with roving tab focus', async () => {
    renderDetail();
    await screen.findByRole('heading', { name: 'Villa Lindenhof' });
    const overview = screen.getByRole('tab', { name: 'Übersicht' });
    overview.focus();
    fireEvent.keyDown(overview, { key: 'ArrowRight' });
    const unitTab = screen.getByRole('tab', { name: 'Einheiten (1)' });
    expect(unitTab).toHaveFocus();
    expect(unitTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', unitTab.id);
    fireEvent.keyDown(unitTab, { key: 'End' });
    const maintenanceTab = screen.getByRole('tab', { name: 'Wartung (1)' });
    expect(maintenanceTab).toHaveFocus();
    fireEvent.keyDown(maintenanceTab, { key: 'Home' });
    expect(overview).toHaveFocus();
  });

  it('separates a failed unit source from a loaded property and does not report zero occupancy', async () => {
    failedPaths.add('/units?property_id=p1');
    renderDetail();
    await screen.findByRole('heading', { name: 'Villa Lindenhof' });
    expect(screen.getByRole('alert')).toHaveTextContent('Einheitendaten nicht verfügbar');
    expect(screen.queryByText('0 von 0 Einheiten belegt')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Einheiten (—)' })).toBeVisible();
    failedPaths.clear();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('tab', { name: 'Einheiten (1)' })).toBeVisible();
  });

  it('reports a failed property request with a retry and a safe back link', async () => {
    failedPaths.add('/properties/p1');
    renderDetail();
    expect(await screen.findByRole('alert')).toHaveTextContent('Immobilie konnte nicht geladen werden');
    expect(screen.getByRole('link', { name: 'Alle Immobilien' })).toHaveAttribute('href', '/properties');
    failedPaths.clear();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByRole('heading', { name: 'Villa Lindenhof' })).toBeVisible();
  });

  it('ignores a late response from the previous property after route navigation', async () => {
    let releaseOld;
    const originalGet = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(path => path === '/properties/p1' ? new Promise(resolve => { releaseOld = resolve; }) : originalGet(path));
    function Switch() { const navigate = useNavigate(); return <button onClick={() => navigate('/properties/p2')}>Other property</button>; }
    renderDetail('/properties/p1', <Switch />);
    fireEvent.click(screen.getByRole('button', { name: 'Other property' }));
    expect(await screen.findByRole('heading', { name: 'Stadthaus am Park' })).toBeVisible();
    await act(async () => releaseOld(props[0]));
    expect(screen.getByRole('heading', { name: 'Stadthaus am Park' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Villa Lindenhof' })).not.toBeInTheDocument();
  });
});

for (const locale of ['de-DE', 'en-US', 'es-ES']) {
  it(`provides translated inventory and detail navigation for ${locale}`, async () => {
    mocks.locale = locale;
    renderList();
    await screen.findByRole('link', { name: 'Villa Lindenhof' });
    expect(screen.getByRole('button', { name: translate('properties.create') })).toBeVisible();
    expect(screen.getByRole('searchbox', { name: translate('properties.search') })).toBeVisible();
    expect(screen.getByRole('button', { name: translate('properties.tableView') })).toBeVisible();
    const newKeys = Object.keys(de.properties).filter(key => !['list', 'types', 'form', 'tabs'].includes(key));
    for (const key of newKeys) expect(dictionaries[locale].properties[key], key).toBeTruthy();
  });
}
