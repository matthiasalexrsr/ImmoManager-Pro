import { webcrypto } from 'node:crypto';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AnnualTaxPage from '../pages/AnnualTaxPage';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), getBlob: vi.fn(), confirm: vi.fn(), role: 'buchhaltung', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-user', role: mocks.role, full_name: 'Synthetic reviewer' } }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: key => key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key }) }));

const text = de.pages.annualTax;
const profile = () => ({ id: 'version', created_at: '2025-02-01', tax_year: 2024, spec: { name: 'Synthetic reviewed', reviewed_by: 'Synthetic adviser', review_confirmed: true,
  rules: [{ account_id: 'account', category_id: 'category', treatment: 'income', form_line: 'User reviewed line', reason: 'Explicit review', exclusion_kind: null }] } });
const preview = (changes = {}) => ({ ready: true, preview_hash: 'a'.repeat(64), source_rows: 1, confirmed_cash_rows: 1, full_year: true, tax_year: 2024, profile_version_id: 'version',
  period_start: '2024-01-01', period_end: '2024-12-31', cash_totals_complete: true, tax_totals_complete: true,
  totals: { cash_cents: '1234', income_cents: '1234', expense_cents: '0', excluded_cash_cents: '0', unclassified_cash_cents: '0' },
  source_samples: [{ booking: { id: 'booking', booking_date: '2024-02-01', amount_cents: '1234', account_name: 'Synthetic Giro', category_name: 'Synthetic Rent', property_id: 'property', status: 'confirmed', payment_text: 'Cash evidence' }, errors: [], parts: [] }],
  groups: [{ property_name: 'Synthetic House', property_id: 'property', form_line: 'User reviewed line', treatment: 'income', amount_cents: '1234' }], blocking_issue_counts: {}, blocking_issues: [], ...changes });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = () => render(<MemoryRouter><AnnualTaxPage /></MemoryRouter>);
const choose = async (labels = text) => {
  await screen.findByRole('option', { name: 'Synthetic portfolio' });
  fireEvent.change(screen.getByLabelText(labels.year), { target: { value: '2024' } });
  fireEvent.change(screen.getByLabelText(labels.portfolio), { target: { value: 'portfolio' } });
  await screen.findByRole('option', { name: /Synthetic reviewed/ });
  fireEvent.change(screen.getByLabelText(labels.profile), { target: { value: 'version' } });
};
const check = () => fireEvent.click(screen.getByRole('button', { name: text.preflight }));

