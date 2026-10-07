import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Documents from '../pages/Documents';
import { api } from '../api';

const context = vi.hoisted(() => ({
  canWrite: true,
  entities: {},
  empty: [],
  store: { invalidateRelated: vi.fn() },
  openParty: vi.fn(),
  t: key => ({
    'ui.buttons.save': 'Speichern',
    'ui.buttons.cancel': 'Abbrechen',
    'ui.buttons.close': 'Schließen',
    'ui.buttons.edit': 'Bearbeiten',
    'ui.buttons.delete': 'Löschen',
    'ui.table.noResults': 'Keine Ergebnisse',
    'ui.form.pleaseSelect': 'Bitte wählen',
  })[key],
}));

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: context.t, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => context.canWrite }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({ items: context.entities[key] || context.empty }),
  useDataStore: () => context.store,
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({
  usePartyWorkspace: () => ({ openParty: context.openParty }),
  PartyLink: ({ tenantId, children }) => tenantId
    ? <button type="button" onClick={event => { event.stopPropagation(); context.openParty(tenantId); }}>{children}</button>
    : <span>{children}</span>,
}));
vi.mock('../components/FileViewer', () => ({
  default: ({ fileUrl, title, onClose }) => <div role="dialog" aria-label={title || 'Dateiansicht'}>
    <p>{fileUrl}</p><button onClick={onClose}>Schließen</button>
  </div>,
}));

const anna = { id: 't1', full_name: 'Anna Müller' };
const ben = { id: 't2', full_name: 'Ben Weber' };
const contract = { id: 'c1', tenant_id: 't1', contract_number: 'MV-2020', status: 'terminated' };
const direct = { id: 'd1', tenant_id: 't1', contract_id: null, title: 'Direkter Brief', document_type: 'Sonstiges', file_url: '/uploads/brief.docx' };
const legacy = { id: 'd2', tenant_id: null, contract_id: 'c1', title: 'Historischer Mietvertrag', document_type: 'Mietvertrag', file_url: '/uploads/vertrag.pdf' };
const overview = person => ({ tenant: person, contracts: person.id === 't1' ? [contract] : [], document_types: ['Mietvertrag', 'Rechnung', 'Sonstiges'] });
const page = (items, extra = {}) => ({ items, total: items.length, skip: 0, limit: 25, has_more: false, ...extra });
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const documentRequests = () => api.get.mock.calls
  .filter(([path]) => new URL(path, 'http://example.test').pathname.endsWith('/documents'))
  .map(([path]) => new URL(path, 'http://example.test'));

