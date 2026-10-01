import { webcrypto } from 'node:crypto';
import { Blob as NodeBlob } from 'node:buffer';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContractWizard from '../pages/ContractWizard';
import ContractReferencePicker from '../components/ContractReferencePicker';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), getBlob: vi.fn(), confirm: vi.fn(), role: 'verwalter', locale: 'de-DE', current: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'actor', role: mocks.role } }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
const languages = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const translate = key => key.split('.').reduce((value, part) => value?.[part], languages[mocks.locale]) || key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale, t: translate }) }));
const text = de.contractWizard.workflow;
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = (path = '/contract-wizard') => render(<MemoryRouter initialEntries={[path]}><ContractWizard /></MemoryRouter>);
const clone = value => structuredClone(value);
const saved = () => ({ id: 'draft-one', portfolio_id: 'portfolio', state: 'draft', revision: 1, persistent: true,
  data: { property_id: 'property', unit_id: 'unit', new_tenant: { full_name: 'Synthetic tenant', email: null }, tenant_id: null,
    contract_number: 'SYN-1', start_date: '2026-10-01', end_date: null, landlord_name: 'Synthetic owner', landlord_address: 'Synthetic street 1',
    deposit_amount: '1500.00', terms: 'Own reviewed synthetic terms', template_id: null, index_rent: 'fixed', service_charge_settlement: 'annual',
    contract_status: 'draft', create_handover: false, attachment_ids: [], metadata_only_attachment_ids: [] } });
const reviewed = base => ({ ...clone(base), state: 'reviewed', revision: 2, review_hash: 'a'.repeat(64), pdf_sha256: 'b'.repeat(64), preview_url: '/contract-wizard/drafts/draft-one/review-pdf',
  review: { property: { name: 'Synthetic property' }, unit: { label: 'A', cold_rent: 600, service_charge_advance: 100, heating_advance: 50 },
    tenant: { full_name: base.data.new_tenant?.full_name || 'Existing tenant' }, parameters: clone(base.data), portfolio: { currency: 'EUR' },
    terms: base.data.terms, template: null, attachments: [] } });
const published = base => ({ ...clone(base), state: 'committed', revision: 3, contract_id: 'contract-one', document_id: 'document-one', pdf_url: '/contract-wizard/drafts/draft-one/pdf' });

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  mocks.role = 'verwalter'; mocks.locale = 'de-DE'; mocks.current = null;
  mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.getBlob.mockReset(); mocks.post.mockReset(); mocks.get.mockReset().mockImplementation(async path => {
    if (path.includes('/choices/')) {
      const kind = path.split('/choices/')[1].split('?')[0];
      const items = { properties: [{ id: 'property', label: 'Synthetic property', portfolio_id: 'portfolio' }],
        units: [{ id: 'unit', label: 'A' }], tenants: [{ id: 'tenant', label: 'Existing tenant' }], documents: [{ id: 'attachment', label: 'Synthetic attachment' }] }[kind];
      const selected = items.find(value => value.id === new URLSearchParams(path.split('?')[1]).get('selected_id')) || null;
      return { items, selected, has_more: false };
    }
    if (path.includes('/templates')) return { items: [], total: 0 };
    if (path.includes('/attachments') || path.includes('/signatures')) return { items: [], has_more: false };
    if (path.includes('/drafts?')) return { items: mocks.current ? [clone(mocks.current)] : [], total: mocks.current ? 1 : 0 };
    if (path.includes('/drafts/')) return clone(mocks.current);
    throw new Error('Unexpected synthetic request');
  });
  mocks.post.mockImplementation(async (path, body) => {
    if (path.endsWith('/review')) mocks.current = reviewed(mocks.current);
    else if (path.endsWith('/publish')) mocks.current = published(mocks.current);
    else if (path.endsWith('/signatures')) mocks.current = { ...mocks.current, state: 'signed', revision: mocks.current.revision + 1 };
    else if (path.endsWith('/edit')) mocks.current = { ...mocks.current, state: 'draft', revision: mocks.current.revision + 1, data: clone(body.data), review: null, review_hash: null };
    else if (path.endsWith('/drafts')) mocks.current = { ...saved(), data: clone(body.data) };
    return clone(mocks.current);
  });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function fillDraft() {
  await screen.findByRole('button', { name: text.newDraft });
  fireEvent.click(screen.getByRole('button', { name: text.newDraft }));
  await screen.findByRole('option', { name: 'Synthetic property' });
  fireEvent.change(screen.getByLabelText(text.property + ' *'), { target: { value: 'property' } });
  await waitFor(() => expect(screen.getByLabelText(text.unit + ' *')).not.toBeDisabled());
  fireEvent.change(screen.getByLabelText(text.unit + ' *'), { target: { value: 'unit' } });
  for (const [label, value] of [[text.landlord + ' *', 'Synthetic owner'], [text.landlordAddress + ' *', 'Synthetic street 1'],
    [text.tenant_full_name + ' *', 'Synthetic tenant'], [text.number + ' *', 'SYN-1'], [text.terms, 'Own reviewed synthetic terms']])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  return screen.getByRole('button', { name: text.saveDraft }).closest('form');
}

