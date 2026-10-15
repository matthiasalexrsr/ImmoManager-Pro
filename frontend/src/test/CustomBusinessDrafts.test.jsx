import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { api } from '../api';
import { workspace } from '../utils/workspaceClient';
import { ReceiptForm } from '../features/invoiceReview/ReviewPanels';
import { ProtocolsTab } from '../features/maintenanceProject/EvidenceTabs';
import { de as maintenanceText } from '../features/maintenanceProject/text';
import DunningCase from '../pages/DunningCase';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'u1' } }), useCanWrite: () => true }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../components/FileViewer', () => ({ default: () => null }));
vi.mock('../components/PhotoDropZone', () => ({ default: () => null }));
vi.mock('../components/PdfPreview', () => ({ default: () => null }));
vi.mock('../utils/workspaceClient', async original => {
  const actual = await original();
  return { ...actual, workspace: { list: vi.fn(), get: vi.fn(), put: vi.fn(), remove: vi.fn(), rebase: vi.fn(), command: () => crypto.randomUUID() } };
});
const revision = '2026-10-15T09:00:00Z';
function savedDraft(context, kind, id, values) {
  workspace.list.mockImplementation(async (_resource, query) => ({ items: query.context === context ? [{
    id: 'saved-draft', revision: 1, form_key: query.form_key, context, values, source: { kind, id, revision },
    anchor: { kind, id }, source_state: { status: 'current' },
  }] : [], next_cursor: null }));
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear();
  workspace.get.mockResolvedValue({ revision });
  workspace.list.mockResolvedValue({ items: [], next_cursor: null });
  workspace.put.mockImplementation(async (_resource, id, body) => ({ id, ...body, revision: body.base_revision + 1 }));
  workspace.remove.mockResolvedValue({ deleted: true });
  api.post.mockResolvedValue({}); api.list.mockResolvedValue([]); api.get.mockResolvedValue({});
});
afterEach(cleanup);

describe('custom business form recovery', () => {
  it('restores receipt candidates without restoring duplicate acceptance or sending a business command', async () => {
    savedDraft('invoice-review-action#receipt', 'invoice', 'i1', {
      received_on: '2026-10-14', kind: 'invoice', property_id: 'p1', cost_category: 'Heizung',
      duplicate_reason: 'Zweite Ausfertigung', accept_duplicate: true,
    });
    const changed = vi.fn();
    // Prepare the source and draft promises before interacting with recovery.
    await act(async () => { render(<MemoryRouter><ReceiptForm view={{ invoice: { id: 'i1', property_id: 'p1' }, duplicates: [{ id: 'i2' }] }} properties={[]} onChanged={changed} /></MemoryRouter>); });
    fireEvent.click(await screen.findByRole('button', { name: 'Entwurf übernehmen' }));
    await waitFor(() => expect(screen.getByLabelText('Kostenart')).toHaveValue('Heizung'));
    expect(screen.getByLabelText('Trotz Dublettenverdacht erfassen')).not.toBeChecked();
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Kostenart'), { target: { value: 'Warmwasser' } });
    await waitFor(() => expect(workspace.put).toHaveBeenCalled(), { timeout: 3000 });
    const body = workspace.put.mock.calls.at(-1)[2];
    expect(body.values.cost_category).toBe('Warmwasser');
    expect(body.values).not.toHaveProperty('accept_duplicate');
    expect(body.field_keys).not.toContain('accept_duplicate');
    workspace.remove.mockRejectedValue(new Error('Private Sicherung offline'));
    fireEvent.submit(screen.getByLabelText('Kostenart').closest('form'));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('accept_duplicate');
  });

  it('recovers maintenance facts and defects while requiring the acceptance result to be chosen again', async () => {
    savedDraft('maintenance-protocol#new', 'maintenance', 'm1', {
      protocol_type: 'acceptance', protocol_date: '2026-10-14', title: 'Dachbegehung', participants: 'Anna', notes: 'Riss prüfen',
      defects: [{ title: 'Riss im Dach', location: 'Ost', severity: 'major', due_date: '', description: '', photo_ids: [] }],
      photo_ids: [], result: 'accepted',
    });
    const reload = vi.fn();
    render(<MemoryRouter><ProtocolsTab ctx={{ caseId: 'm1', tx: maintenanceText, can: { write_protocols: true }, reload,
      project: { protocols: [], work_packages: [], orders: [], photos: [] } }} /></MemoryRouter>);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: maintenanceText.addProtocol })); });
    const dialog = screen.getByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Entwurf übernehmen' }));
    await waitFor(() => expect(within(dialog).getByLabelText(maintenanceText.title)).toHaveValue('Dachbegehung'));
    expect(within(dialog).getByLabelText(`${maintenanceText.defectTitle} 1`)).toHaveValue('Riss im Dach');
    expect(within(dialog).getByLabelText(maintenanceText.result)).toHaveValue('');
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(maintenanceText.result), { target: { value: 'accepted_with_defects' } });
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith('/maintenance/m1/protocols', expect.objectContaining({ title: 'Dachbegehung', result: 'accepted_with_defects' }));
  });

  it('restores a dunning-block reason and date without creating or lifting a block until explicit save', async () => {
    savedDraft('dunning-action#block', 'contract', 'c1', { reason: 'Rückfrage zugesagt', blocked_until: '2026-10-20' });
    api.get.mockResolvedValue({ contract: { id: 'c1', number: 'V1' }, next: { status: 'not_due' },
      totals: { overdue_principal: 100, open_charges: 0, unapplied_payments: 0 },
      claims: [], excluded: [], manual: [], cases: [], blocks: [], disputes: [], as_of: '2026-10-15' });
    await act(async () => { render(<MemoryRouter initialEntries={['/dunning/contracts/c1']}><Routes>
      <Route path="/dunning/contracts/:contractId" element={<DunningCase />} />
    </Routes></MemoryRouter>); });
    fireEvent.click(await screen.findByRole('button', { name: 'Entwurf übernehmen' }));
    const form = screen.getByRole('form', { name: 'Mahnsperre setzen' });
    await waitFor(() => expect(within(form).getByLabelText('Grund')).toHaveValue('Rückfrage zugesagt'));
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.submit(form);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/dunning/contracts/c1/blocks', {
      reason: 'Rückfrage zugesagt', blocked_until: '2026-10-20',
    }));
  });
});
