import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import HandoverProtocols from '../pages/HandoverProtocols';
import Leads from '../pages/Leads';
import Listings from '../pages/Listings';
import Viewings from '../pages/Viewings';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  confirm: vi.fn(),
  failed: new Set(),
  data: {},
  entities: {},
  invalidateRelated: vi.fn(),
}));

vi.mock('../api', () => ({
  api: { get: mocks.get, post: mocks.post, put: mocks.put, del: mocks.del },
}));
vi.mock('../hooks/useWriteAccess', () => ({
  default: () => ({ canWrite: true, isAllowed: () => true, requireWrite: () => true }),
}));
vi.mock('../i18n', () => ({
  useTranslation: () => ({
    t: key => key === 'ui.buttons.retry' ? 'retry' : key === 'ui.table.loading' ? 'loading' : key,
  }),
}));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: mocks.invalidateRelated }),
  useEntities: (_key, path) => {
    const source = mocks.entities[path] || {};
    return {
      items: source.items || [],
      loading: Boolean(source.loading),
      error: source.error || null,
      reload: source.reload || vi.fn(),
    };
  },
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../components/StatusBadge', () => ({ default: ({ status, label }) => <span>{label || status}</span> }));
vi.mock('../components/FormModal', () => ({ default: () => <div role="dialog" /> }));
vi.mock('../components/DataTable', () => ({
  default: ({ title, data }) => (
    <section aria-label={title || 'table'}>
      <output data-testid="row-count">{data.length}</output>
    </section>
  ),
}));

const unit = { id: 'unit-1', label: 'Wohnung 1', name: 'Wohnung 1' };
const lead = { id: 'lead-1', full_name: 'Alex Beispiel', status: 'new', unit_id: 'unit-1', priority: 1 };
const listing = { id: 'listing-1', title: 'Wohnung im Park', unit_id: 'unit-1', status: 'active' };
const viewing = { id: 'viewing-1', lead_id: 'lead-1', unit_id: 'unit-1', scheduled_at: '2026-10-05T10:00:00', status: 'scheduled' };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.failed = new Set();
  mocks.data = {
    '/contacts': [{ id: 'contact-1', first_name: 'Ada', last_name: 'Beispiel', contact_type: 'tenant' }],
    '/handover-protocols': [{ id: 'handover-1', unit_id: 'unit-1', contract_id: 'contract-1', protocol_type: 'move_in', protocol_date: '2026-10-01', status: 'draft' }],
    '/leads': [lead],
    '/units': [unit],
    '/listings': [listing],
    '/viewings': [viewing],
  };
  mocks.entities = {
    '/units': { items: [unit], reload: vi.fn() },
    '/contracts': { items: [{ id: 'contract-1', contract_number: 'MV-1' }], reload: vi.fn() },
    '/leads': { items: [lead], reload: vi.fn() },
  };
  mocks.get.mockImplementation(async path => {
    if (mocks.failed.has(path)) throw new Error(`Load failed: ${path}`);
    return mocks.data[path] || [];
  });
  mocks.post.mockResolvedValue({});
  mocks.put.mockResolvedValue({});
  mocks.del.mockResolvedValue(null);
  mocks.confirm.mockResolvedValue(true);
});

const primaryCases = [
  // Contacts now has a cursor source, actor binding and independent totals;
  // ContactInventory.test.jsx exercises that actual contract and its retry.
  ['HandoverProtocols', HandoverProtocols, '/handover-protocols', 'Übergabeprotokolle'],
  ['Leads', Leads, '/leads', 'Interessenten'],
  ['Listings', Listings, '/listings', 'Inserate'],
];

describe.each(primaryCases)('%s load state', (_name, Page, path, successLabel) => {
  it('keeps a failed primary request distinct from an empty result and recovers via retry', async () => {
    mocks.failed.add(path);
    render(<Page />);

    expect(await screen.findByRole('alert')).toHaveTextContent(`Load failed: ${path}`);
    expect(screen.queryByTestId('row-count')).not.toBeInTheDocument();

    mocks.failed.delete(path);
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));

    await waitFor(() => expect(screen.getByRole('region', { name: successLabel })).toBeInTheDocument());
    expect(screen.getByTestId('row-count')).toHaveTextContent('1');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('Viewings load state', () => {
  it('does not turn a failed viewing load into an empty calendar and recovers via retry', async () => {
    mocks.failed.add('/viewings');
    render(<Viewings />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Load failed: /viewings');
    expect(screen.queryByRole('heading', { name: 'Besichtigungen' })).not.toBeInTheDocument();

    mocks.failed.delete('/viewings');
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));

    expect(await screen.findByRole('heading', { name: 'Besichtigungen' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('reference failures', () => {
  it('does not publish leads with an incomplete units reference set', async () => {
    mocks.failed.add('/units');
    render(<Leads />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Load failed: /units');
    expect(screen.queryByTestId('row-count')).not.toBeInTheDocument();
  });

  it.each([
    ['HandoverProtocols', HandoverProtocols, '/contracts', 'Contracts unavailable'],
    ['Listings', Listings, '/units', 'Units unavailable'],
    ['Viewings', Viewings, '/leads', 'Leads unavailable'],
  ])('%s exposes a failed cached reference source', async (_name, Page, path, message) => {
    mocks.entities[path] = { ...mocks.entities[path], error: new Error(message), reload: vi.fn() };
    render(<Page />);
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByTestId('row-count')).not.toBeInTheDocument();
  });
});
