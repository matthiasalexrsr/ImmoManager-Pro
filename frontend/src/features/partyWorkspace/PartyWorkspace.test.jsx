import { act, fireEvent, render, screen, waitFor, within, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Link } from 'react-router-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import { PartyWorkspaceProvider, PartyLink } from './PartyWorkspace';

vi.mock('../../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../../contexts/AuthContext', () => ({ useCanWrite: vi.fn(() => true) }));

const tenant = { id: 't1', full_name: 'Anna Müller', archived: false, email: 'anna@example.com', phone: '+49 1234', address_line: 'Lindenstraße 8', postal_code: '10115', city: 'Berlin', country: 'DE', notes: 'Bitte per E-Mail kontaktieren.' };
const contracts = [
  { id: 'c1', tenant_id: 't1', contract_number: 'MV-24', property_name: 'Lindenhof', unit_label: '2. OG links', start_date: '2024-01-01', end_date: null, status: 'active', current_rent: { cold_rent: 800, service_charge: 100, heating_charge: 60, valid_from: '2024-01-01' } },
  { id: 'c2', tenant_id: 't1', contract_number: 'MV-20', property_name: 'Alte Villa', unit_label: 'EG', start_date: '2020-01-01', end_date: '2023-12-31', status: 'terminated', current_rent: null },
];
const overview = { tenant, contracts, document_count: 26, document_types: ['Mietvertrag', 'Protokoll'] };
const doc = { id: 'd1', tenant_id: 't1', contract_id: 'c1', title: 'Mietvertrag Anna', document_type: 'Mietvertrag', document_date: '2024-01-01', created_at: '2024-01-01T00:00:00Z', description: 'Unterzeichneter Vertrag', file_url: '/uploads/lease.pdf' };
const response = (items = [doc], extra = {}) => ({ items, total: items.length, skip: 0, limit: 25, has_more: false, ...extra });
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

function mount() {
  return render(<MemoryRouter><PartyWorkspaceProvider><PartyLink tenantId="t1">Anna Müller</PartyLink><PartyLink tenantId="t2">Ben Weber</PartyLink><Link to="/elsewhere">Andere Seite</Link></PartyWorkspaceProvider></MemoryRouter>);
}

