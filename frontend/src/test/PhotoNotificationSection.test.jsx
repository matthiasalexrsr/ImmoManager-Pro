import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import usePhotoNotification from '../hooks/usePhotoNotification';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: () => () => {} } }));
const source = overrides => ({ source: { kind: 'entity_photo', entity_id: 'photo1',
  href: '/properties/p1?source_id=photo1', values: { entity_type: 'property', entity_id: 'p1' }, ...overrides } });
function Section() {
  const result = usePhotoNotification('property', 'p1');
  const navigate = useNavigate();
  return <><output>{result.open ? 'Fotobereich geöffnet' : 'Fotobereich geschlossen'}</output>
    {result.error && <div role="alert">{result.error}<button onClick={result.retry}>Wiederholen</button></div>}
    <button onClick={() => navigate('/properties/p1?notice_id=n2&source_id=photo2')}>Anderer Hinweis</button></>;
}
const show = () => render(<MemoryRouter initialEntries={['/properties/p1?notice_id=n1&source_id=photo1']}><Section /></MemoryRouter>);
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);
describe('opening a photo notification section', () => {
  it('opens only the verified photo section and never archives a notice itself', async () => {
    api.get.mockResolvedValue(source()); show();
    expect(await screen.findByText('Fotobereich geöffnet')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each([
    { kind: 'property' }, { entity_id: 'different' }, { href: '//foreign.example/properties/p1?source_id=photo1' },
    { href: '/properties/p2?source_id=photo1' }, { values: { entity_type: 'unit', entity_id: 'p1' } },
  ])('rejects an unrelated or invalid target %j', async overrides => {
    api.get.mockResolvedValue(source(overrides)); show();
    await act(async () => {});
    expect(screen.getByText('Fotobereich geschlossen')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('keeps the source unread when loading fails and offers a retry', async () => {
    api.get.mockRejectedValueOnce(new Error('Quelle nicht erreichbar')).mockResolvedValue(source()); show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Quelle nicht erreichbar');
    fireEvent.click(screen.getByRole('button', { name: 'Wiederholen' }));
    expect(await screen.findByText('Fotobereich geöffnet')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('discards a late response from a previously selected notification', async () => {
    let release;
    api.get.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }))
      .mockResolvedValue(source({ kind: 'document', entity_id: 'photo2' }));
    show();
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    const oldSignal = api.get.mock.calls[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: 'Anderer Hinweis' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(oldSignal.aborted).toBe(true);
    await act(async () => release(source()));
    expect(screen.getByText('Fotobereich geschlossen')).toBeInTheDocument();
  });
});
