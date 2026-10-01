import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { I18nProvider } from '../i18n';
import Accounts from '../pages/Accounts';
import Bookings from '../pages/Bookings';
import Insurances from '../pages/Insurances';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: 'eigentuemer' }) }));
vi.mock('../api', () => ({ api: { getAll: vi.fn(async () => []) } }));
const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const lookup = (messages, key) => key.split('.').reduce((value, part) => value?.[part], messages);
const pages = ['Accounts', 'Bookings', 'Invoices', 'Receivables', 'RentCharges',
  'RentAdjustments', 'Budgets', 'Deposits', 'AllocationKeys', 'Categories',
  'TaxRates', 'Insurances', 'Meters', 'Statements'];
const components = ['FinanceCrudPage', 'FinanceLoadState', 'FormModal', 'DataTable'];
const sources = [
  ...pages.map(name => `../pages/${name}.jsx`),
  ...components.map(name => `../components/${name}.jsx`),
].map(path => readFileSync(new URL(path, import.meta.url), 'utf8'));
const requiredKeys = [...new Set(sources.flatMap(source =>
  [...source.matchAll(/\b(?:t|tr)\(\s*['"]([A-Za-z][A-Za-z0-9_.]*)['"]/g)].map(match => match[1])))];

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true,
    json: async () => catalogs[String(url).split('/').at(-1)] || {} })));
});

describe.each(Object.entries(catalogs))('finance translations in %s', (locale, messages) => {
  it('resolves every literal label used by finance pages and their shared controls', () => {
    const missing = requiredKeys.filter(key => {
      const label = lookup(messages, key);
      return typeof label !== 'string' || !label.trim() || label === key;
    });
    expect(missing).toEqual([]);
  });

  it.each([
    ['Accounts', Accounts, 'finance.accounts.form.name', 'finance.accounts.types.checking'],
    ['Bookings', Bookings, 'finance.bookings.form.bookingDate', 'finance.bookings.statusOptions.matched'],
    ['Insurances', Insurances, 'pages.insurances.form.contactPhone', 'pages.insurances.types.building'],
  ])('renders %s form labels and options with the real translation provider', async (...scenario) => {
    const [, Page, labelKey, optionKey] = scenario;
    localStorage.setItem('locale', locale);
    render(<I18nProvider><Page /></I18nProvider>);
    fireEvent.click(await screen.findByRole('button', { name: lookup(messages, 'ui.buttons.new'), exact: true }));
    const dialog = screen.getByRole('dialog');
    const label = lookup(messages, labelKey);
    expect(typeof label, labelKey).toBe('string');
    expect(within(dialog).getByLabelText(label, { exact: false })).toBeInTheDocument();
    expect(within(dialog).getByRole('option', { name: lookup(messages, optionKey), exact: true })).toBeInTheDocument();
    const visible = [dialog.textContent, ...[...dialog.querySelectorAll('[aria-label], [placeholder], [title]')]
      .flatMap(node => ['aria-label', 'placeholder', 'title'].map(attr => node.getAttribute(attr) || ''))].join(' ');
    expect(visible).not.toMatch(/\b(?:finance|portfolio|units|ui|pages)\.[A-Za-z][\w.]*/);
  });
});
