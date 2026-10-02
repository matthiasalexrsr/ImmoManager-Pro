import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Contracts from '../pages/Contracts';
import de from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), canWrite: true, lifecycleProps: null,
}));
vi.mock('../api', () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../hooks/useWriteAccess', () => ({ default: () => ({
  canWrite: mocks.canWrite, isAllowed: () => mocks.canWrite,
  requireWrite: () => { if (!mocks.canWrite) throw new Error('denied'); },
}) }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: vi.fn() }),
  useEntities: kind => ({
    items: kind === 'properties' ? [{ id: 'property-1', name: 'Synthetic property' }]
      : kind === 'units' ? [{ id: 'unit-1', label: 'A', cold_rent: '600.00' }]
        : [{ id: 'tenant-1', full_name: 'Synthetic tenant' }],
  }),
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({
  t: (key, params) => {
    let value = key.split('.').reduce((node, part) => node?.[part], de) || key;
    if (params && typeof value === 'string') {
      for (const [name, replacement] of Object.entries(params)) value = value.replaceAll(`{{${name}}}`, String(replacement));
    }
    return value;
  },
}) }));
vi.mock('../components/DataTable', () => ({ default: props => {
  const lifecycle = props.columns.find(column => column.key === 'lifecycle');
  return <div>
    <span data-testid="edit-enabled">{String(Boolean(props.onEdit))}</span>
    <span data-testid="delete-enabled">{String(Boolean(props.onDelete))}</span>
    {props.data.map(row => <div key={row.id}>{lifecycle.render(undefined, row)}</div>)}
  </div>;
} }));
vi.mock('../components/ContractLifecycle', () => ({ default: props => {
  mocks.lifecycleProps = props;
  return <div role="dialog" aria-label="Synthetic lifecycle">
    <span>{props.contract.contract_number}</span>
    <input aria-label="Synthetic selected draft" defaultValue="" />
    <button type="button" onClick={props.onChanged}>Refresh contract rows</button>
    <button type="button" onClick={props.onClose}>Close lifecycle</button>
  </div>;
} }));

const row = {
  id: 'contract-1', contract_number: 'MV-1', property_id: 'property-1', unit_id: 'unit-1',
  tenant_id: 'tenant-1', start_date: '2026-01-01', end_date: '2026-12-31',
  status: 'active', updated_at: '2026-10-01T10:00:00',
};

beforeEach(() => {
  vi.clearAllMocks(); mocks.canWrite = true; mocks.lifecycleProps = null;
  mocks.get.mockResolvedValue([row]);
});

describe('contracts lifecycle row hook', () => {
  it('retains the open workflow and its selected draft during and after a real parent list refresh', async () => {
    render(<Contracts />);
    fireEvent.click(await screen.findByRole('button', { name: de.contractLifecycle.open }));
    const dialog = screen.getByRole('dialog', { name: 'Synthetic lifecycle' });
    fireEvent.change(screen.getByLabelText('Synthetic selected draft'), { target: { value: 'draft-created-on-server' } });
    let completeRefresh;
    mocks.get.mockReturnValueOnce(new Promise(resolve => { completeRefresh = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh contract rows' }));
    expect(screen.getByRole('dialog', { name: 'Synthetic lifecycle' })).toBe(dialog);
    expect(screen.getByLabelText('Synthetic selected draft')).toHaveValue('draft-created-on-server');
    await act(async () => completeRefresh([{ ...row, updated_at: '2026-10-02T12:00:00' }]));
    expect(screen.getByRole('dialog', { name: 'Synthetic lifecycle' })).toBe(dialog);
    expect(screen.getByLabelText('Synthetic selected draft')).toHaveValue('draft-created-on-server');
  });

  it('opens the scoped lifecycle dialog with the exact contract row without changing CRUD actions', async () => {
    render(<Contracts />);
    const open = await screen.findByRole('button', { name: de.contractLifecycle.open });
    expect(screen.getByTestId('edit-enabled')).toHaveTextContent('true');
    expect(screen.getByTestId('delete-enabled')).toHaveTextContent('true');

    fireEvent.click(open);
    expect(await screen.findByRole('dialog', { name: 'Synthetic lifecycle' })).toBeInTheDocument();
    expect(mocks.lifecycleProps.contract.id).toBe('contract-1');
    expect(mocks.lifecycleProps.contract.contract_number).toBe('MV-1');

    fireEvent.click(screen.getByRole('button', { name: 'Close lifecycle' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Synthetic lifecycle' })).not.toBeInTheDocument());
  });

  it('keeps lifecycle/history access visible for readonly while ordinary CRUD stays disabled', async () => {
    mocks.canWrite = false;
    render(<Contracts />);
    const open = await screen.findByRole('button', { name: de.contractLifecycle.open });
    expect(screen.getByTestId('edit-enabled')).toHaveTextContent('false');
    expect(screen.getByTestId('delete-enabled')).toHaveTextContent('false');
    fireEvent.click(open);
    expect(await screen.findByText('MV-1')).toBeInTheDocument();
  });
});
