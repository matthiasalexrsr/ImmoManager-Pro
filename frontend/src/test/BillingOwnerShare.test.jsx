import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import BillingOwnerShare from '../components/BillingOwnerShare';
import { ownerPeriod } from './fixtures/ownerShare';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';
const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
const view = (periodId = 'period', refreshKey = '') => <I18nProvider>
  <BillingOwnerShare periodId={periodId} refreshKey={refreshKey} units={{ vacant: { label: 'Vacant apartment' } }} />
</I18nProvider>;
beforeEach(() => {
  localStorage.clear();
  mocks.get.mockReset().mockResolvedValue(ownerPeriod());
  mocks.post.mockReset();
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true,
    json: async () => catalogs[String(url).split('/').at(-1)] || {} })));
});
describe.each(Object.entries(catalogs))('saved owner allocation in %s', (locale, catalog) => {
  it('displays separate owner and tenant shares without any posting controls', async () => {
    localStorage.setItem('locale', locale);
    render(view());
    const labels = catalog.pages.statements.ownerShare;
    const section = await screen.findByRole('region', { name: labels.title });
    await within(section).findByText(labels.snapshotHelp);
    expect(section).toHaveTextContent(labels.notTenantDebt);
    for (const [key, amount] of [['total', 120], ['vacancy', 50], ['nonRecoverable', 70], ['propertyCosts', 170], ['tenantCosts', 50]]) {
      const money = new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(amount).replace(/\u00a0/g, ' ');
      expect(within(section).getByText(labels[key], { selector: '.stat-label' }).parentElement).toHaveTextContent(money);
    }
    expect(within(section).getByRole('heading', { name: labels.vacantDays })).toBeInTheDocument();
    expect(section).toHaveTextContent('31');
    expect(section.querySelectorAll('a')).toHaveLength(0);
    expect(within(section).queryByRole('button', { name: /verbuchen|post|contabilizar/i })).not.toBeInTheDocument();
    expect(section.textContent).not.toMatch(/pages\.statements\./);
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
describe('owner snapshot reads', () => {
  it('treats a failed period GET as an error, not zero owner cost', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Period unavailable'));
    const { container } = render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('Period unavailable');
    expect(container.querySelector('.stats-grid')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: de.ui.buttons.retry }));
    await screen.findByText(de.pages.statements.ownerShare.snapshotHelp);
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.get).toHaveBeenLastCalledWith('/billing/periods/period', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it('shows not calculated for a real null snapshot', async () => {
    mocks.get.mockResolvedValue({ id: 'period', owner_cost_share: null });
    const { container } = render(view());
    await screen.findByText(de.pages.statements.ownerShare.notCalculated);
    expect(container.querySelector('.stats-grid')).toBeNull();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('refuses partial or mismatched period data', async () => {
    mocks.get.mockResolvedValue(ownerPeriod('other'));
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent(de.pages.statements.ownerShare.invalidResponse);
  });
  it('refetches the saved period after generated statement IDs change', async () => {
    mocks.get.mockResolvedValueOnce({ id: 'period', owner_cost_share: null });
    const page = render(view());
    await screen.findByText(de.pages.statements.ownerShare.notCalculated);
    page.rerender(view('period', 'new-statement'));
    await screen.findByText(de.pages.statements.ownerShare.snapshotHelp);
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });
  it('ignores a late response from a previously selected period', async () => {
    let resolve;
    mocks.get.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const page = render(view());
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    page.rerender(view('second'));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    expect(mocks.get.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => resolve(ownerPeriod()));
    expect(screen.queryByText(de.pages.statements.ownerShare.snapshotHelp)).not.toBeInTheDocument();
  });
});
