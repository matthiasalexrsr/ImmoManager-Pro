import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { I18nProvider } from '../i18n';
import RentCharges from '../pages/RentCharges';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ getAll: vi.fn(), put: vi.fn(), post: vi.fn(), readonly: false }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isReadonly: mocks.readonly }) }));
const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const lookup = (messages, key) => key.split('.').reduce((value, part) => value?.[part], messages);
const charge = { id: 'charge', contract_id: 'contract', month: '2026-01', cold_rent: 500,
  service_charge: 50, heating_charge: 30, other_charges: 5, amount_paid: 100, status: 'partial' };
beforeEach(() => {
  localStorage.clear();
  mocks.readonly = false;
  mocks.getAll.mockReset().mockImplementation(async path => path === '/contracts'
    ? [{ id: 'contract', contract_number: 'MV-1', status: 'active' }] : [{ ...charge }]);
  mocks.put.mockReset().mockResolvedValue({});
  mocks.post.mockReset();
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true,
    json: async () => catalogs[String(url).split('/').at(-1)] || {} })));
});
const expected = {
  'de-DE': { title: 'Sollstellungen', edit: 'Sollstellung bearbeiten', create: 'Sollstellung erstellen', month: 'Monat (JJJJ-MM)' },
  'en-US': { title: 'Rent charges', edit: 'Edit rent charge', create: 'Create rent charge', month: 'Month (YYYY-MM)' },
  'es-ES': { title: 'Cargos de alquiler', edit: 'Editar cargo de alquiler', create: 'Crear cargo de alquiler', month: 'Mes (AAAA-MM)' },
};

describe.each(Object.entries(catalogs))('RentCharges labels in %s', (locale, messages) => {
  const t = key => lookup(messages, key);
  it('renders translated columns and edit fields without changing receipt-backed values', async () => {
    localStorage.setItem('locale', locale);
    render(<I18nProvider><RentCharges /></I18nProvider>);
    await screen.findByRole('heading', { name: expected[locale].title, exact: true });
    for (const key of ['month', 'coldRent', 'serviceCharge', 'heatingCharge', 'otherCharges', 'totalDue', 'paid', 'remaining']) {
      const label = t(`pages.rentCharges.columns.${key}`);
      expect(label).toEqual(expect.any(String));
      expect(screen.getByRole('columnheader', { name: label, exact: false })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole('button', { name: t('ui.buttons.edit'), exact: true }));
    const dialog = screen.getByRole('dialog', { name: expected[locale].edit });
    expect(within(dialog).getByLabelText(expected[locale].month, { exact: false })).toHaveValue('2026-01');
    for (const key of ['coldRent', 'serviceCharge', 'heatingCharge', 'otherCharges']) {
      expect(within(dialog).getByLabelText(t(`pages.rentCharges.form.${key}`), { exact: false })).toBeInTheDocument();
    }
    expect(dialog.querySelector('[name="status"]')).toBeNull();
    expect(dialog.querySelector('[name="amount_paid"]')).toBeNull();
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/rent-charges/charge', {
      contract_id: 'contract', month: '2026-01', cold_rent: 500, service_charge: 50,
      heating_charge: 30, other_charges: 5, amount_paid: 100, status: 'partial',
    }));
    expect(mocks.post).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('keeps manual creation and the existing monthly generator separate', async () => {
    localStorage.setItem('locale', locale);
    render(<I18nProvider><RentCharges /></I18nProvider>);
    fireEvent.click(await screen.findByRole('button', { name: t('ui.buttons.new'), exact: true }));
    expect(screen.getByRole('dialog', { name: expected[locale].create })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: t('ui.buttons.cancel'), exact: true }));
    fireEvent.click(screen.getByRole('button', { name: t('pages.rentGeneration.title'), exact: true }));
    const monthly = screen.getByRole('dialog', { name: t('pages.rentGeneration.title') });
    expect(within(monthly).getByLabelText(t('pages.rentGeneration.startMonth'), { exact: false })).toHaveAttribute('type', 'month');
    expect(within(monthly).getByLabelText(t('pages.rentGeneration.endMonth'), { exact: false })).toHaveAttribute('type', 'month');
    expect(within(monthly).getByRole('option', { name: 'MV-1' })).toHaveValue('contract');
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