beforeEach(() => {
  useCanWrite.mockReturnValue(true);
  api.get.mockImplementation(path => Promise.resolve(path.includes('/overview') ? overview : path.includes('/ocr-text') ? { has_ocr: false } : response()));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('party workspace', () => {
  it('keeps party account links usable without a provider or router', () => {
    render(<PartyLink tenantId="t1">Anna Müller</PartyLink>);
    expect(screen.getByRole('link', { name: 'Anna Müller' })).toHaveAttribute('href', '/tenants/t1/account');
  });

  it('opens one party with contact information and separate current and historical contracts', async () => {
    mount();
    const opener = screen.getByRole('button', { name: 'Anna Müller' });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Anna Müller' });
    expect(within(dialog).getByRole('link', { name: 'anna@example.com' })).toHaveAttribute('href', 'mailto:anna@example.com');
    expect(within(dialog).getByText('Lindenstraße 8')).toBeInTheDocument();
    expect(within(dialog).getByText('MV-24')).toBeInTheDocument();
    expect(within(dialog).getByText('MV-20')).toBeInTheDocument();
    expect(within(dialog).getByText(/800,00/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Miete gültig ab 01.01.2024/)).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Mieterkonto' })).toHaveAttribute('href', '/tenants/t1/account');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('preserves server ordering across documents with historical document dates', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('/overview') ? overview : response([
      { ...doc, id: 'd-new', title: 'Neu hochgeladen', document_date: '2020-01-01', created_at: '2026-01-01T00:00:00Z' },
      { ...doc, id: 'd-old', title: 'Früher hochgeladen', document_date: '2025-01-01', created_at: '2025-01-01T00:00:00Z' },
    ])));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    await screen.findByRole('button', { name: 'Neu hochgeladen' });
    const list = screen.getByRole('list', { name: 'Dokumente' });
    expect(within(list).getAllByRole('listitem').map(item => within(item).getAllByRole('button')[0].textContent)).toEqual(['Neu hochgeladen', 'Früher hochgeladen']);
  });

  it('ignores a previous party response when another party is opened', async () => {
    const old = deferred();
    api.get.mockImplementation(path => path === '/tenants/t1/overview' ? old.promise : Promise.resolve({ ...overview, tenant: { ...tenant, id: 't2', full_name: 'Ben Weber' } }));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    fireEvent.click(screen.getByRole('button', { name: 'Ben Weber' }));
    await screen.findByRole('dialog', { name: 'Ben Weber' });
    await act(async () => old.resolve(overview));
    expect(screen.getByRole('dialog', { name: 'Ben Weber' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Anna Müller' })).not.toBeInTheDocument();
  });

  it('closes on navigation from the panel and hides edit and upload actions for read-only users', async () => {
    useCanWrite.mockReturnValue(false);
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    expect(screen.queryByRole('link', { name: 'Mieter bearbeiten' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    await screen.findByRole('button', { name: doc.title });
    expect(screen.queryByRole('link', { name: 'Dokument hinzufügen' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Dokumentenverwaltung/ })).toHaveAttribute('href', '/documents?tenant_id=t1');
    fireEvent.click(screen.getByRole('link', { name: 'Mieterkonto' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('copies the address and exposes errors without replacing them with empty data', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    fireEvent.click(screen.getByRole('button', { name: 'Kopieren: Adresse' }));
    await screen.findByRole('button', { name: 'Kopiert: Adresse' });
    expect(writeText).toHaveBeenCalledWith('Lindenstraße 8\n10115 Berlin\nDE');
    api.get.mockRejectedValue(new Error('Verbindung unterbrochen'));
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Verbindung unterbrochen');
    expect(screen.queryByText('Noch keine Dokumente')).not.toBeInTheDocument();
    api.get.mockResolvedValue(response());
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    await screen.findByRole('button', { name: doc.title });
  });

  it('traps keyboard focus and supports arrow-key tab selection', async () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    const dialog = await screen.findByRole('dialog', { name: 'Anna Müller' });
    const close = within(dialog).getByRole('button', { name: 'Schließen' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(within(dialog).getAllByRole('button', { name: 'Dokumente zu diesem Vertrag' }).at(-1)).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();
    const overviewTab = screen.getByRole('tab', { name: 'Übersicht' });
    overviewTab.focus();
    fireEvent.keyDown(overviewTab, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /Dokumente/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /Dokumente/ })).toHaveFocus();
  });

  it('loads all paginated results and removes the more action when the final page arrives', async () => {
    api.get.mockImplementation(path => {
      if (path.includes('/overview')) return Promise.resolve(overview);
      if (path.includes('skip=25')) return Promise.resolve(response([{ ...doc, id: 'last', title: 'Letztes Dokument' }], { total: 26, skip: 25 }));
      return Promise.resolve(response(Array.from({ length: 25 }, (_, i) => ({ ...doc, id: `d${i}`, title: `Dokument ${i}` })), { total: 26, has_more: true }));
    });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    const more = await screen.findByRole('button', { name: 'Weitere Dokumente laden' });
    fireEvent.click(more);
    await screen.findByRole('button', { name: 'Letztes Dokument' });
    expect(screen.getAllByRole('listitem')).toHaveLength(26);
    expect(screen.queryByRole('button', { name: 'Weitere Dokumente laden' })).not.toBeInTheDocument();
  });

  it('pages party documents and keeps existing results visible after a page error', async () => {
    api.get.mockImplementation(path => {
      if (path.includes('/overview')) return Promise.resolve(overview);
      if (path.includes('skip=25')) return Promise.reject(new Error('Server nicht erreichbar'));
      return Promise.resolve(response(Array.from({ length: 25 }, (_, i) => ({ ...doc, id: `d${i}`, title: `Dokument ${i}` })), { total: 26, has_more: true }));
    });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    await screen.findByRole('button', { name: 'Dokument 0' });
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Dokumente laden' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Dokument 0' })).toBeInTheDocument();
    expect(screen.queryByText('Noch keine Dokumente')).not.toBeInTheDocument();
  });

  it('ignores stale search responses and applies type and contract filters to the scoped endpoint', async () => {
    const old = deferred();
    api.get.mockImplementation(path => {
      if (path.includes('/overview')) return Promise.resolve(overview);
      if (path.includes('q=alt')) return old.promise;
      return Promise.resolve(response([{ ...doc, title: path.includes('q=neu') ? 'Neues Dokument' : doc.title }]));
    });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    await screen.findByRole('button', { name: doc.title });
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'alt' } });
    await waitFor(() => expect(api.get.mock.calls.some(([path]) => path.includes('q=alt'))).toBe(true));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'neu' } });
    await screen.findByRole('button', { name: 'Neues Dokument' });
    await act(async () => old.resolve(response([{ ...doc, title: 'Altes Dokument' }])));
    expect(screen.queryByRole('button', { name: 'Altes Dokument' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Dokumententyp'), { target: { value: 'Protokoll' } });
    fireEvent.change(screen.getByLabelText('Vertrag'), { target: { value: 'c1' } });
    await waitFor(() => expect(api.get.mock.calls.some(([path]) => path.startsWith('/tenants/t1/documents?') && path.includes('document_type=Protokoll') && path.includes('contract_id=c1'))).toBe(true));
  });

  it('closes only the preview on Escape and restores focus to its document button', async () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Anna Müller' }));
    await screen.findByRole('dialog', { name: 'Anna Müller' });
    fireEvent.click(screen.getByRole('tab', { name: /Dokumente/ }));
    const preview = await screen.findByRole('button', { name: doc.title });
    preview.focus();
    fireEvent.click(preview);
    await screen.findByRole('dialog', { name: doc.title });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: doc.title })).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Anna Müller' })).toBeInTheDocument();
    expect(preview).toHaveFocus();
  });
});
