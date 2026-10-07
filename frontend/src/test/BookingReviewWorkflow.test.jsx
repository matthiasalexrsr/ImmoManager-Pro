import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import Bookings from '../pages/Bookings';
import ReviewList from '../pages/ReviewList';
import { api } from '../api';

const pdfSources = vi.hoisted(() => []);
vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: {}, getDocument: options => {
  pdfSources.push(options.url);
  return { promise: new Promise(() => {}), destroy: async () => {} };
} }));

const context = vi.hoisted(() => ({
  canWrite: true,
  entities: {},
  empty: [],
  store: { invalidateRelated: vi.fn() },
  toast: { error: vi.fn(), success: vi.fn() },
  t: key => ({
    'ui.buttons.save': 'Speichern', 'ui.buttons.cancel': 'Abbrechen',
    'ui.buttons.close': 'Schließen', 'ui.buttons.edit': 'Bearbeiten',
    'ui.buttons.delete': 'Löschen', 'ui.table.noResults': 'Keine Ergebnisse',
    'ui.form.pleaseSelect': 'Bitte wählen',
  })[key],
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: context.t, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => context.canWrite }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({ items: context.entities[key] || context.empty, loading: false, error: null }),
  useDataStore: () => context.store,
}));
vi.mock('../components/Toast', () => ({ useToast: () => context.toast }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));

const booking = (id, extra = {}) => ({
  id, account_id: 'a1', category_id: null, property_id: 'p1', unit_id: 'u1',
  tenant_id: null, booking_date: '2026-09-03', amount: 612, payment_text: `Überweisung ${id}`,
  receipt_url: null, status: 'open', created_at: '2026-09-03T10:00:00', updated_at: '2026-09-03T10:00:00',
  ...extra,
});
const first = booking('first');
const target = booking('target', { receipt_url: '/uploads/target.pdf' });
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function mount(path = '/bookings?booking_id=target') {
  return render(<MemoryRouter initialEntries={[path]}>
    <Link to="/bookings?booking_id=other">Anderen Prüffall öffnen</Link>
    <Routes>
      <Route path="/bookings" element={<Bookings />} />
      <Route path="/review" element={<ReviewList />} />
    </Routes>
  </MemoryRouter>);
}

beforeEach(() => {
  pdfSources.length = 0;
  vi.resetAllMocks();
  localStorage.clear();
  context.canWrite = true;
  context.entities = {
    accounts: [{ id: 'a1', name: 'Mietkonto' }],
    categories: [{ id: 'cat1', name: 'Miete' }],
    properties: [{ id: 'p1', name: 'Haus A' }],
    units: [{ id: 'u1', property_id: 'p1', label: 'Wohnung 1' }],
    tenants: [{ id: 't1', full_name: 'Anna Müller' }],
    contracts: [{ id: 'c1', tenant_id: 't1', unit_id: 'u1', contract_number: 'MV-1' }],
  };
  api.list.mockResolvedValue([first]);
  api.get.mockImplementation(path => {
    if (path === '/bookings/allocations') return Promise.resolve([]);
    if (path === '/bookings/target') return Promise.resolve(target);
    if (path === '/bookings/other') return Promise.resolve(booking('other'));
    if (path === '/review') return Promise.resolve({ items: [] });
    if (path.startsWith('/files/ocr-text')) return Promise.resolve({ has_ocr: false });
    return Promise.reject(new Error(`Unerwarteter Abruf: ${path}`));
  });
});
afterEach(cleanup);

