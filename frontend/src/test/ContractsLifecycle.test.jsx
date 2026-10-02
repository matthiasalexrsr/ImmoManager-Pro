import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Contracts from '../pages/Contracts';
import de from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), canWrite: true, lifecycleProps: null }));
vi.mock('../api', () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner-1', role: 'eigentuemer' } }) }));
vi.mock('../hooks/useWriteAccess', () => ({ default: () => ({
  canWrite: mocks.canWrite, isAllowed: () => mocks.canWrite,
  requireWrite: () => { if (!mocks.canWrite) throw new Error('denied'); },
}) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../i18n', () => ({ useTranslation: () => ({
  t: (key, params) => {
    let value = key.split('.').reduce((node, part) => node?.[part], de) || key;
    if (params && typeof value === 'string') {
      for (const [name, replacement] of Object.entries(params)) value = value.replaceAll(`{{${name}}}`, String(replacement));
    }
    return value;
  }, locale: 'de-DE',
}) }));
vi.mock('../components/ContractLifecycle', () => ({ default: function SyntheticLifecycle(props) {
  const [selectedDraft, setSelectedDraft] = useState('');
  mocks.lifecycleProps = props;
  return <div role="dialog" aria-label="Synthetic lifecycle">
    <span>{props.contract.contract_number}</span>
    <input aria-label="Synthetic private draft" value={selectedDraft} onChange={event => setSelectedDraft(event.target.value)} />
    <button type="button" onClick={props.onChanged}>Saved command</button>
    <button type="button" onClick={props.onClose}>Close lifecycle</button>
  </div>;
} }));

const row = {
  id: 'contract-1', contract_number: 'MV-1', property_id: 'property-1', unit_id: 'unit-1',
  tenant_id: 'tenant-1', start_date: '2026-01-01', end_date: '2026-12-31',
  status: 'active', updated_at: '2026-10-01T10:00:00.000001',
  edit_etag: '"immo-v1:contracts:contract-1:2026-10-01T10:00:00.000001Z"',
  property_name: 'Synthetic property', unit_label: 'A', tenant_name: 'Synthetic tenant',
  unit_cold_rent: 600, deposit_amount: 0,
};
const page = { items: [row], reference_date: '2026-10-01', has_more: false, next_cursor: null };
beforeEach(() => {
  vi.clearAllMocks(); mocks.canWrite = true; mocks.lifecycleProps = null;
  mocks.get.mockResolvedValue(page);
});

describe('contracts lifecycle row hook', () => {
  it('retains the same dialog and private selection across a successful delayed parent page refresh', async () => {
    render(<Contracts />);
    fireEvent.click(await screen.findByRole('button', { name: de.contractLifecycle.open }));
    const dialog = screen.getByRole('dialog', { name: 'Synthetic lifecycle' });
    fireEvent.change(screen.getByLabelText('Synthetic private draft'), { target: { value: 'draft-created-on-server' } });
    let completeRefresh;
    mocks.get.mockImplementationOnce(() => new Promise(resolve => { completeRefresh = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Saved command' }));
    await waitFor(() => expect(completeRefresh).toBeTypeOf('function'));
    expect(screen.getByRole('dialog', { name: 'Synthetic lifecycle' })).toBe(dialog);
    expect(screen.getByLabelText('Synthetic private draft')).toHaveValue('draft-created-on-server');
    await act(async () => completeRefresh({ ...page, items: [{ ...row, contract_number: 'Fresh page label' }] }));
    await screen.findByRole('button', { name: 'Bearbeiten Fresh page label' });
    expect(screen.getByRole('dialog', { name: 'Synthetic lifecycle' })).toBe(dialog);
    expect(screen.getByLabelText('Synthetic private draft')).toHaveValue('draft-created-on-server');
    expect(mocks.lifecycleProps.contract.contract_number).toBe('MV-1');
  });

  it('opens the scoped lifecycle dialog with the exact row while keeping ordinary CRUD available', async () => {
    render(<Contracts />);
    const open = await screen.findByRole('button', { name: de.contractLifecycle.open });
    expect(screen.getByRole('button', { name: 'Bearbeiten MV-1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Löschen MV-1' })).toBeInTheDocument();
    fireEvent.click(open);
    expect(await screen.findByRole('dialog', { name: 'Synthetic lifecycle' })).toBeInTheDocument();
    expect(mocks.lifecycleProps.contract.id).toBe('contract-1');
    expect(mocks.lifecycleProps.contract.edit_etag).toBe(row.edit_etag);
    fireEvent.click(screen.getByRole('button', { name: 'Close lifecycle' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Synthetic lifecycle' })).not.toBeInTheDocument());
  });

  it('keeps lifecycle/history access visible for readonly while ordinary CRUD stays unavailable', async () => {
    mocks.canWrite = false;
    render(<Contracts />);
    fireEvent.click(await screen.findByRole('button', { name: de.contractLifecycle.open }));
    expect(screen.queryByRole('button', { name: 'Bearbeiten MV-1' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Löschen MV-1' })).not.toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('preserves selected private draft across a pending and failed parent list refresh', async () => {
    let rejectRefresh;
    render(<Contracts />);
    fireEvent.click(await screen.findByRole('button', { name: de.contractLifecycle.open }));
    fireEvent.change(screen.getByLabelText('Synthetic private draft'), { target: { value: 'saved-draft-UUID / exact retry' } });
    mocks.get.mockImplementationOnce(() => new Promise((_, reject) => { rejectRefresh = reject; }));
    fireEvent.click(screen.getByRole('button', { name: 'Saved command' }));
    await waitFor(() => expect(rejectRefresh).toBeTypeOf('function'));
    expect(screen.getByLabelText('Synthetic private draft')).toHaveValue('saved-draft-UUID / exact retry');
    await act(async () => rejectRefresh(new Error('Synthetic list outage')));
    expect(screen.getByRole('alert')).toHaveTextContent('Synthetic list outage');
    expect(screen.getByLabelText('Synthetic private draft')).toHaveValue('saved-draft-UUID / exact retry');
    expect(mocks.lifecycleProps.contract.id).toBe(row.id);
    mocks.get.mockResolvedValueOnce(page);
    fireEvent.click(screen.getByRole('button', { name: de.contractWorkspace.retry }));
    await screen.findByRole('button', { name: 'Bearbeiten MV-1' });
    expect(screen.getByLabelText('Synthetic private draft')).toHaveValue('saved-draft-UUID / exact retry');
  });
});
