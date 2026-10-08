import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import PhotoDropZone from '../components/PhotoDropZone';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), del: vi.fn() } }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const photos = [{ id: '1', file_url: '/uploads/photo.png', caption: 'Haus' }];
beforeEach(() => { vi.resetAllMocks(); localStorage.setItem('access_token', 'photo-session'); });
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
