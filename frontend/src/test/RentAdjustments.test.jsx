import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import RentAdjustments from '../pages/RentAdjustments';
import german from '../../../i18n/de-DE.json';
import english from '../../../i18n/en-US.json';
import spanish from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ getAll: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), confirm: vi.fn(),
  invalidateRelated: vi.fn(), readonly: false, locale: 'de-DE', translations: null }));
vi.mock('../api', () => ({ api: { ...mocks,
  get: vi.fn(async () => ({ draft: null })),
  put: (path, data) => path === '/auth/users/me/form-drafts'
    ? Promise.resolve({ revision: '00000000-0000-4000-8000-000000000001', updated_at: '2026-01-01T00:00:00Z', expires_at: '2026-01-08T00:00:00Z' }) : mocks.put(path, data),
  del: path => path.startsWith('/auth/users/me/form-drafts') ? Promise.resolve({ discarded: true }) : mocks.del(path),
} }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isReadonly: mocks.readonly, user: { id: 'synthetic-owner', role: mocks.readonly ? 'readonly' : 'eigentuemer' } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => mocks }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: key => key.split('.').reduce((value, part) => value?.[part], mocks.translations) || key }) }));

const record = { id: 'adjustment', contract_id: 'contract', adjustment_type: 'stepped', effective_date: '2025-02-01',
  previous_rent: 500, new_rent: 600.30, status: 'applied', notes: 'Synthetic fixture', updated_at: '2026-01-01T00:00:00.123456Z' };
beforeEach(() => {
  mocks.readonly = false; mocks.locale = 'de-DE'; mocks.translations = german;
  mocks.getAll.mockReset().mockImplementation(async path => path === '/contracts'
    ? [{ id: 'contract', contract_number: 'V-Synthetic' }] : [structuredClone(record)]);
  mocks.post.mockReset().mockResolvedValue(record);
  mocks.put.mockReset().mockResolvedValue(record);
  mocks.del.mockReset().mockResolvedValue(undefined);
  mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.invalidateRelated.mockReset();
});
const openEdit = async () => {
  render(<RentAdjustments />);
  await screen.findByText('V-Synthetic');
  fireEvent.click(screen.getByRole('button', { name: german.ui.buttons.edit }));
  await screen.findByText(german.formDraft.status.ready);
  return screen.getByRole('dialog');
};

it('submits contract-specific applied prices with cents and refreshes monthly charges too', async () => {
  const dialog = await openEdit();
  expect(screen.getByRole('note')).toHaveTextContent(german.pages.rentAdjustments.policy);
  expect(within(dialog).getByLabelText(/Neue Kaltmiete/)).toHaveAttribute('min', '0');
  expect(within(dialog).getByLabelText(/Neue Kaltmiete/)).toHaveAttribute('step', '0.01');
  expect(within(dialog).getByLabelText(/Status/)).toBeRequired();
  fireEvent.change(within(dialog).getByLabelText(/Neue Kaltmiete/), { target: { value: '650.45' } });
  fireEvent.click(within(dialog).getByRole('button', { name: german.ui.buttons.save }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/rent-adjustments/adjustment', expect.objectContaining({
    contract_id: 'contract', status: 'applied', effective_date: '2025-02-01', previous_rent: 500, new_rent: 650.45,
  })));
  await waitFor(() => expect(mocks.invalidateRelated).toHaveBeenCalledWith('rent_adjustments', 'contracts', 'rent_charges'));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

it('keeps the submitted draft and displays a conflicting effective-date response', async () => {
  mocks.put.mockRejectedValueOnce(Object.assign(new Error('Angewendete Anpassung für dieses Datum existiert bereits.'), { statusCode: 409 }));
  const dialog = await openEdit();
  fireEvent.change(within(dialog).getByLabelText(/Neue Kaltmiete/), { target: { value: '650.45' } });
  fireEvent.click(within(dialog).getByRole('button', { name: german.ui.buttons.save }));
  await within(dialog).findByRole('alert');
  expect(within(dialog).getByRole('alert')).toHaveTextContent('für dieses Datum existiert bereits');
  expect(within(dialog).getByLabelText(/Neue Kaltmiete/)).toHaveValue(650.45);
  expect(mocks.invalidateRelated).not.toHaveBeenCalled();
});

it('exposes no mutation controls for readonly users while keeping prices visible', async () => {
  mocks.readonly = true;
  render(<RentAdjustments />);
  await screen.findByText('V-Synthetic');
  expect(screen.getByText(/600,30\s*€/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: german.ui.buttons.edit })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: german.ui.buttons.delete })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: german.ui.buttons.new })).not.toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalled();
});

it('does not open a second confirmation or send a second deletion during a pending operation', async () => {
  let accept;
  mocks.confirm.mockImplementation(() => new Promise(resolve => { accept = resolve; }));
  render(<RentAdjustments />);
  await screen.findByText('V-Synthetic');
  const remove = screen.getByRole('button', { name: german.ui.buttons.delete });
  fireEvent.click(remove); fireEvent.click(remove);
  expect(mocks.confirm).toHaveBeenCalledTimes(1);
  expect(mocks.del).not.toHaveBeenCalled();
  await act(async () => { accept(true); });
  await waitFor(() => expect(mocks.del).toHaveBeenCalledTimes(1));
});

it.each([['en-US', english], ['es-ES', spanish]])('localizes the applied rule and retains drafts when switching to %s', async (locale, translations) => {
  const { rerender } = render(<RentAdjustments />);
  await screen.findByText('V-Synthetic');
  fireEvent.click(screen.getByRole('button', { name: german.ui.buttons.edit }));
  fireEvent.change(screen.getByLabelText(/Neue Kaltmiete/), { target: { value: '720.55' } });
  mocks.locale = locale; mocks.translations = translations;
  rerender(<RentAdjustments />);
  expect(screen.getByRole('note')).toHaveTextContent(translations.pages.rentAdjustments.policy);
  expect(screen.getByLabelText(`${translations.pages.rentAdjustments.newRent} *`)).toHaveValue(720.55);
  expect(screen.getByRole('combobox', { name: `${translations.pages.rentAdjustments.status} *` })).toHaveValue('applied');
  expect(within(screen.getByRole('dialog')).getByRole('option', { name: translations.pages.rentAdjustments.applied })).toBeInTheDocument();
});
