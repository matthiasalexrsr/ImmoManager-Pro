import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Receivables from '../pages/Receivables';

const mocks = vi.hoisted(() => ({
  getAll: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), confirm: vi.fn(),
  invalidateRelated: vi.fn(), readonly: false,
}));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isReadonly: mocks.readonly }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => mocks }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('../components/DataTable', () => ({ default: ({ data, onAdd, onEdit, onDelete }) => (
  <section aria-label="Receivables">
    {onAdd && <button onClick={onAdd}>Create receivable</button>}
    {data.map(row => <div key={row.id}>
      <output data-testid="receivable">{row.contract_label}: {row.status}; {row.amount_paid}</output>
      {onEdit && <button onClick={() => onEdit(row)}>Edit receivable</button>}
      {onDelete && <button onClick={() => onDelete(row)}>Delete receivable</button>}
    </div>)}
  </section>
) }));

const baseRow = { id: 'receivable', contract_id: 'contract', amount_due: 100,
  amount_paid: 40, due_date: '2026-01-10', status: 'partial', description: 'Original',
  statement_id: 'statement' };
let row;
beforeEach(() => {
  row = { ...baseRow };
  mocks.readonly = false;
  mocks.getAll.mockReset().mockImplementation(async path => path === '/contracts'
    ? [{ id: 'contract', contract_number: 'MV-1' }] : [{ ...row }]);
  for (const method of ['post', 'put', 'del']) mocks[method].mockReset().mockResolvedValue({});
  mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.invalidateRelated.mockClear();
});
async function edit() {
  fireEvent.click(await screen.findByRole('button', { name: 'Edit receivable' }));
  return screen.getByRole('dialog');
}
const submit = dialog => fireEvent.submit(dialog.querySelector('form'));

describe('Receivables receipt-managed controls', () => {
  it('shows readonly balances without create, edit, delete or payment actions', async () => {
    mocks.readonly = true;
    render(<Receivables />);
    expect(await screen.findByTestId('receivable')).toHaveTextContent('MV-1: partial; 40');
    for (const name of ['Create receivable', 'Edit receivable', 'Delete receivable']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'pages.receivables.openRentOverview' })).toHaveAttribute('href', '/rent-overview');
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.del).not.toHaveBeenCalled();
  });

  it.each(['open', 'partial', 'paid', 'overdue', 'cancelled'])('preserves existing %s status when editing non-payment fields', async status => {
    row.status = status;
    render(<Receivables />);
    const dialog = await edit();
    expect(within(dialog).queryByRole('option', { name: 'status.payment.paid' })).not.toBeInTheDocument();
    expect(dialog.querySelector('#form-field-status')).toBeNull();
    expect(dialog.querySelector('#form-field-amount_paid')).toBeNull();
    fireEvent.change(within(dialog).getByLabelText('ui.form.description'), { target: { value: 'Updated' } });
    submit(dialog);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/receivables/receivable', {
      contract_id: 'contract', amount_due: 100, due_date: '2026-01-10',
      description: 'Updated', status, statement_id: 'statement',
    }));
    expect(mocks.put.mock.calls[0][1]).not.toHaveProperty('amount_paid');
    expect(mocks.post).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('creates an open receivable with no payment balance or paid-status control', async () => {
    render(<Receivables />);
    fireEvent.click(await screen.findByRole('button', { name: 'Create receivable' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(dialog.querySelector('#form-field-contract_id'), { target: { value: 'contract' } });
    fireEvent.change(dialog.querySelector('#form-field-amount_due'), { target: { value: '125.50' } });
    fireEvent.change(dialog.querySelector('#form-field-due_date'), { target: { value: '2026-03-01' } });
    expect(dialog.querySelector('#form-field-status')).toBeNull();
    submit(dialog);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/receivables', {
      contract_id: 'contract', amount_due: 125.50, due_date: '2026-03-01', description: null, status: 'open',
    }));
    expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('amount_paid');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('retains edits and displays backend rejection without faking a payment', async () => {
    mocks.put.mockRejectedValueOnce(new Error('Receipt-backed balance cannot be changed'));
    render(<Receivables />);
    const dialog = await edit();
    fireEvent.change(within(dialog).getByLabelText('ui.form.description'), { target: { value: 'Keep draft' } });
    submit(dialog);
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Receipt-backed balance');
    expect(within(dialog).getByLabelText('ui.form.description')).toHaveValue('Keep draft');
    expect(mocks.put.mock.calls[0][1].status).toBe('partial');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('closes an open edit when the current user becomes readonly', async () => {
    const view = render(<Receivables />);
    await edit();
    mocks.readonly = true;
    view.rerender(<Receivables />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    mocks.readonly = false;
    view.rerender(<Receivables />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not delete after readonly access replaces a pending confirmation', async () => {
    let confirm;
    mocks.confirm.mockReturnValue(new Promise(resolve => { confirm = resolve; }));
    const view = render(<Receivables />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete receivable' }));
    mocks.readonly = true;
    view.rerender(<Receivables />);
    confirm(true);
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(1));
    expect(mocks.del).not.toHaveBeenCalled();
  });
});
