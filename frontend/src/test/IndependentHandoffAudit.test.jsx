import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Invoices from '../pages/Invoices';
import { api } from '../api';
import { holdNewEntry, dropNewEntry } from '../utils/newEntry';

vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'audit-owner' } }), useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({ useEntities: () => ({ items: [], loading: false }), useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: {
  list: vi.fn(async () => ({ items: [] })), get: vi.fn(), put: vi.fn(), remove: vi.fn(), touch: vi.fn(), command: () => crypto.randomUUID(),
} }));
afterEach(() => { cleanup(); dropNewEntry('/'); });

it.each([true, false])('keeps the authoritative invoice proposal (proposal first: %s)', async proposalFirst => {
  let proposalReady;
  let listReady;
  api.list.mockReturnValue(new Promise(resolve => { listReady = resolve; }));
  api.post.mockResolvedValue({items:[]});
  api.get.mockImplementation(path => path.startsWith('/assistant/proposals/')
    ? new Promise(resolve => { proposalReady = resolve; }) : Promise.resolve({}));
  // Layout queues the generic ?neu=1 request while Invoices is showing its loading state.
  holdNewEntry('/invoices');
  render(<MemoryRouter initialEntries={['/invoices?assistant_proposal=audit-proposal']}><Invoices /></MemoryRouter>);
  await waitFor(() => expect(proposalReady).toBeTypeOf('function'));
  if (!proposalFirst) await act(async () => listReady([]));
  await act(async () => proposalReady({ id: 'audit-proposal', revision: 2, state: 'applied',
    payload: { kind: 'invoice', values: { supplier: 'Audit Heizungsbetrieb', invoice_date: '2026-10-18',
      net_amount: '100.00', gross_amount: '119.00', vat_rate: '19.00' } } }));
  expect(await screen.findByRole('textbox', {name:'Lieferant *'})).toHaveValue('Audit Heizungsbetrieb');
  if (proposalFirst) await act(async () => listReady([]));
  expect(screen.getByRole('textbox', {name:'Lieferant *'})).toHaveValue('Audit Heizungsbetrieb');
});
