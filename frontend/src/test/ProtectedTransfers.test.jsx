import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import ServiceDocuments from '../features/serviceContracts/DocumentsTab';
import { DocumentsTab as MaintenanceDocuments } from '../features/maintenanceProject/EvidenceTabs';
import { de } from '../features/maintenanceProject/text';
import BackupSection from '../pages/settings/BackupSection';
import AutotestSection from '../pages/settings/AutotestSection';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), upload: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn() }) }));
const fixtures = ['service', 'maintenance'];
const renderDocuments = async type => {
  const element = type === 'service' ? <ServiceDocuments contract={{ id: 's1', property_ids: ['p1'] }} canWrite />
    : <MaintenanceDocuments ctx={{ caseId: 'm1', project: { case: { property_id: 'p1', unit_id: 'u1', title: 'Dach' }, documents: [] },
      tx: de, can: { documents: true }, reload: vi.fn(), act: vi.fn() }} />;
  let view;
  await act(async () => { view = render(<MemoryRouter>{element}</MemoryRouter>); });
  return view;
};
beforeEach(() => {
  vi.resetAllMocks();
  api.captureSession.mockReturnValue(() => {});
  api.get.mockResolvedValue([]); api.list.mockResolvedValue([]); api.post.mockResolvedValue({ id: 'd1' });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it.each(fixtures)('persists and links a %s upload only after the protected multipart response', async type => {
  const file = new File(['document'], 'vertrag.pdf');
  api.upload.mockResolvedValue({ file_url: '/uploads/vertrag.pdf' });
  const view = await renderDocuments(type);
  await act(async () => { fireEvent.change(view.container.querySelector('input[type=file]'), { target: { files: [file] } }); });
  expect(api.upload).toHaveBeenCalledWith('/files/upload?folder=documents', expect.any(FormData));
  expect(api.upload.mock.calls[0][1].get('file')).toBe(file);
  expect(api.post).toHaveBeenCalledWith('/documents', expect.objectContaining({ file_url: '/uploads/vertrag.pdf', property_id: 'p1' }));
  expect(api.post.mock.calls[1][0]).toBe(type === 'service' ? '/service-contracts/s1/documents' : '/maintenance/m1/documents');
  expect(api.post.mock.calls[1][1]).toEqual(expect.objectContaining({ document_id: 'd1' }));
});

it.each(fixtures)('stops %s document creation when its captured session changes during upload', async type => {
  let changed = false; let finish;
  api.captureSession.mockImplementation(() => () => { if (changed) throw new Error('Sitzung gewechselt'); });
  api.upload.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = await renderDocuments(type);
  fireEvent.change(view.container.querySelector('input[type=file]'), { target: { files: [new File(['document'], 'vertrag.pdf')] } });
  changed = true;
  await act(async () => { finish({ file_url: '/uploads/old-owner.pdf' }); });
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Sitzung gewechselt');
});

it.each(fixtures)('does not create a %s document after its upload view unmounts', async type => {
  let finish;
  api.upload.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = await renderDocuments(type);
  fireEvent.change(view.container.querySelector('input[type=file]'), { target: { files: [new File(['document'], 'vertrag.pdf')] } });
  view.unmount();
  await act(async () => { finish({ file_url: '/uploads/old-context.pdf' }); });
  expect(api.post).not.toHaveBeenCalled();
});

it.each(['backup', 'autotest'])('downloads the %s export through the protected blob client', async type => {
  const blob = new Blob(['private report']);
  api.getBlob.mockResolvedValue(blob);
  api.post.mockResolvedValue({ summary: { passed: 1, total: 1 } });
  vi.stubGlobal('URL', class extends URL { static createObjectURL = vi.fn(() => 'blob:private'); static revokeObjectURL = vi.fn(); });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(type === 'backup' ? <BackupSection /> : <AutotestSection />);
  if (type === 'autotest') await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Run Autotest' })); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: type === 'backup' ? 'pages.settings.jsonExport' : 'Download Markdown' })); });
  expect(api.getBlob).toHaveBeenCalledWith(type === 'backup' ? '/data/export' : '/autotest/report/markdown');
  expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:private');
});
