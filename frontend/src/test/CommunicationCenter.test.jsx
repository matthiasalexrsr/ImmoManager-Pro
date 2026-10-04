import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CommunicationCenter from '../pages/CommunicationCenter';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(), getBlob: vi.fn(),
  confirm: vi.fn(), canWrite: true, role: 'eigentuemer',
}));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'actor', role: mocks.role } }),
}));
vi.mock('../hooks/useWriteAccess', () => ({
  default: () => ({ canWrite: mocks.canWrite }),
}));
vi.mock('../components/ConfirmDialog', () => ({
  useConfirm: () => mocks.confirm,
}));

const portfolio = { id: 'p1', name: 'Portfolio Mitte' };
const tenant = { id: 't1', full_name: 'Mara Muster' };
const contract = { id: 'c1', tenant_id: 't1', contract_number: 'MV-1' };
const template = {
  id: 'tpl1', name: 'Mieterschreiben', category: 'general', audience: 'tenant',
  channel: 'universal', is_active: true, subject_template: 'Vertrag {{contract.number}}',
  body_template: 'Hallo {{recipient.name}}', revision: 1,
};
const draft = {
  id: 'd1', portfolio_id: 'p1', title: 'Mieterschreiben', channel: 'email',
  recipient_type: 'tenant', recipient_id: 't1', contract_id: 'c1', template_id: '',
  subject_template: 'Vertrag {{contract.number}}', body_template: 'Hallo {{recipient.name}}',
  status: 'draft', revision: 1, whatsapp_language_code: 'de',
};
const reviewed = {
  ...draft, status: 'reviewed', revision: 2, rendered_subject: 'Vertrag MV-1',
  rendered_body: 'Hallo Mara Muster', snapshot_sha256: 'a'.repeat(64),
};
const queued = { ...reviewed, status: 'queued', revision: 2, external_reference: 'outbox-1' };
const preview = {
  subject: 'Vertrag MV-1', body: 'Hallo Mara Muster', missing_fields: [], warnings: [],
  recipient: { name: 'Mara Muster', email: 'mara@example.test' },
  context: {}, context_sha256: 'b'.repeat(64),
};

const view = () => render(<MemoryRouter><CommunicationCenter /></MemoryRouter>);

beforeEach(() => {
  mocks.canWrite = true; mocks.role = 'eigentuemer';
  mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.put.mockReset(); mocks.getBlob.mockReset();
  mocks.getAll.mockReset().mockImplementation(async path => ({
    '/portfolios': [portfolio], '/tenants': [tenant], '/contacts': [], '/contracts': [contract],
  }[path] || []));
  mocks.get.mockReset().mockImplementation(async path =>
    path === '/communication-center/catalog'
      ? { variables: [], blocks: [], channels: [], templates: [template] }
      : path.startsWith('/communication-center/drafts?') ? [] : {});
  mocks.post.mockReset().mockImplementation(async (path) => {
    if (path.startsWith('/communication-center/preview?')) return preview;
    if (path === '/communication-center/drafts') return draft;
    if (path === '/communication-center/drafts/d1/review') return reviewed;
    if (path === '/communication-center/drafts/d1/dispatch') {
      return { draft: queued, provider: 'smtp-outbox', result: {} };
    }
    return {};
  });
});

describe('communication center', () => {
  it('renders authoritative preview, freezes a reviewed snapshot and hands it to the channel', async () => {
    view();
    await screen.findByRole('heading', { name: 'Kommunikationszentrum' });
    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Mieterschreiben' } });
    fireEvent.change(screen.getByLabelText('Empfänger'), { target: { value: 't1' } });
    fireEvent.change(screen.getByLabelText('Vertrag'), { target: { value: 'c1' } });
    fireEvent.change(screen.getByLabelText('Betreff'), {
      target: { value: 'Vertrag {{contract.number}}' },
    });
    fireEvent.change(screen.getByLabelText('Dokumentinhalt'), {
      target: { value: 'Hallo {{recipient.name}}' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Vorschau prüfen' }));
    expect(await screen.findByText('Hallo Mara Muster')).toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledWith(
      '/communication-center/preview?portfolio_id=p1',
      expect.objectContaining({ recipient_id: 't1', contract_id: 'c1', channel: 'email' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Verbindlich freigeben' }));
    await screen.findByText(/Daten-Snapshot und Prüfsummen freigegeben/);
    expect(mocks.post).toHaveBeenCalledWith('/communication-center/drafts', expect.any(Object));
    expect(mocks.post).toHaveBeenCalledWith('/communication-center/drafts/d1/review', {
      expected_revision: 1, confirmed: true,
    });

    fireEvent.click(screen.getByRole('button', { name: 'E-Mail übergeben' }));
    await screen.findByText(/An Versandkanal übergeben/);
    expect(mocks.post).toHaveBeenCalledWith('/communication-center/drafts/d1/dispatch', {
      expected_revision: 2, confirmed: true, action: 'email', test_mode: true,
    });
    expect(mocks.confirm).toHaveBeenCalledTimes(2);
  });

  it('keeps the installation library readable but removes mutation controls for readonly users', async () => {
    mocks.canWrite = false; mocks.role = 'readonly';
    view();
    await screen.findByRole('heading', { name: 'Kommunikationszentrum' });
    expect(screen.queryByRole('button', { name: '+ Neue Korrespondenz' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Entwurf speichern' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Vorlagen' }));
    await waitFor(() => expect(screen.getByText('Mieterschreiben')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: '+ Vorlage' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Starterbibliothek/ })).not.toBeInTheDocument();
  });
});