describe('Prüfliste', () => {
  it('keeps a failed review request distinct from an empty list and supports retry', async () => {
    api.get.mockRejectedValueOnce(new Error('Prüfung offline')).mockResolvedValueOnce({ items: [] });
    mount('/review');
    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent('Prüfung offline');
    expect(screen.queryByText('Nichts zu prüfen.')).not.toBeInTheDocument();
    fireEvent.click(within(error).getByRole('button', { name: /Erneut/ }));
    expect(await screen.findByText('Nichts zu prüfen.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('Konkreter Buchungsprüffall', () => {
  it('follows the concrete review link through the receipt and back to the review list', async () => {
    const review = { items: [{ kind: 'payment_without_tenant', severity: 'info', entity_id: 'target',
      title: 'Zahlungseingang prüfen', detail: '612 Euro ohne Mieter', link: '/bookings?booking_id=target' }] };
    api.get.mockImplementation(path => {
      if (path === '/review') return Promise.resolve(review);
      if (path === '/bookings/allocations') return Promise.resolve([]);
      if (path.startsWith('/files/ocr-text')) return Promise.resolve({ has_ocr: false });
      return Promise.resolve(target);
    });
    mount('/review');
    fireEvent.click(await screen.findByRole('link', { name: 'Öffnen' }));
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    fireEvent.click(await within(selected).findByRole('button', { name: 'Beleg öffnen' }));
    const viewer = await screen.findByRole('dialog', { name: /Überweisung target/ });
    expect(within(viewer).getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', `${window.location.origin}/uploads/target.pdf`);
    await waitFor(() => expect(pdfSources).toContain(`${window.location.origin}/uploads/target.pdf`));
    fireEvent.click(within(viewer).getByRole('button', { name: 'Schließen' }));
    fireEvent.click(within(selected).getByRole('link', { name: /Zur Prüfliste/ }));
    expect(await screen.findByText('Zahlungseingang prüfen')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Ausgewählte Buchung' })).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('preserves special characters in a selected ID through query and API encoding', async () => {
    api.get.mockImplementation(path => {
      if (path === '/bookings/allocations') return Promise.resolve([]);
      if (path === '/bookings/bank%20%2B%3F%23%C3%A4') return Promise.resolve(booking('bank +?#ä'));
      return Promise.reject(new Error('Falscher Datensatz'));
    });
    mount('/bookings?booking_id=bank%20%2B%3F%23%C3%A4');
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    expect(await within(selected).findByText('Überweisung bank +?#ä')).toBeInTheDocument();
  });

  it('reports an empty explicit ID instead of treating it as a normal list', async () => {
    mount('/bookings?booking_id=');
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    expect(await within(selected).findByRole('alert')).toHaveTextContent('Buchungs-ID ist ungültig');
    expect(within(selected).queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
  });

  it('loads the named booking independently of the list and opens its original receipt for a reader', async () => {
    context.canWrite = false;
    mount();
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    expect(selected).toHaveTextContent('Überweisung target');
    expect(selected).not.toHaveTextContent('Überweisung first');
    expect(within(selected).getByRole('link', { name: /Zur Prüfliste/ })).toHaveAttribute('href', '/review');
    expect(within(selected).queryByRole('button', { name: /Bearbeiten|Aufteilen/ })).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(within(selected).getByRole('button', { name: 'Beleg öffnen' }));
    const viewer = await screen.findByRole('dialog', { name: /Überweisung target/ });
    expect(within(viewer).getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', `${window.location.origin}/uploads/target.pdf`);
    await waitFor(() => expect(pdfSources).toContain(`${window.location.origin}/uploads/target.pdf`));
    expect(screen.queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
  });

  it('shows a failed exact lookup without substituting the first booking', async () => {
    api.get.mockImplementation(path => path === '/bookings/allocations'
      ? Promise.resolve([]) : Promise.reject(new Error('Buchung nicht gefunden')));
    mount('/bookings?booking_id=missing');
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    expect(await within(selected).findByRole('alert')).toHaveTextContent('Buchung nicht gefunden');
    expect(selected).not.toHaveTextContent('Überweisung first');
    expect(within(selected).queryByRole('button', { name: /Bearbeiten|Beleg öffnen/ })).not.toBeInTheDocument();
  });

  it('rejects a response for a different ID and allows retry of the selected ID', async () => {
    let attempts = 0;
    api.get.mockImplementation(path => {
      if (path === '/bookings/allocations') return Promise.resolve([]);
      if (path === '/bookings/target') return Promise.resolve(attempts++ ? target : first);
      return Promise.reject(new Error(path));
    });
    mount();
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    const error = await within(selected).findByRole('alert');
    expect(selected).not.toHaveTextContent('Überweisung first');
    fireEvent.click(within(error).getByRole('button', { name: /Erneut/ }));
    expect(await within(selected).findByText('Überweisung target')).toBeInTheDocument();
  });

  it('does not let a late answer from the previous ID replace the current case', async () => {
    const pending = deferred();
    api.get.mockImplementation(path => {
      if (path === '/bookings/allocations') return Promise.resolve([]);
      return path === '/bookings/target' ? pending.promise : Promise.resolve(booking('other'));
    });
    mount();
    fireEvent.click(screen.getByRole('link', { name: 'Anderen Prüffall öffnen' }));
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    expect(await within(selected).findByText('Überweisung other')).toBeInTheDocument();
    await act(async () => { pending.resolve(target); });
    expect(selected).not.toHaveTextContent('Überweisung target');
    expect(selected).toHaveTextContent('Überweisung other');
  });

  it('closes the old receipt when navigating to another case', async () => {
    mount();
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    fireEvent.click(await within(selected).findByRole('button', { name: 'Beleg öffnen' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Anderen Prüffall öffnen' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText('Überweisung other')).toBeInTheDocument();
  });

  it.each([[null, /Kein Beleg/], ['javascript:alert(1)', /Belegadresse.*ungültig/]])(
    'identifies missing or invalid receipt %s instead of opening a preview', async (receipt, message) => {
      api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : booking('target', { receipt_url: receipt })));
      mount();
      const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
      expect(await within(selected).findByText(message)).toBeInTheDocument();
      expect(within(selected).queryByRole('button', { name: 'Beleg öffnen' })).not.toBeInTheDocument();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    },
  );

  it('preserves edits when saving fails and refreshes the selected record after success', async () => {
    let current = target;
    api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : current));
    api.put.mockRejectedValueOnce(new Error('Datensatz wurde inzwischen geändert'))
      .mockImplementationOnce(async (_path, payload) => { current = { ...target, ...payload }; return current; });
    mount();
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    fireEvent.click(await within(selected).findByRole('button', { name: 'Bearbeiten' }));
    const form = screen.getByRole('dialog', { name: 'Buchung bearbeiten' });
    fireEvent.change(within(form).getByLabelText('Buchungstext'), { target: { value: 'Geklärter Zahlungseingang' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Speichern' }));
    expect(await within(form).findByText('Datensatz wurde inzwischen geändert')).toBeInTheDocument();
    expect(within(form).getByLabelText('Buchungstext')).toHaveValue('Geklärter Zahlungseingang');
    fireEvent.click(within(form).getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await within(selected).findByText('Geklärter Zahlungseingang')).toBeInTheDocument();
    expect(api.put).toHaveBeenLastCalledWith('/bookings/target', expect.objectContaining({ payment_text: 'Geklärter Zahlungseingang' }));
  });
});

describe('Buchungs- und Zuordnungsladung', () => {
  it('does not turn a failed booking list into zero totals and recovers on retry', async () => {
    api.list.mockRejectedValueOnce(new Error('Buchungen offline')).mockResolvedValueOnce([first]);
    mount('/bookings');
    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent('Buchungen offline');
    expect(screen.queryByText('Keine Ergebnisse')).not.toBeInTheDocument();
    expect(screen.queryByText('Gesamt')).not.toBeInTheDocument();
    fireEvent.click(within(error).getByRole('button', { name: /Erneut/ }));
    expect(await screen.findByText('Überweisung first')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('makes failed allocations unknown, blocks splitting, then restores the real assignment on retry', async () => {
    const assigned = booking('target', { tenant_id: 't1' });
    let attempts = 0;
    api.get.mockImplementation(path => {
      if (path === '/bookings/allocations') return attempts++
        ? Promise.resolve([{ id: 'pa1', booking_id: 'target', contract_id: 'c1', amount: 612, source: 'manual' }])
        : Promise.reject(new Error('Zuordnungen offline'));
      return Promise.resolve(assigned);
    });
    mount();
    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent('Zuordnungen offline');
    const selected = screen.getByRole('region', { name: 'Ausgewählte Buchung' });
    expect(selected).toHaveTextContent('Zuordnung nicht verfügbar');
    expect(within(selected).queryByRole('button', { name: 'Aufteilen' })).not.toBeInTheDocument();
    fireEvent.click(within(error).getByRole('button', { name: /Erneut/ }));
    expect(await within(selected).findByText('MV-1')).toBeInTheDocument();
    expect(within(selected).getByRole('button', { name: 'Aufteilen' })).toBeInTheDocument();
    expect(selected).not.toHaveTextContent('nicht zugeordnet: 612');
  });

  it('keeps entered split amounts after an unsuccessful save', async () => {
    api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : booking('target', { tenant_id: 't1' })));
    api.put.mockRejectedValue(new Error('Zuordnung derzeit nicht möglich'));
    mount();
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    fireEvent.click(await within(selected).findByRole('button', { name: 'Aufteilen' }));
    const form = screen.getByRole('dialog', { name: 'Zahlung aufteilen' });
    fireEvent.change(within(form).getByLabelText('Vertrag MV-1 (€)'), { target: { value: '300' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Speichern' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Zuordnung derzeit nicht möglich');
    expect(within(form).getByLabelText('Vertrag MV-1 (€)')).toHaveValue(300);
  });

  it('does not discard a reopened split form when an older save finishes', async () => {
    const pending = deferred();
    api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : booking('target', { tenant_id: 't1' })));
    api.put.mockReturnValue(pending.promise);
    mount();
    const selected = await screen.findByRole('region', { name: 'Ausgewählte Buchung' });
    fireEvent.click(await within(selected).findByRole('button', { name: 'Aufteilen' }));
    const oldForm = screen.getByRole('dialog', { name: 'Zahlung aufteilen' });
    fireEvent.change(within(oldForm).getByLabelText('Vertrag MV-1 (€)'), { target: { value: '300' } });
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Speichern' }));
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Abbrechen' }));
    fireEvent.click(within(selected).getByRole('button', { name: 'Aufteilen' }));
    const newForm = screen.getByRole('dialog', { name: 'Zahlung aufteilen' });
    fireEvent.change(within(newForm).getByLabelText('Vertrag MV-1 (€)'), { target: { value: '111' } });
    await act(async () => { pending.resolve([]); });
    expect(screen.getByRole('dialog', { name: 'Zahlung aufteilen' })).toBeInTheDocument();
    expect(within(newForm).getByLabelText('Vertrag MV-1 (€)')).toHaveValue(111);
  });
});