describe('persistent reviewed contract workflow', () => {
  it('saves no contract until explicit review and confirmation; keeps bounded choices', async () => {
    view();
    fireEvent.submit(await fillDraft());
    await waitFor(() => expect(screen.getByRole('button', { name: text.review })).not.toBeDisabled());
    expect(mocks.post.mock.calls[0][1].data.contract_status).toBe('draft');
    expect(mocks.post.mock.calls.some(([path]) => path.endsWith('/publish'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: text.review }));
    await screen.findByRole('heading', { name: `4 · ${text.reviewTitle}` });
    mocks.confirm.mockResolvedValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: text.publish }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(text.publishConfirm));
    expect(mocks.post.mock.calls.some(([path]) => path.endsWith('/publish'))).toBe(false);
    await waitFor(() => expect(screen.getByRole('button', { name: text.publish })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: text.publish }));
    await screen.findByRole('heading', { name: text.published });
    expect(screen.getByText(text.noCash)).toBeInTheDocument();
    expect(mocks.post.mock.calls.filter(([path]) => path.endsWith('/publish'))).toHaveLength(1);
    expect(mocks.get.mock.calls.filter(([path]) => path.includes('/choices/')).every(([path]) => new URLSearchParams(path.split('?')[1]).get('limit') === '25')).toBe(true);
  });

  it('preserves typed draft and retries exactly the same command after lost response', async () => {
    view(); const form = await fillDraft();
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Synthetic network loss'), { isNetwork: true }));
    fireEvent.submit(form);
    await screen.findByText('Synthetic network loss');
    expect(screen.getByLabelText(text.number + ' *')).toHaveValue('SYN-1');
    expect(screen.getByRole('button', { name: text.saveDraft })).toBeDisabled();
    const original = mocks.post.mock.calls[0];
    fireEvent.click(screen.getByRole('button', { name: text.retryExact }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1]).toEqual(original);
    await waitFor(() => expect(screen.getByRole('button', { name: text.review })).toBeEnabled());
  });

  it('ignores duplicate submissions while pending and readonly never writes', async () => {
    view(); const form = await fillDraft(); const request = pending(); mocks.post.mockReturnValueOnce(request.promise);
    fireEvent.submit(form); fireEvent.submit(form);
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(form).toHaveAttribute('aria-busy', 'true');
    await act(async () => { mocks.current = saved(); request.resolve(clone(mocks.current)); });
  });

  it('shows readonly saved review and denies publish, new draft and edit', async () => {
    mocks.current = reviewed(saved()); mocks.role = 'readonly';
    view('/contract-wizard?draft=draft-one');
    await screen.findByRole('heading', { name: `4 · ${text.reviewTitle}` });
    expect(screen.getByRole('button', { name: text.newDraft })).toBeDisabled();
    expect(screen.getByRole('button', { name: text.saveDraft })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: text.publish }));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('does not replace edits when language changes and keeps a failed CAS recoverable', async () => {
    mocks.current = saved(); const result = view('/contract-wizard?draft=draft-one');
    await screen.findByDisplayValue('SYN-1');
    fireEvent.change(screen.getByLabelText(text.number + ' *'), { target: { value: 'Own changed number' } });
    mocks.locale = 'en-US'; result.rerender(<MemoryRouter initialEntries={['/contract-wizard?draft=draft-one']}><ContractWizard /></MemoryRouter>);
    expect(screen.getByLabelText(en.contractWizard.workflow.number + ' *')).toHaveValue('Own changed number');
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Synthetic stale revision'), { statusCode: 409 }));
    fireEvent.submit(screen.getByRole('button', { name: en.contractWizard.workflow.saveDraft }).closest('form'));
    await screen.findByText('Synthetic stale revision');
    expect(screen.getByLabelText(en.contractWizard.workflow.number + ' *')).toHaveValue('Own changed number');
    expect(screen.queryByRole('button', { name: en.contractWizard.workflow.retryExact })).not.toBeInTheDocument();
  });

  it('rejects malformed mutation success and failed / non-PDF download responses', async () => {
    mocks.current = reviewed(saved()); view('/contract-wizard?draft=draft-one');
    await screen.findByRole('button', { name: text.publish });
    mocks.post.mockResolvedValueOnce({ ok: true });
    fireEvent.click(screen.getByRole('button', { name: text.publish }));
    await screen.findByText(text.malformed);
    expect(screen.queryByRole('heading', { name: text.published })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: text.retryExact })).toBeInTheDocument();
    const createUrl = vi.fn(); vi.stubGlobal('URL', class extends URL { static createObjectURL = createUrl; static revokeObjectURL = vi.fn(); });
    mocks.getBlob.mockRejectedValueOnce(Object.assign(new Error('Synthetic 401'), { statusCode: 401 }));
    fireEvent.click(screen.getByRole('button', { name: text.previewPdf }));
    await screen.findByText('Synthetic 401'); expect(createUrl).not.toHaveBeenCalled();
    mocks.getBlob.mockResolvedValueOnce(new NodeBlob(['<html>failure</html>'], { type: 'text/html' }));
    fireEvent.click(screen.getByRole('button', { name: text.previewPdf }));
    await screen.findByText(text.malformed); expect(createUrl).not.toHaveBeenCalled();
  });

  it('prevents Enter in embedded search from submitting a surrounding form; pages references', async () => {
    const submit = vi.fn(event => event.preventDefault());
    mocks.get.mockResolvedValue({ items: [{ id: 'property', label: 'Synthetic property' }], selected: null, has_more: true });
    render(<form onSubmit={submit}><ContractReferencePicker kind="properties" label="Object choice" value="" onChange={vi.fn()} /></form>);
    await screen.findByRole('option', { name: 'Synthetic property' });
    const search = screen.getByLabelText(`Object choice: ${text.search}`);
    expect(fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', cancelable: true })).toBe(false);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: text.next }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => new URLSearchParams(path.split('?')[1]).get('offset') === '25')).toBe(true));
  });

  it('requires explicit confirmation for factual signature evidence and never activates a contract', async () => {
    mocks.current = published(reviewed(saved())); view('/contract-wizard?draft=draft-one');
    fireEvent.click(await screen.findByRole('button', { name: text.recordSignature }));
    fireEvent.change(screen.getByLabelText(text.signature_reference), { target: { value: 'Paper original, local cabinet 12' } });
    mocks.confirm.mockResolvedValueOnce(false);
    fireEvent.submit(screen.getByRole('button', { name: text.saveSignature }).closest('form'));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(text.signatureConfirm));
    expect(mocks.post).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('button', { name: text.saveSignature })).toBeEnabled());
    fireEvent.submit(screen.getByRole('button', { name: text.saveSignature }).closest('form'));
    await waitFor(() => expect(screen.queryByRole('button', { name: text.saveSignature })).not.toBeInTheDocument());
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post.mock.calls[0][0]).toBe('/contract-wizard/drafts/draft-one/signatures');
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ confirmed: true, expected_revision: 3,
      tenant_signer: 'Synthetic tenant', landlord_signer: 'Synthetic owner', reference: 'Paper original, local cabinet 12' });
    expect(mocks.current.data.contract_status).toBe('draft');
  });

  it('retains an immutable template-version draft after a concrete server rejection', async () => {
    mocks.current = saved(); view('/contract-wizard?draft=draft-one');
    const create = await screen.findByRole('button', { name: text.newTemplate });
    await waitFor(() => expect(create).toBeEnabled()); fireEvent.click(create);
    fireEvent.change(screen.getByLabelText(text.templateTitle), { target: { value: 'Own reviewed version' } });
    fireEvent.change(screen.getByLabelText(text.templateBody), { target: { value: 'Own complete reviewed terms' } });
    mocks.post.mockRejectedValueOnce(Object.assign(new Error('Synthetic version conflict'), { statusCode: 409 }));
    fireEvent.click(screen.getByRole('button', { name: text.saveVersion }));
    await screen.findByText('Synthetic version conflict');
    expect(screen.getByLabelText(text.templateBody)).toHaveValue('Own complete reviewed terms');
    expect(screen.getByLabelText(text.templateTitle)).toHaveValue('Own reviewed version');
    expect(screen.getByRole('button', { name: text.saveDraft })).toBeDisabled();
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ portfolio_id: 'portfolio', previous_id: null });
  });

  it.each(['de-DE', 'en-US', 'es-ES'])('has complete localized workflow actions in %s', async locale => {
    mocks.locale = locale; view(); const labels = languages[locale].contractWizard.workflow;
    await screen.findByRole('heading', { name: labels.title });
    expect(screen.getByRole('button', { name: labels.legacy })).toBeInTheDocument();
    expect(Object.keys(labels).sort()).toEqual(Object.keys(text).sort());
    expect(screen.queryByText(/contractWizard\.workflow\./)).not.toBeInTheDocument();
  });
});
