import { beforeEach, describe, expect, it, vi } from 'vitest';
import { detailFixture } from './handoverFixtures';

const api = vi.hoisted(() => ({
  get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), postBlob: vi.fn(),
  upload: vi.fn(),
}));
vi.mock('../api', () => ({ api }));
vi.mock('../features/partyWorkspace/files', () => ({ downloadFile: vi.fn(async () => {}) }));

import { handoverProtocolService as service } from '../features/handoverProtocol/handoverProtocolApi';
import { downloadFile } from '../features/partyWorkspace/files';

const HASH = 'a'.repeat(64);

describe('handover protocol API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('asks for the proposal of one contract and kind', async () => {
    api.get.mockResolvedValue({});
    await service.source('c 1', 'move_in');
    expect(api.get.mock.calls[0][0]).toBe('/handover-protocols/source?contract_id=c+1&protocol_type=move_in');
  });

  it('creates from the contract and refuses an answer that is no protocol detail', async () => {
    api.post.mockResolvedValueOnce({ created: true, ...detailFixture() });
    expect((await service.create('c-1', 'move_out', '2026-06-30')).created).toBe(true);
    expect(api.post.mock.calls[0].slice(0, 2)).toEqual(['/handover-protocols/from-contract',
      { contract_id: 'c-1', protocol_type: 'move_out', protocol_date: '2026-06-30' }]);
    api.post.mockResolvedValueOnce({ protocol: { id: 'p' } });
    await expect(service.create('c-1', 'move_out')).rejects.toThrow('invalid_handover_detail');
  });

  it('uploads photos as multipart through the session-aware client', async () => {
    api.upload.mockResolvedValue({ id: 'ph-1' });
    const file = new File(['x'], 'a.png', { type: 'image/png' });
    await service.uploadPhoto('p/1', file, { defectId: 'd-1', caption: 'Loch' });
    const [path, form] = api.upload.mock.calls[0];
    expect(path).toBe('/handover-protocols/p%2F1/photos');
    expect(form).toBeInstanceOf(FormData);
    expect(form.get('file')).toBe(file);
    expect(form.get('defect_id')).toBe('d-1');
    expect(form.get('caption')).toBe('Loch');
    expect(form.get('room_id')).toBeNull();
  });

  it('finalizes with the reviewed hash and both confirmations only', async () => {
    api.post.mockResolvedValue(detailFixture());
    await service.finalize('p-1', { idempotencyKey: 'handover:1', reviewHash: HASH });
    expect(api.post.mock.calls[0].slice(0, 2)).toEqual(['/handover-protocols/p-1/finalize', {
      idempotency_key: 'handover:1', review_hash: HASH, confirmed_content: true, confirmed_signatures: true }]);
    await expect(service.finalize('p-1', { idempotencyKey: 'k', reviewHash: 'nope' })).rejects.toThrow();
  });

  it('checks the preview answer and the PDF bytes', async () => {
    api.post.mockResolvedValueOnce({ review_hash: HASH, pdf_sha256: HASH, problems: [] });
    expect((await service.preview('p-1')).review_hash).toBe(HASH);
    api.post.mockResolvedValueOnce({ review_hash: 'x' });
    await expect(service.preview('p-1')).rejects.toThrow('invalid_handover_preview');
    api.postBlob.mockResolvedValueOnce(new Blob(['<html>'], { type: 'text/html' }));
    await expect(service.previewPdfUrl('p-1', { pdf_sha256: HASH })).rejects.toThrow('kein PDF');
  });

  it('downloads the original under a readable name', async () => {
    const detail = detailFixture({ original: { file_url: '/uploads/handover-protocols/d-1.pdf' } });
    await service.downloadOriginal(detail);
    expect(downloadFile).toHaveBeenCalledWith('/uploads/handover-protocols/d-1.pdf',
      'Uebergabeprotokoll-Auszug-V-1-2026-06-30.pdf', expect.anything());
  });
});
