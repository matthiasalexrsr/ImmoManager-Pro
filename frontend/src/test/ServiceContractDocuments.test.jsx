import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import DocumentsTab from '../features/serviceContracts/DocumentsTab';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), del: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => {
  const t = key => key;
  return { useTranslation: () => ({ t, locale: 'de-DE' }) };
});
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => true }));
vi.mock('../components/FileViewer', () => ({ default: ({ title }) => <div role="dialog">{title}</div> }));

const contract = { id: 'sc1', property_ids: ['p1', 'p2'] };
const existing = { id: 'existing', link_id: 'link1', title: 'Vertragsoriginal', source: 'contract' };
const document = { id: 'available', title: 'Wartungsnachweis' };
const mount = value => render(<MemoryRouter><DocumentsTab contract={value || contract} canWrite /></MemoryRouter>);
const linkButton = () => screen.getByRole('button', { name: 'serviceContracts.linkDocument', exact: true });
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  api.get.mockResolvedValue([existing]);
  api.list.mockResolvedValue([document]);
});
afterEach(cleanup);

it('keeps a failed source visible as a retryable error instead of an empty or partial chooser', async () => {
  api.list.mockImplementation(path => path.includes('p2') ? Promise.reject(new Error('Haus Süd offline')) : Promise.resolve([document]));
  mount();
  await screen.findByText('Vertragsoriginal');
  fireEvent.click(linkButton());
  expect(await screen.findByRole('alert')).toHaveTextContent('Haus Süd offline');
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  api.list.mockResolvedValue([document]);
  fireEvent.click(screen.getByRole('button', { name: 'Auswahl erneut laden' }));
  expect(await screen.findByRole('combobox', { name: 'serviceContracts.fields.document *' })).toHaveTextContent('Wartungsnachweis');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('deduplicates documents across locations and excludes documents already linked', async () => {
  api.list.mockResolvedValue([document, existing]);
  mount();
  await screen.findByText('Vertragsoriginal');
  fireEvent.click(linkButton());
  const select = await screen.findByRole('combobox', { name: 'serviceContracts.fields.document *' });
  await waitFor(() => expect(select).toHaveTextContent('Wartungsnachweis'));
  expect(within(select).getAllByRole('option', { name: 'Wartungsnachweis' })).toHaveLength(1);
  expect(within(select).queryByRole('option', { name: 'Vertragsoriginal' })).not.toBeInTheDocument();
});

it('retries a failed document list and links to the exact document record', async () => {
  api.get.mockRejectedValueOnce(new Error('Dokumentdienst offline')).mockResolvedValue([existing]);
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('Dokumentdienst offline');
  fireEvent.click(screen.getByRole('button', { name: 'serviceContracts.retry' }));
  const link = await screen.findByRole('link', { name: 'Dokumentenakte: Vertragsoriginal' });
  expect(link).toHaveAttribute('href', '/documents?focus_id=existing');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('ignores the late document selection of a previously opened contract', async () => {
  let finish;
  const old = new Promise(resolve => { finish = resolve; });
  api.list.mockImplementation(path => path.includes('p2') ? old : Promise.resolve([document]));
  const view = mount();
  await screen.findByText('Vertragsoriginal');
  fireEvent.click(linkButton());
  view.rerender(<MemoryRouter><DocumentsTab contract={{ id: 'sc2', property_ids: ['p3'] }} canWrite /></MemoryRouter>);
  await act(async () => finish([{ id: 'old-only', title: 'Alte Akte' }]));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByText('Alte Akte')).not.toBeInTheDocument();
});
