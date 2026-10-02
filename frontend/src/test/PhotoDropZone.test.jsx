import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import PhotoDropZone from '../components/PhotoDropZone';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: 'eigentuemer' }) }));
vi.mock('../api', () => ({ api: { get: vi.fn(), getBlob: vi.fn(), postForm: vi.fn(), del: vi.fn() } }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
const png = () => new Blob([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], { type: 'image/png' });

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn().mockReturnValue('blob:private-photo');
  URL.revokeObjectURL = vi.fn();
  api.getBlob.mockResolvedValue(png());
});

it('preserves existing protected photos across an upload failure and a successful retry', async () => {
  const saved = { id: 'saved', file_url: '/uploads/photos/saved.png', caption: 'Saved photo' };
  api.get.mockResolvedValue([saved]);
  api.postForm.mockRejectedValueOnce(new Error('Upload vorübergehend fehlgeschlagen')).mockResolvedValueOnce({ id: 'new' });
  render(<PhotoDropZone entityType="unit" entityId="unit-1" />);
  await screen.findByAltText('Saved photo');
  expect(screen.getByAltText('Saved photo')).toHaveAttribute('src', 'blob:private-photo');
  const input = screen.getByLabelText('Fotos hochladen');
  const file = new File([png()], 'photo.png', { type: 'image/png' });
  fireEvent.change(input, { target: { files: [file] } });
  await screen.findByText('Upload vorübergehend fehlgeschlagen');
  expect(screen.getByAltText('Saved photo')).toBeInTheDocument();
  fireEvent.change(input, { target: { files: [file] } });
  await waitFor(() => expect(api.postForm).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  expect(api.postForm.mock.calls[1][0]).toBe('/photos/upload?entity_type=unit&entity_id=unit-1');
  expect(api.postForm.mock.calls[1][1].get('file').name).toBe('photo.png');
  expect(screen.getByAltText('Saved photo')).toBeInTheDocument();
});

it('aborts old entity reads and never displays late photos in a different unit', async () => {
  let finish;
  api.get.mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce([]);
  const view = render(<PhotoDropZone entityType="unit" entityId="old" />);
  const signal = api.get.mock.calls[0][1].signal;
  view.rerender(<PhotoDropZone entityType="unit" entityId="new" />);
  await act(async () => finish([{ id: 'private-old', file_url: '/uploads/photos/old.png', caption: 'Old private photo' }]));
  expect(signal.aborted).toBe(true);
  expect(screen.queryByAltText('Old private photo')).not.toBeInTheDocument();
  expect(api.getBlob).not.toHaveBeenCalled();
});
