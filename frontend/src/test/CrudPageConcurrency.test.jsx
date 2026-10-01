import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import CrudPage from '../pages/CrudPage';
import { EDIT_REVISION } from '../editRevision';
import german from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ state: null, role: 'eigentuemer', put: vi.fn(), del: vi.fn(), reload: vi.fn() }));
vi.mock('../api', () => ({ api: { put: mocks.put, del: mocks.del } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isReadonly: mocks.role === 'readonly', canWrite: () => mocks.role !== 'readonly' }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: () => ({ ...mocks.state, reload: mocks.reload }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));
vi.mock('../components/DataTable', () => ({ default: ({ data, onAdd, onEdit, onDelete }) => <div>
  {onAdd && <button onClick={onAdd}>Create</button>}
  {data.map(row => <div key={row.id}><span>{row.name}</span>
    {onEdit && <button onClick={() => onEdit(row)}>Edit {row.name}</button>}
    {onDelete && <button onClick={() => onDelete(row)}>Delete {row.name}</button>}
  </div>)}
</div> }));
const old = { id: 'property-1', name: 'Original', updated_at: '2026-10-01T08:00:00.123456' };
const props = { title: 'Immobilien', endpoint: '/properties', columns: [{ key: 'name', label: 'Name' }], formFields: [{ key: 'name', label: 'Name', required: true }] };
beforeEach(() => {
  mocks.role = 'eigentuemer'; mocks.state = { items: [old], loading: false, error: null };
  mocks.put.mockReset(); mocks.del.mockReset(); mocks.reload.mockReset();
});

it('keeps the open draft mounted through list loading/errors and saves its original version', async () => {
  mocks.put.mockRejectedValue(new Error('Nicht gespeichert'));
  const { rerender } = render(<CrudPage {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit Original' }));
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Mein Entwurf' } });
  mocks.state = { items: [], loading: true, error: null }; rerender(<CrudPage {...props} />);
  expect(screen.getByLabelText('Name *')).toHaveValue('Mein Entwurf');
  mocks.state = { items: [], loading: false, error: 'Listenabruf fehlgeschlagen' }; rerender(<CrudPage {...props} />);
  expect(screen.getByLabelText('Name *')).toHaveValue('Mein Entwurf');
  fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
  expect(mocks.reload).toHaveBeenCalledTimes(1);
  fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
  await screen.findByText('Nicht gespeichert');
  expect(mocks.put.mock.calls[0][0]).toBe('/properties/property-1');
  expect(mocks.put.mock.calls[0][1][EDIT_REVISION].updatedAt).toBe(old.updated_at);
});

it('deletion uses the snapshot from the clicked row and preserves a conflict error', async () => {
  mocks.del.mockRejectedValue(new Error('Zwischenzeitlich geändert'));
  render(<CrudPage {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Delete Original' }));
  await screen.findByText('Zwischenzeitlich geändert');
  expect(mocks.del).toHaveBeenCalledWith('/properties/property-1', { ifMatch: expect.objectContaining({ id: old.id, updatedAt: old.updated_at }) });
  expect(mocks.reload).not.toHaveBeenCalled();
});

it('a refreshed list does not renew the revision or change the draft of the open record', async () => {
  mocks.put.mockRejectedValue(new Error('Konflikt'));
  const { rerender } = render(<CrudPage {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit Original' }));
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Entwurf B' } });
  mocks.state = { items: [{ ...old, name: 'Server A', updated_at: '2026-10-01T09:00:00.654321' }], loading: false, error: null };
  rerender(<CrudPage {...props} />);
  expect(screen.getByLabelText('Name *')).toHaveValue('Entwurf B');
  fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
  await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
  expect(mocks.put.mock.calls[0][1][EDIT_REVISION].updatedAt).toBe(old.updated_at);
});

it('read-only users have no general CRUD mutation controls', () => {
  mocks.role = 'readonly';
  render(<CrudPage {...props} />);
  expect(screen.getByText('Original')).toBeVisible();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(mocks.put).not.toHaveBeenCalled();
  expect(mocks.del).not.toHaveBeenCalled();
});
