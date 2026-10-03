import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BillingDisputeRead from '../features/billingDisputes/BillingDisputeRead';
import { casePage, caseRow, event, periodStatus } from './fixtures/disputes';

const mocks = vi.hoisted(() => ({ user: { id: 'actor', role: 'eigentuemer', portfolio_access: 'all' }, get: vi.fn(), getBlob: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user, role: mocks.user.role }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key }) }));
const copy = value => structuredClone(value);
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function read(path) {
  if (path.includes('/periods/period/status')) return Promise.resolve(copy(periodStatus));
  if (path.startsWith('/billing/disputes?')) return Promise.resolve(copy(casePage));
  if (path === '/billing/disputes/case') return Promise.resolve(copy(caseRow));
  if (path.includes('/case/journal')) {
    const after = Number(new URLSearchParams(path.split('?')[1]).get('after'));
    return Promise.resolve({ items: Array.from({ length: after ? 2 : 25 }, (_, index) => event(after + index + 1)), next_after: after ? null : 25, revision: 27 });
  }
  if (path.startsWith('/billing/disputes/case/events/')) return Promise.resolve(event(Number(path.split('-').at(-1))));
  throw new Error(`Unexpected private read: ${path}`);
}
async function open() {
  fireEvent.click(await screen.findByRole('button', { name: 'Akte · statement-original' }));
  await screen.findByText('Beanstandete Originalfassung');
}

beforeEach(() => {
  vi.clearAllMocks(); mocks.user = { id: 'actor', role: 'eigentuemer', portfolio_access: 'all' };
  mocks.get.mockImplementation(read); mocks.getBlob.mockResolvedValue(new Blob(['abc']));
});

