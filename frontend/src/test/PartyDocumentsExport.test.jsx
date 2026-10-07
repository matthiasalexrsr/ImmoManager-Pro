import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Documents from '../pages/Documents';
import { api } from '../api';

const context = vi.hoisted(() => ({
  people: [{ id: 't1', full_name: 'Anna Müller' }], empty: [],
  t: key => key, store: { invalidateRelated: vi.fn() },
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: context.t, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => false }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({ items: key === 'tenants_all' ? context.people : context.empty }),
  useDataStore: () => context.store,
}));

const records = Array.from({ length: 501 }, (_, index) => ({
  id: `d${index}`, title: `Abrechnung ${String(index + 1).padStart(3, '0')}`, tenant_id: 't1',
  document_type: 'Rechnung', file_url: '/uploads/example.pdf',
}));
let createURL;
let revokeURL;
let originalCreate;
let originalRevoke;

function mount() {
  return render(<MemoryRouter initialEntries={['/documents?tenant_id=t1']}><Documents /></MemoryRouter>);
}
function readBlob(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result);
    reader.onerror = reject; reader.readAsText(blob);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  originalCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
  originalRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');
  createURL = vi.fn(() => 'blob:export'); revokeURL = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createURL });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeURL });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  api.get.mockImplementation(path => {
    const url = new URL(path, 'http://example.test');
    if (url.pathname.endsWith('/overview')) return Promise.resolve({ tenant: context.people[0], contracts: [], document_types: ['Rechnung'] });
    const skip = Number(url.searchParams.get('skip'));
    const limit = Number(url.searchParams.get('limit'));
    return Promise.resolve({ items: records.slice(skip, skip + limit), total: records.length, skip, limit, has_more: skip + limit < records.length });
  });
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks();
  if (originalCreate) Object.defineProperty(URL, 'createObjectURL', originalCreate); else delete URL.createObjectURL;
  if (originalRevoke) Object.defineProperty(URL, 'revokeObjectURL', originalRevoke); else delete URL.revokeObjectURL;
});

describe('complete party document exports', () => {
  it('exports every filtered record across API pages although the screen contains only 25', async () => {
    mount();
    await screen.findByText('Abrechnung 001');
    expect(screen.queryByText('Abrechnung 501')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Dokumente durchsuchen' }), { target: { value: 'Abrechnung' } });
    await screen.findByText('Abrechnung 001');
    fireEvent.change(screen.getByLabelText('Dokumententyp'), { target: { value: 'Rechnung' } });
    await screen.findByText('Abrechnung 001');
    fireEvent.click(screen.getByRole('button', { name: 'CSV', exact: true }));
    await waitFor(() => expect(createURL).toHaveBeenCalledTimes(1));
    const csv = await readBlob(createURL.mock.calls[0][0]);
    expect(csv).toContain('Abrechnung 001');
    expect(csv).toContain('Abrechnung 501');
    expect(csv).toContain('Anna Müller');
    expect(csv.trim().split('\n')).toHaveLength(502);
    const requests = api.get.mock.calls.map(([path]) => new URL(path, 'http://example.test'))
      .filter(url => url.searchParams.get('limit') === '500');
    expect(requests.map(url => url.searchParams.get('skip'))).toEqual(['0', '500']);
    for (const url of requests) {
      expect(url.pathname).toBe('/tenants/t1/documents');
      expect(url.searchParams.get('q')).toBe('Abrechnung');
      expect(url.searchParams.get('document_type')).toBe('Rechnung');
    }
  });

  it('reports a changed collection without downloading a truncated or duplicate export', async () => {
    const response = api.get.getMockImplementation();
    api.get.mockImplementation(async path => {
      const page = await response(path);
      return path.includes('skip=500') ? { ...page, total: 502 } : page;
    });
    mount();
    await screen.findByText('Abrechnung 001');
    fireEvent.click(screen.getByRole('button', { name: 'CSV', exact: true }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Dokumentbestand hat sich');
    expect(createURL).not.toHaveBeenCalled();
    expect(screen.getByText('Abrechnung 001')).toBeInTheDocument();
  });
});
