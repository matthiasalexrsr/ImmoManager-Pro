import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import PhotoDropZone from '../components/PhotoDropZone';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), del: vi.fn(), upload: vi.fn(), captureSession: () => () => {} } }));
const access = vi.hoisted(() => ({ canEdit: true, confirm: vi.fn() }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => access.confirm }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.canEdit }));
vi.mock('../components/FileViewer', () => ({ default: ({ title, onClose }) => <div role="dialog" aria-label={title}><button onClick={onClose}>Vorschau schließen</button></div> }));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const photos = [{ id: '1', file_url: '/uploads/photo.png', caption: 'Haus' }];
beforeEach(() => { vi.resetAllMocks(); access.canEdit = true; access.confirm.mockResolvedValue(true); localStorage.setItem('access_token', 'photo-session'); });
afterEach(() => { cleanup(); localStorage.clear(); });

it('prepares many thumbnails with one active session check before starting any image', async () => {
  const access = deferred();
  api.get.mockImplementation(path => path === '/auth/me' ? access.promise : Promise.resolve(Array.from({ length: 10 }, (_, id) => ({ ...photos[0], id }))));
  render(<PhotoDropZone entityType="property" entityId="one" />);
  await waitFor(() => expect(api.get.mock.calls.filter(([path]) => path === '/auth/me')).toHaveLength(1));
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  await act(async () => { access.resolve({ id: 'reader' }); });
  expect(await screen.findAllByRole('img')).toHaveLength(10);
});

it('remounts a failed image after a newly prepared retry', async () => {
  api.get.mockImplementation(path => Promise.resolve(path === '/auth/me' ? {} : photos));
  render(<PhotoDropZone entityType="property" entityId="one" />);
  const broken = await screen.findByRole('img');
  fireEvent.error(broken);
  fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
  await waitFor(() => expect(screen.getByRole('img')).not.toBe(broken));
  expect(api.get.mock.calls.filter(([path]) => path === '/auth/me')).toHaveLength(2);
});

it('does not let an old entity response populate the new entity thumbnails', async () => {
  const old = deferred();
  api.get.mockImplementation(path => path.includes('entity_id=one') ? old.promise : Promise.resolve(path === '/auth/me' ? {} : [{ ...photos[0], caption: 'Neues Haus' }]));
  const view = render(<PhotoDropZone entityType="property" entityId="one" />);
  view.rerender(<PhotoDropZone entityType="property" entityId="two" />);
  await screen.findByRole('img', { name: 'Neues Haus' });
  await act(async () => { old.resolve(photos); });
  expect(screen.queryByRole('img', { name: 'Haus' })).not.toBeInTheDocument();
});

it('keeps a partial upload visible, reports the failed filename and refreshes the list', async () => {
  api.get.mockImplementation(path => Promise.resolve(path === '/auth/me' ? {} : photos));
  api.upload.mockResolvedValueOnce({ id: 'new' }).mockRejectedValueOnce(new Error('Kein Speicherplatz'));
  render(<PhotoDropZone entityType="property" entityId="one" />);
  const files = [new File(['one'], 'Ansicht.png', { type: 'image/png' }), new File(['two'], 'Hof.png', { type: 'image/png' })];
  fireEvent.change(screen.getByLabelText('Fotos auswählen'), { target: { files } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Hof.png: Kein Speicherplatz');
  expect(screen.getByRole('status')).toHaveTextContent('1 von 2 Fotos gespeichert.');
  expect(api.upload).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Fotos hinzufügen' })).not.toBeDisabled());
  expect(api.get.mock.calls.filter(([path]) => path.startsWith('/photos?'))).toHaveLength(2);
});

it('does not submit another queued file after its entity was closed, and blocks double selection', async () => {
  const first = deferred();
  api.get.mockResolvedValue([]); api.upload.mockReturnValue(first.promise);
  const view = render(<PhotoDropZone entityType="property" entityId="one" />);
  const files = [new File(['one'], 'eins.png'), new File(['two'], 'zwei.png')];
  fireEvent.change(screen.getByLabelText('Fotos auswählen'), { target: { files } });
  fireEvent.change(screen.getByLabelText('Fotos auswählen'), { target: { files } });
  expect(api.upload).toHaveBeenCalledTimes(1);
  view.rerender(<PhotoDropZone entityType="property" entityId="two" />);
  await act(async () => first.resolve({ id: 'saved' }));
  expect(api.upload).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('reports a failed deletion without removing its preview and gives readers only preview tools', async () => {
  api.get.mockImplementation(path => Promise.resolve(path === '/auth/me' ? {} : photos));
  api.del.mockRejectedValue(new Error('Löschen fehlgeschlagen'));
  const view = render(<PhotoDropZone entityType="property" entityId="one" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Foto löschen: Haus' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Löschen fehlgeschlagen');
  expect(screen.getByRole('img', { name: 'Haus' })).toBeInTheDocument();
  access.canEdit = false; view.rerender(<PhotoDropZone entityType="property" entityId="one" />);
  expect(screen.queryByRole('button', { name: /Foto löschen/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Fotos hinzufügen' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Foto ansehen: Haus' }));
  expect(screen.getByRole('dialog', { name: 'Haus' })).toBeInTheDocument();
});
