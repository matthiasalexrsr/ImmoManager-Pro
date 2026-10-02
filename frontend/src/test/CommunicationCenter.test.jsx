import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CommunicationCenter from '../pages/CommunicationCenter';

const mocks = vi.hoisted(() => ({
  role: 'eigentuemer',
  get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(),
  getBlob: vi.fn(), confirm: vi.fn(),
}));

vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1', role: mocks.role,
      write_permissions: mocks.role === 'readonly' ? [] : ['communication'],
    },
  }),
}));
vi.mock('../components/ConfirmDialog', () => ({
  useConfirm: () => mocks.confirm,
}));
vi.mock('../i18n', () => ({
  useTranslation: () => ({ t: key => key, locale: 'de-DE' }),
}));

const catalog = {
  variables: [{ key: 'recipient.name', label: 'Empfängername / Firma' }],
  blocks: [], templates: [], channels: [],
};
const portfolio = { id: 'portfolio-1', name: 'Privatbestand' };
const tenant = { id: 'tenant-1', full_name: 'Mara Muster' };
const contract = { id: 'contract-1', tenant_id: tenant.id, contract_number: 'MV-1' };

beforeEach(() => {
  mocks.role = 'eigentuemer';
  mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.getAll.mockReset().mockImplementation(async path => ({
    '/portfolios': [portfolio],
    '/tenants': [tenant],
    '/contacts': [],
    '/contracts': [contract],
  }[path] || []));
  mocks.get.mockReset().mockImplementation(async path => (
    path === '/communication-center/catalog' ? catalog
      : path.startsWith('/communication-center/drafts?') ? []
        : null
  ));
  mocks.post.mockReset().mockImplementation(async (path, body) => (
    path.startsWith('/communication-center/preview')
      ? {
        subject: body.subject_template, body: `Hallo Mara Muster`,
        recipient: tenant, context: {}, context_sha256: 'a'.repeat(64),
        missing_fields: [], warnings: [],
      }
      : path === '/communication-center/starter-library'
        ? { templates_added: 5, blocks_added: 3 }
        : {}
  ));
  mocks.put.mockReset();
  mocks.getBlob.mockReset();
});

const view = () => render(<MemoryRouter><CommunicationCenter /></MemoryRouter>);

describe('communication center', () => {
  it('renders the editor and sends the selected channel to authoritative preview', async () => {
    view();
    await screen.findByRole('heading', { name: 'Kommunikationszentrum' });
    fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: tenant.id } });
    fireEvent.change(screen.getByLabelText('Vertrag'), { target: { value: contract.id } });
    fireEvent.change(screen.getByLabelText('Dokumentinhalt'), {
      target: { value: 'Hallo {{recipient.name}}' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    await screen.findByText('Hallo Mara Muster');
    const call = mocks.post.mock.calls.find(([url]) => url.startsWith('/communication-center/preview'));
    expect(call[1]).toMatchObject({
      recipient_type: 'tenant', recipient_id: tenant.id,
      contract_id: contract.id, channel: 'email',
      body_template: 'Hallo {{recipient.name}}',
    });
  });

  it('lets only library administrators install starter templates', async () => {
    view();
    await screen.findByRole('heading', { name: 'Kommunikationszentrum' });
    fireEvent.click(screen.getByRole('button', { name: 'Vorlagen' }));
    const starter = screen.getByRole('button', { name: 'Starterbibliothek ergänzen' });
    fireEvent.click(starter);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
      '/communication-center/starter-library', {},
    ));
    await screen.findByText(/Starterbibliothek ergänzt: 5 Vorlagen, 3 Bausteine/);
  });
  it('keeps the library read-only for readonly users', async () => {
    mocks.role = 'readonly';
    view();
    await screen.findByRole('heading', { name: 'Kommunikationszentrum' });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(
      expect.stringContaining('/communication-center/drafts?portfolio_id='),
    ));
    expect(screen.queryByRole('button', { name: '+ Neue Korrespondenz' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Vorlagen' }));
    expect(screen.queryByRole('button', { name: 'Starterbibliothek ergänzen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '+ Vorlage' })).not.toBeInTheDocument();
  });
});