function mount(url = '/documents?tenant_id=t1') {
  return render(<MemoryRouter initialEntries={[url]}><Documents /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  context.canWrite = true;
  context.entities = { tenants_all: [anna, ben], properties: [], units: [], contracts: [contract] };
  api.get.mockImplementation(path => {
    const parsed = new URL(path, 'http://example.test');
    if (parsed.pathname.endsWith('/overview')) return Promise.resolve(overview(parsed.pathname.includes('/t2/') ? ben : anna));
    if (parsed.pathname.endsWith('/documents')) return Promise.resolve(page([direct, legacy]));
    return Promise.reject(new Error(`Unexpected GET ${path}`));
  });
  api.list.mockResolvedValue([direct, legacy]);
  api.post.mockResolvedValue({});
  api.put.mockResolvedValue({});
  vi.stubGlobal('fetch', vi.fn());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('party documents page', () => {
  it('shows direct and historical-contract documents from the scoped endpoint, with server paging and filters', async () => {
    const documents = Array.from({ length: 26 }, (_, index) => ({ ...(index === 0 ? legacy : direct), id: `d${index}`, title: `Unterlage ${index}` }));
    api.get.mockImplementation(path => {
      const parsed = new URL(path, 'http://example.test');
      if (parsed.pathname.endsWith('/overview')) return Promise.resolve(overview(anna));
      const skip = Number(parsed.searchParams.get('skip'));
      const items = parsed.searchParams.get('q') ? [{ ...legacy, title: 'Abrechnung älter & neu', document_type: 'Rechnung' }] : documents;
      return Promise.resolve(page(items.slice(skip, skip + 25), { total: items.length, skip, has_more: skip + 25 < items.length }));
    });
    mount();
    await screen.findByText('Unterlage 0');
    expect(screen.getByText('MV-2020')).toBeInTheDocument();
    fireEvent.click(within(screen.getByText('Unterlage 0').closest('tr')).getByRole('button', { name: 'Anna Müller' }));
    expect(context.openParty).toHaveBeenCalledWith('t1');
    expect(screen.getByText('1–25 von 26')).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
    expect(documentRequests()[0].pathname).toBe('/tenants/t1/documents');
    expect(Object.fromEntries(documentRequests()[0].searchParams)).toEqual({ skip: '0', limit: '25', q: '', document_type: '' });

    fireEvent.click(screen.getByRole('button', { name: 'Weitere Dokumente' }));
    await screen.findByText('Unterlage 25');
    expect(documentRequests().at(-1).searchParams.get('skip')).toBe('25');
    fireEvent.change(screen.getByLabelText('Dokumente durchsuchen'), { target: { value: 'älter & neu' } });
    await screen.findByText('Abrechnung älter & neu');
    fireEvent.change(screen.getByLabelText('Dokumententyp'), { target: { value: 'Rechnung' } });
    await waitFor(() => expect(Object.fromEntries(documentRequests().at(-1).searchParams)).toEqual({ skip: '0', limit: '25', q: 'älter & neu', document_type: 'Rechnung' }));
  });

  it('keeps direct tenant assignments out of the unassigned filter', async () => {
    const unassigned = { ...direct, id: 'orphan', tenant_id: null, title: 'Ohne Partei' };
    api.list.mockResolvedValue([direct, unassigned]);
    mount('/documents');
    await screen.findByText('Direkter Brief');
    fireEvent.click(screen.getByRole('button', { name: 'Ohne Zuordnung' }));
    expect(screen.getByText('Ohne Partei')).toBeInTheDocument();
    expect(screen.queryByText('Direkter Brief')).not.toBeInTheDocument();
  });

  it('prefills an uploaded document for the selected tenant and saves the reviewed values with that file', async () => {
    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ file_url: '/uploads/brief-neu.docx' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ file_url: '/uploads/zweiter.docx' }) });
    mount();
    await screen.findByText('Direkter Brief');
    fireEvent.change(screen.getByLabelText('Dokumentdateien wählen'), {
      target: { files: [new File(['brief'], 'Brief.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })] },
    });
    const dialog = await screen.findByRole('dialog', { name: 'Dokument erstellen' });
    await waitFor(() => expect(within(dialog).getByLabelText('Mieter / Partei')).toHaveValue('t1'));
    expect(within(dialog).getByLabelText(/Titel/)).toHaveValue('Brief');
    fireEvent.change(within(dialog).getByLabelText(/Titel/), { target: { value: 'Persönlicher Brief' } });
    fireEvent.change(within(dialog).getByLabelText('Tags'), { target: { value: 'Kontakt, geprüft' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/documents', expect.objectContaining({
      tenant_id: 't1', file_url: '/uploads/brief-neu.docx', title: 'Persönlicher Brief', tags: 'Kontakt, geprüft', contract_id: null,
    })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByText(/Hochgeladen:/)).not.toBeInTheDocument();
    expect(context.store.invalidateRelated).toHaveBeenCalledWith('documents');

    fireEvent.change(screen.getByLabelText('Dokumentdateien wählen'), { target: { files: [new File(['neu'], 'Zweiter.docx')] } });
    const next = await screen.findByRole('dialog', { name: 'Dokument erstellen' });
    await waitFor(() => expect(within(next).getByLabelText(/Titel/)).toHaveValue('Zweiter'));
    fireEvent.click(within(next).getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.post).toHaveBeenLastCalledWith('/documents', expect.objectContaining({ tenant_id: 't1', title: 'Zweiter', file_url: '/uploads/zweiter.docx' })));
  });

  it('imports every file with the tenant ID and shows success only after persistence, retaining each failure', async () => {
    const pending = deferred();
    fetch.mockReturnValueOnce(pending.promise).mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ error: { message: 'Zuordnung wurde abgelehnt' } }) });
    mount();
    await screen.findByText('Direkter Brief');
    const files = [new File(['a'], 'Erste.docx'), new File(['b'], 'Zweite.docx')];
    fireEvent.change(screen.getByLabelText('Dokumentdateien wählen'), { target: { files } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/Gespeichert/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Dokumentdateien wählen')).toBeDisabled();
    await act(async () => pending.resolve({ ok: true, json: async () => ({ id: 'new-doc' }) }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await screen.findByText(/Zuordnung wurde abgelehnt/);
    const queue = (await screen.findByText(/Erste\.docx — Gespeichert/)).closest('[role="status"]');
    expect(queue).toHaveTextContent('✓ Erste.docx — Gespeichert');
    expect(queue).toHaveTextContent('✗ Zweite.docx');
    expect(queue).not.toHaveTextContent('Zweite.docx — Gespeichert');
    expect(screen.getByLabelText('Dokumentdateien wählen')).toBeEnabled();
    for (const [index, [url, options]] of fetch.mock.calls.entries()) {
      expect(url).toBe('/api/v1/documents/import');
      expect(options.method).toBe('POST');
      expect(options.body).toBeInstanceOf(FormData);
      expect(options.body.get('file')).toBe(files[index]);
      expect(options.body.get('tenant_id')).toBe('t1');
      expect(options.body.get('title')).toBe(index === 0 ? 'Erste' : 'Zweite');
    }
    expect(api.post).not.toHaveBeenCalled();
  });

  it('allows readers to view documents without upload, edit, or delete controls', async () => {
    context.canWrite = false;
    mount();
    await screen.findByText('Direkter Brief');
    expect(screen.queryByRole('button', { name: 'Dokumente hochladen' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Dokumentdateien wählen')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Löschen' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Dokument ansehen' })).toHaveLength(2);
  });

  it('reports a failed search instead of presenting it as an empty result', async () => {
    const success = api.get.getMockImplementation();
    api.get.mockImplementation((path, options) => new URL(path, 'http://example.test').searchParams.get('q') === 'Ausfall'
      ? Promise.reject(new Error('Dokumentsuche ist nicht erreichbar')) : success(path, options));
    mount();
    await screen.findByText('Direkter Brief');
    fireEvent.change(screen.getByLabelText('Dokumente durchsuchen'), { target: { value: 'Ausfall' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Dokumentsuche ist nicht erreichbar');
    expect(screen.queryByText('Keine Dokumente')).not.toBeInTheDocument();
    expect(screen.queryByText('Keine Ergebnisse')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Erneut laden' })).toBeInTheDocument();
  });

  it('ignores late results for the previous tenant when the selected party changes', async () => {
    const oldPage = deferred();
    const oldOverview = deferred();
    const benDoc = { ...direct, id: 'ben-doc', tenant_id: 't2', title: 'Brief für Ben' };
    api.get.mockImplementation(path => {
      const pathname = new URL(path, 'http://example.test').pathname;
      if (pathname === '/tenants/t1/overview') return oldOverview.promise;
      if (pathname === '/tenants/t1/documents') return oldPage.promise;
      return Promise.resolve(pathname.endsWith('/overview') ? overview(ben) : page([benDoc]));
    });
    mount();
    await waitFor(() => expect(documentRequests()).toHaveLength(1));
    fireEvent.change(screen.getByLabelText('Mieter / Partei'), { target: { value: 't2' } });
    await screen.findByText('Brief für Ben');
    await act(async () => { oldPage.resolve(page([direct])); oldOverview.resolve(overview(anna)); });
    expect(screen.getByText('Brief für Ben')).toBeInTheDocument();
    expect(screen.queryByText('Direkter Brief')).not.toBeInTheDocument();
    expect(screen.getByText(/Dokumente von Ben Weber/)).toBeInTheDocument();
  });

  it('opens the preview from the keyboard-accessible document action', async () => {
    const user = userEvent.setup();
    mount();
    const row = (await screen.findByText('Direkter Brief')).closest('tr');
    const preview = within(row).getByRole('button', { name: 'Dokument ansehen' });
    preview.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('dialog', { name: 'Direkter Brief' })).toHaveTextContent('/uploads/brief.docx');
    expect(context.openParty).not.toHaveBeenCalled();
  });
});
