import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import Meters from '../pages/Meters';
import Leads from '../pages/Leads';
import Documents from '../pages/Documents';

const context = vi.hoisted(() => ({ empty: [] }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => false }));
vi.mock('../contexts/DataStoreContext', () => ({ useEntities: () => ({ items: context.empty }), useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ usePartyWorkspace: () => null, PartyLink: ({ children }) => <span>{children}</span> }));
const show = element => render(<MemoryRouter>{element}</MemoryRouter>);
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 9, 15, 12));
  api.list.mockResolvedValue([]); api.get.mockResolvedValue({});
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('remaining exact KPI sources', () => {
  it('opens the identical meter inspection and type bases, including inactive inspection candidates', async () => {
    api.list.mockImplementation(async path => path === '/meters' ? [
      { id: 'm1', serial_number: 'Alter Wasserzähler', meter_type: 'cold_water', is_active: false, next_inspection: '2026-10-20' },
      { id: 'm2', serial_number: 'Neuer Wasserzähler', meter_type: 'cold_water', is_active: true },
      { id: 'm3', serial_number: 'Heizungszähler', meter_type: 'heating', is_active: true, next_inspection: '2026-12-01' },
    ] : []);
    show(<Meters />);
    fireEvent.click(await screen.findByRole('button', { name: 'Prüfung fällig: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Alter Wasserzähler')).toBeInTheDocument();
    expect(screen.queryByText('Neuer Wasserzähler')).not.toBeInTheDocument();
    expect(screen.queryByText('Heizungszähler')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Kaltwasser: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Alter Wasserzähler')).toBeInTheDocument();
    expect(screen.getByText('Neuer Wasserzähler')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Aktiv: Quellvorgänge anzeigen' }));
    expect(screen.queryByText('Alter Wasserzähler')).not.toBeInTheDocument();
    expect(screen.getByText('Heizungszähler')).toBeInTheDocument();
  });

  it('opens lead status sources and resets an existing table search for the total', async () => {
    api.list.mockImplementation(async path => path === '/leads' ? [{ id: 'l1', full_name: 'Anna Anfrage', status: 'new' }, { id: 'l2', full_name: 'Ben Bestätigt', status: 'accepted' }] : []);
    show(<Leads />);
    fireEvent.click(await screen.findByRole('button', { name: 'Angenommen: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Ben Bestätigt')).toBeInTheDocument();
    expect(screen.queryByText('Anna Anfrage')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Nicht vorhanden' } });
    fireEvent.click(screen.getByRole('button', { name: 'Gesamt: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Anna Anfrage')).toBeInTheDocument();
    expect(screen.getByText('Ben Bestätigt')).toBeInTheDocument();
  });

  it('names lead statuses in German, also when grouped, and links an inquiry to its re-letting project', async () => {
    api.list.mockImplementation(async path => path === '/leads' ? [
      { id: 'l1', full_name: 'Anna Anfrage', status: 'contacted', project_id: 'p1' },
      { id: 'l2', full_name: 'Zora Zurück', status: 'withdrawn' }] : []);
    show(<Leads />);
    expect(await screen.findByRole('button', { name: 'Zurückgezogen: Quellvorgänge anzeigen' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Projekt öffnen' })).toHaveAttribute('href', '/reletting/p1?tab=applicants');
    fireEvent.click(within(screen.getByText('Gruppieren nach:').parentElement).getByRole('button', { name: 'Status' }));
    expect(screen.getByRole('heading', { name: 'Kontaktiert (1)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Zurückgezogen (1)' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /withdrawn|contacted/ })).not.toBeInTheDocument();
  });

  it.each([[Meters, 'Zähler gesamt'], [Leads, 'Gesamt']])('shows unavailable source counts instead of invented zeroes', async (Page, label) => {
    api.list.mockImplementation(async path => { if (path === '/meters' || path === '/leads') throw new Error('Quelle offline'); return []; });
    show(<Page />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Quelle offline');
    expect(screen.getByRole('button', { name: `${label}: Quellvorgänge anzeigen` })).toHaveTextContent('—');
  });

  it('opens file and OCR sources against the complete unscoped document list', async () => {
    api.list.mockResolvedValue([{ id: 'd1', title: 'Erkannter Beleg', file_url: '/uploads/a.pdf', ocr_status: 'completed' },
      { id: 'd2', title: 'Papierakte', ocr_status: null }]);
    show(<Documents />);
    fireEvent.click(await screen.findByRole('button', { name: 'Text erkannt: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Erkannter Beleg')).toBeInTheDocument();
    expect(screen.queryByText('Papierakte')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Gesamt: Quellvorgänge anzeigen' }));
    expect(screen.getByText('Papierakte')).toBeInTheDocument();
  });
});