describe('actual bounded dispute file reads', () => {
  it('uses complete server counts and advances case keysets without a whole-stock reader', async () => {
    mocks.get.mockImplementation(path => {
      if (path.startsWith('/billing/disputes?')) {
        const next = new URLSearchParams(path.split('?')[1]).get('after_id');
        return Promise.resolve({ items: next ? [{ ...caseRow, id: 'case-26' }] : Array.from({ length: 25 }, (_, index) => ({ ...caseRow, id: `case-${index}` })), next_after_id: next ? null : 'case-24' });
      }
      return read(path);
    });
    render(<BillingDisputeRead periodId="period" />);
    expect(await screen.findByText('27')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Akte · statement-original' })).toHaveLength(25);
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Widerspruchsakten' })).getByRole('button', { name: 'Nächste Seite' }));
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Akte · statement-original' })).toHaveLength(1));
    expect(mocks.get.mock.calls.some(([path]) => path.includes('after_id=case-24'))).toBe(true);
    expect(mocks.get.mock.calls.every(([path]) => path.startsWith('/billing/disputes'))).toBe(true);
  });
  it('loads exact original and bounded chronology only on opening, preserving source fields and historical limits', async () => {
    render(<BillingDisputeRead periodId="period" />);
    await screen.findByText('27'); expect(mocks.get.mock.calls.some(([path]) => path.includes('/journal') || path === '/billing/disputes/case')).toBe(false);
    await open();
    expect(screen.getByText(caseRow.party_binding_note)).toBeInTheDocument();
    expect(screen.getByText(/123,45\s*€/)).toBeInTheDocument();
    const history = await screen.findByRole('region', { name: 'Chronik' });
    await waitFor(() => expect(within(history).getAllByRole('button', { name: /Originalereignis öffnen/ })).toHaveLength(25));
    fireEvent.click(within(history).getByRole('button', { name: 'Nächste Seite', exact: true }));
    await waitFor(() => expect(within(history).getAllByRole('button', { name: /Originalereignis öffnen/ })).toHaveLength(2));
    expect(within(history).getByText('Original reason 27')).toBeInTheDocument();
    expect(within(history).queryByText('Original reason 1')).not.toBeInTheDocument();
    fireEvent.click(within(history).getByRole('button', { name: 'Originalereignis öffnen · Revision 26' }));
    const original = await screen.findByRole('region', { name: 'Originalereignis' });
    expect(await within(original).findByText('Original reason 26')).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith('/billing/disputes/case/events/event-26', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });
  it('keeps legacy disputed status explicit and treats a failed case list as an error', async () => {
    mocks.get.mockImplementation(path => path.includes('/status') ? Promise.resolve({ ...periodStatus, legacy_disputed_without_complete_case: true, case_count: 0, open_case_count: 0 })
      : Promise.reject(Object.assign(new Error('Journal nicht migriert'), { statusCode: 503 })));
    render(<BillingDisputeRead periodId="period" />);
    expect(await screen.findByText(/Altstatus ohne vollständige/)).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Journal nicht migriert');
    expect(screen.queryByText('Keine passenden Akten auf dieser Seite.')).not.toBeInTheDocument();
  });
  it('blocks command entry for a readonly actor while retaining original navigation', async () => {
    mocks.user.role = 'readonly'; const create = vi.fn(); const append = vi.fn();
    render(<BillingDisputeRead periodId="period" onNewCase={create} onEvent={append} />); await open();
    expect(screen.queryByRole('button', { name: 'Neue Akte erfassen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Notiz hinzufügen', exact: true })).not.toBeInTheDocument();
    expect(create).not.toHaveBeenCalled(); expect(append).not.toHaveBeenCalled();
  });
  it('rejects a mismatched original revision instead of displaying a plausible empty case', async () => {
    mocks.get.mockImplementation(path => path === '/billing/disputes/case' ? Promise.resolve({ ...caseRow, statement_revision: 4 }) : read(path));
    render(<BillingDisputeRead periodId="period" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Akte · statement-original' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Aktenantwort konnte nicht geprüft');
    expect(screen.queryByText('Beanstandete Originalfassung')).not.toBeInTheDocument();
  });
  it('aborts a pending original read and hides late private contents on actor switch', async () => {
    const detail = pending(); let signal;
    mocks.get.mockImplementation((path, options) => path === '/billing/disputes/case' ? (signal = options.signal, detail.promise) : read(path));
    const ui = render(<BillingDisputeRead periodId="period" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Akte · statement-original' }));
    await waitFor(() => expect(signal).toBeDefined());
    mocks.user = { id: 'different-actor', role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] };
    mocks.get.mockResolvedValue({ items: [], next_after_id: null });
    ui.rerender(<BillingDisputeRead periodId="period" />); expect(signal.aborted).toBe(true);
    await act(async () => detail.resolve(copy(caseRow)));
    expect(screen.queryByText(caseRow.party_binding_note)).not.toBeInTheDocument();
    expect(screen.queryByText('Original reason 1')).not.toBeInTheDocument();
  });
  it('hides the entire private workspace on a server scope denial during chronology loading', async () => {
    mocks.get.mockImplementation(path => path.includes('/journal') ? Promise.reject(Object.assign(new Error('Private grant gone'), { statusCode: 403 })) : read(path));
    render(<BillingDisputeRead periodId="period" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Akte · statement-original' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Der Zugriff wurde geändert');
    expect(screen.queryByText('Beanstandete Originalfassung')).not.toBeInTheDocument();
    expect(screen.queryByText(caseRow.party_binding_note)).not.toBeInTheDocument();
  });
  it('downloads only the authenticated immutable version and refuses a truncated original', async () => {
    mocks.getBlob.mockResolvedValue(new Blob(['ab']));
    render(<BillingDisputeRead periodId="period" />); await open();
    fireEvent.click((await screen.findAllByRole('button', { name: 'Original herunterladen' }))[0]);
    expect(await screen.findByRole('alert')).toHaveTextContent('Aktenantwort konnte nicht geprüft');
    expect(mocks.getBlob).toHaveBeenCalledWith('/documents/document/versions/version/download', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });
});