beforeEach(() => {
  mocks.role = 'buchhaltung'; mocks.locale = 'de-DE';
  mocks.getAll.mockReset().mockResolvedValue([{ id: 'portfolio', name: 'Synthetic portfolio' }, { id: 'other', name: 'Other portfolio' }]);
  mocks.get.mockReset().mockImplementation(async path => path.includes('/options?')
    ? { accounts: [{ id: 'account', name: 'Synthetic Giro' }], categories: [{ id: 'category', name: 'Synthetic Rent' }], properties: [{ id: 'property', name: 'Synthetic House' }, { id: 'property2', name: 'Synthetic Other' }] }
    : path.includes('/profiles?') ? { total: 1, items: [profile()] } : { total: 0, items: [] });
  mocks.post.mockReset().mockResolvedValue(preview()); mocks.getBlob.mockReset(); mocks.confirm.mockReset().mockResolvedValue(true);
  vi.stubGlobal('crypto', webcrypto); URL.createObjectURL = vi.fn().mockReturnValue('blob:synthetic'); URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

describe('reviewed annual tax preparation', () => {
  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('uses actual source boundaries and translated controls in %s', async (locale, catalog) => {
    mocks.locale = locale; const labels = catalog.pages.annualTax;
    const { container } = view(); await choose(labels);
    expect(container).toHaveTextContent(labels.cashBasis); expect(container).toHaveTextContent(labels.boundary);
    expect(container.textContent).not.toMatch(/pages\.annualTax\.|finance\.tax/);
    expect(screen.getByRole('button', { name: labels.newProfile })).toBeEnabled();
    expect(mocks.get.mock.calls.some(([path]) => path.includes('tax_year=2024'))).toBe(true);
  });

  it('shows source errors independently, retries and never displays a false empty journal', async () => {
    const fallback = mocks.get.getMockImplementation(); let fail = true;
    mocks.get.mockImplementation(path => path.includes('/projections?') && fail ? Promise.reject(new Error('Actual journal unavailable')) : fallback(path));
    view(); await choose();
    const alert = await screen.findByRole('alert'); expect(alert).toHaveTextContent('Actual journal unavailable');
    expect(screen.queryByText(text.noSnapshots)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: text.preflight })).toBeEnabled();
    fail = false; fireEvent.click(within(alert).getByRole('button', { name: text.retry }));
    await screen.findByText(text.noSnapshots);
  });

  it('aborts an old source load and ignores a late response after portfolio change', async () => {
    const old = pending(), fallback = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(path => path.includes('/options?portfolio_id=portfolio') ? old.promise : fallback(path));
    view(); await screen.findByRole('option', { name: 'Synthetic portfolio' });
    fireEvent.change(screen.getByLabelText(text.portfolio), { target: { value: 'portfolio' } });
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    const oldOptions = mocks.get.mock.calls.find(([path]) => path.includes('/options?portfolio_id=portfolio'));
    fireEvent.change(screen.getByLabelText(text.portfolio), { target: { value: 'other' } });
    await screen.findByRole('option', { name: /Synthetic reviewed/ });
    await act(async () => old.resolve({ accounts: [], categories: [], properties: [] }));
    expect(oldOptions[1].signal.aborted).toBe(true);
    expect(screen.getByRole('button', { name: text.newProfile })).toBeEnabled();
    expect(screen.getByLabelText(text.portfolio)).toHaveValue('other');
  });

  it('keeps reviewed mapping drafts and the same idempotency key after a rejected save', async () => {
    view(); await choose(); fireEvent.click(screen.getByRole('button', { name: text.newProfile }));
    const form = screen.getByRole('button', { name: text.saveProfile }).closest('form');
    const field = (label, value) => fireEvent.change(within(form).getByLabelText(label), { target: { value } });
    field(text.name, 'Reviewed 2024 mapping'); field(text.account, 'account'); field(text.category, 'category');
    field(text.formLine, 'User confirmed line'); field(text.reason, 'Reviewed explicitly');
    fireEvent.click(within(form).getByLabelText(text.reviewConfirmed));
    mocks.post.mockRejectedValueOnce(new Error('409: Reviewed account/category already assigned'));
    fireEvent.submit(form); await screen.findByRole('alert');
    expect(within(form).getByLabelText(text.formLine)).toHaveValue('User confirmed line');
    const first = mocks.post.mock.calls[0][1];
    mocks.post.mockResolvedValueOnce({ ...profile(), id: 'new-profile' }); fireEvent.submit(form);
    await screen.findByText(text.profileSaved);
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first.idempotency_key);
    expect(first).toMatchObject({ tax_year: 2024, currency: 'EUR', review_confirmed: true });
    expect(first.rules[0]).not.toHaveProperty('key');
  });

  it('shows incomplete classified totals and blocks a snapshot without any hidden save', async () => {
    mocks.post.mockResolvedValue(preview({ ready: false, tax_totals_complete: false, blocking_issue_counts: { property_assignment_required: 1 } }));
    view(); await choose(); check();
    await screen.findByText(text.blocked); expect(screen.getByText(text.partialTotals)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.saveSnapshot })).not.toBeInTheDocument();
    expect(mocks.post.mock.calls.map(([path]) => path)).toEqual(['/reports/annual-tax/preflight']);
  });

  it('sends explicit signed split cents and exclusion evidence without floating-point conversion', async () => {
    view(); await choose(); check(); await screen.findByText(text.ready);
    fireEvent.click(screen.getByRole('button', { name: text.adjustSource }));
    const override = screen.getByRole('group', { name: `${text.adjustment} 1` });
    fireEvent.change(within(override).getByLabelText(text.overrideReason), { target: { value: 'Explicit principal and cost split' } });
    let part = within(override).getByRole('group', { name: `${text.part} 1` });
    fireEvent.change(within(part).getByLabelText(text.signedAmount), { target: { value: '-40,01' } });
    fireEvent.change(within(part).getByLabelText(text.treatment), { target: { value: 'expense' } });
    fireEvent.change(within(part).getByLabelText(text.formLine), { target: { value: 'Reviewed interest' } });
    fireEvent.change(within(part).getByLabelText(text.reason), { target: { value: 'Actual bank evidence' } });
    fireEvent.click(within(override).getByRole('button', { name: text.addPart }));
    part = within(override).getByRole('group', { name: `${text.part} 2` });
    fireEvent.change(within(part).getByLabelText(text.signedAmount), { target: { value: '-59.99' } });
    fireEvent.change(within(part).getByLabelText(text.treatment), { target: { value: 'excluded' } });
    fireEvent.change(within(part).getByLabelText(text.exclusionKind), { target: { value: 'loan_principal' } });
    fireEvent.change(within(part).getByLabelText(text.reason), { target: { value: 'Principal excluded after review' } });
    check(); await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    const body = mocks.post.mock.calls[1][1];
    expect(body.overrides[0].parts.map(row => row.amount_cents)).toEqual(['-4001', '-5999']);
    expect(body.overrides[0].parts[1]).toMatchObject({ treatment: 'excluded', form_line: null, exclusion_kind: 'loan_principal', property_id: null });
    expect(body.overrides[0].parts[0]).not.toHaveProperty('amount');
  });

  it('rejects fractional-cent input locally and keeps the original amount draft', async () => {
    view(); await choose(); fireEvent.click(screen.getByRole('button', { name: text.addAdjustment }));
    for (const [label, value] of [[text.bookingId, 'booking'], [text.overrideReason, 'Explicit review'], [text.formLine, 'Reviewed line'], [text.reason, 'Reviewed evidence'], [text.property, 'property']])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.change(screen.getByLabelText(text.signedAmount), { target: { value: '10.001' } }); check();
    await screen.findByText(text.amountInvalid); expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.getByLabelText(text.signedAmount)).toHaveValue('10.001');
  });

  it('requires explicit confirmation and invalidates it if the review is changed while pending', async () => {
    const reply = pending(); mocks.confirm.mockReturnValue(reply.promise);
    view(); await choose(); check(); await screen.findByText(text.ready);
    fireEvent.click(screen.getByRole('button', { name: text.saveSnapshot }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText(text.pendingReason), { target: { value: 'New review input' } });
    await act(async () => reply.resolve(true)); expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(text.ready)).not.toBeInTheDocument();
  });

  it('saves only after review and retains draft inputs after a source-change conflict', async () => {
    view(); await choose(); fireEvent.change(screen.getByLabelText(text.emptyReason), { target: { value: 'Reviewed source evidence' } });
    check(); await screen.findByText(text.ready);
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('annual_tax_source_changed'), { statusCode: 409 }));
    fireEvent.click(screen.getByRole('button', { name: text.saveSnapshot }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText(text.emptyReason)).toHaveValue('Reviewed source evidence');
    expect(screen.queryByRole('button', { name: text.saveSnapshot })).not.toBeInTheDocument();
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ preview_hash: 'a'.repeat(64), empty_cash_review_reason: 'Reviewed source evidence' });
  });

  it.each(['readonly', 'techniker'])('allows saved evidence but no finance commands for %s', async role => {
    mocks.role = role; const fallback = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(path => path.includes('/projections?') ? Promise.resolve({ total: 1, items: [preview({ id: 'snapshot', revision_number: 1 })] }) : fallback(path));
    view(); await choose();
    expect(screen.queryByRole('button', { name: text.newProfile })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.preflight })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: text.showSnapshot })); await screen.findByText(text.savedResult);
    expect(screen.getByRole('button', { name: text.download })).toBeEnabled();
    expect(screen.queryByRole('button', { name: text.reviseSnapshot })).not.toBeInTheDocument(); expect(mocks.post).not.toHaveBeenCalled();
  });

  it('discards privileged drafts after a role change and does not render a late private result', async () => {
    const result = pending(); mocks.post.mockReturnValue(result.promise);
    const { rerender } = view(); await choose(); check();
    mocks.role = 'readonly'; rerender(<MemoryRouter><AnnualTaxPage /></MemoryRouter>);
    await act(async () => result.resolve(preview()));
    expect(screen.queryByText(text.ready)).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: text.saveSnapshot })).not.toBeInTheDocument();
  });

  it('formats aggregate integer cents above Number.MAX_SAFE_INTEGER exactly', async () => {
    mocks.post.mockResolvedValue(preview({ totals: { ...preview().totals, income_cents: '9007199254740993' } }));
    view(); await choose(); check();
    await screen.findByText('90.071.992.547.409,93 €');
  });

  it('restores reviewed split evidence and loads an older profile before preparing a revision', async () => {
    const fallback = mocks.get.getMockImplementation();
    const snapshot = preview({ id: 'original', revision_number: 1, profile_version_id: 'older-version', review_request: { profile_version_id: 'older-version', as_of: '2024-12-31',
      pending_review_reason: 'Original review', empty_cash_review_reason: null, overrides: [{ booking_id: 'booking', reason: 'Original split evidence', correction_of_booking_id: null, transfer_counter_booking_id: null,
        parts: [{ amount_cents: '-4001', property_id: 'property', treatment: 'expense', form_line: 'Reviewed line', reason: 'Actual split evidence', exclusion_kind: null }] }] } });
    mocks.get.mockImplementation(path => path.includes('/projections?') ? Promise.resolve({ total: 1, items: [snapshot] })
      : path.endsWith('/profiles/older-version') ? Promise.resolve({ ...profile(), id: 'older-version' }) : fallback(path));
    view(); await choose(); fireEvent.click(screen.getByRole('button', { name: text.reviseSnapshot }));
    await waitFor(() => expect(screen.getByLabelText(text.profile)).toHaveValue('older-version'));
    expect(screen.getByLabelText(text.signedAmount)).toHaveValue('-40.01'); expect(screen.getByLabelText(text.overrideReason)).toHaveValue('Original split evidence');
    check(); await screen.findByText(text.ready);
    expect(screen.getByLabelText(text.previousSnapshot)).toHaveValue('original');
    expect(screen.getByRole('button', { name: text.saveSnapshot })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(text.revisionReason), { target: { value: 'Reviewed correction' } });
    expect(screen.getByRole('button', { name: text.saveSnapshot })).toBeEnabled();
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ profile_version_id: 'older-version', pending_review_reason: 'Original review', overrides: [{ parts: [{ amount_cents: '-4001' }] }] });
  });
});
