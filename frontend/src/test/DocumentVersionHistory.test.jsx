import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Blob as NodeBlob } from 'node:buffer';
import { webcrypto } from 'node:crypto';
import DocumentVersionHistory from '../components/DocumentVersionHistory';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn(), getBlob: vi.fn(), confirm: vi.fn(),
  role: 'verwalter', userId: 'actor', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: mocks.userId, role: mocks.role } }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => {
  const translate = (key, params = {}) => (key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key)
    .replace(/\{\{(\w+)\}\}/g, (match, name) => params[name] ?? match);
  return { useTranslation: () => ({ locale: mocks.locale, t: translate }) };
});

const labels = de.pages.documents.versions;
const digest = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'; // SHA256 abc
const row = (number = 1, changes = {}) => ({ id: `version-${number}`, document_id: 'document', number, predecessor_id: number > 1 ? `version-${number - 1}` : null,
  restored_from_id: null, actor_id: 'actor', comment: 'Synthetic reviewed change', filename: 'reviewed.txt', sha256: digest,
  size_bytes: 3, created_at: '2026-10-01T12:00:00Z', metadata_snapshot: { title: 'Synthetic original', tags: 'reviewed' }, ...changes });
const history = (head = row(), items = head ? [head] : []) => ({ document_id: 'document', document_etag: 'etag-original',
  head, items, next_before: null, persistent: true });
const source = { document_etag: 'etag-original', filename: 'original.txt', sha256: digest, size_bytes: 3 };
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = (props = {}) => <DocumentVersionHistory document={{ id: 'document', title: 'Synthetic source' }} onClose={vi.fn()} {...props} />;
const writeDraft = async () => {
  const input = await screen.findByLabelText(labels.comment);
  fireEvent.change(input, { target: { value: 'Explicit reason retained' } });
  const file = new File(['abc'], 'new.txt', { type: 'text/plain', lastModified: 100 });
  fireEvent.change(screen.getByLabelText(labels.newFile), { target: { files: [file] } });
  return file;
};

beforeEach(() => {
  mocks.role = 'verwalter'; mocks.userId = 'actor'; mocks.locale = 'de-DE';
  mocks.get.mockReset().mockImplementation(async path => path.endsWith('/version-source') ? source : history());
  mocks.post.mockReset().mockResolvedValue(row(2)); mocks.postForm.mockReset().mockResolvedValue(row(2));
  mocks.getBlob.mockReset().mockResolvedValue(new NodeBlob(['abc'], { type: 'application/octet-stream' }));
  mocks.confirm.mockReset().mockResolvedValue(true);
  vi.stubGlobal('Blob', NodeBlob); vi.stubGlobal('crypto', webcrypto);
  URL.createObjectURL = vi.fn().mockReturnValue('blob:version'); URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('immutable document history', () => {
  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('shows readable evidence in %s with readonly downloads', async (locale, catalog) => {
    mocks.locale = locale; mocks.role = 'readonly';
    const text = catalog.pages.documents.versions;
    const { container } = render(view());
    await screen.findByRole('button', { name: text.download });
    expect(container).toHaveTextContent(text.originalPolicy);
    expect(screen.queryByLabelText(text.comment)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.publish })).not.toBeInTheDocument();
    expect(container.textContent).not.toContain('pages.documents.versions.');
    expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.postForm).not.toHaveBeenCalled();
  });

  it('requires preview and explicit confirmation before preserving the original', async () => {
    mocks.get.mockImplementation(async path => path.endsWith('/version-source') ? source : history(null));
    mocks.post.mockResolvedValue(row());
    render(view());
    fireEvent.change(await screen.findByLabelText(labels.comment), { target: { value: 'Archive reviewed original' } });
    expect(screen.getByRole('button', { name: labels.archive })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: labels.reviewOriginal }));
    await screen.findByText(`SHA256 ${digest}`);
    mocks.confirm.mockResolvedValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: labels.archive }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(1));
    expect(mocks.post).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('button', { name: labels.archive })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: labels.archive }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][0]).toBe('/documents/document/versions/archive-original');
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ expected_head_id: null, expected_document_etag: 'etag-original',
      expected_sha256: digest, confirmed: true, comment: 'Archive reviewed original' });
  });

  it('preserves draft and the same command reference after a lost upload response', async () => {
    mocks.postForm.mockRejectedValueOnce(new Error('Synthetic lost response')).mockResolvedValueOnce(row(2));
    render(view()); const file = await writeDraft();
    fireEvent.click(screen.getByRole('button', { name: labels.publish }));
    await screen.findByText('Synthetic lost response');
    expect(screen.getByLabelText(labels.comment)).toHaveValue('Explicit reason retained');
    expect(screen.getByLabelText(labels.newFile).files[0]).toBe(file);
    const first = JSON.parse(mocks.postForm.mock.calls[0][1].get('command'));
    fireEvent.click(screen.getByRole('button', { name: labels.publish }));
    await waitFor(() => expect(mocks.postForm).toHaveBeenCalledTimes(2));
    const retry = JSON.parse(mocks.postForm.mock.calls[1][1].get('command'));
    expect(retry).toEqual(first);
    await screen.findByText(labels.saved.replace('{{number}}', '2'));
    expect(screen.getByLabelText(labels.comment)).toHaveValue('');
  });

  it('blocks duplicate submissions and all close paths while a command is pending', async () => {
    const delivery = pending(); mocks.postForm.mockReturnValue(delivery.promise);
    const onClose = vi.fn(); render(view({ onClose })); await writeDraft();
    const form = screen.getByLabelText(labels.comment).closest('form');
    fireEvent.submit(form); fireEvent.submit(form);
    await waitFor(() => expect(mocks.postForm).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(screen.getByRole('button', { name: labels.close }));
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(screen.getByRole('dialog').parentElement);
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => delivery.resolve(row(2)));
  });

  it('rechecks the current role after a pending confirmation', async () => {
    const decision = pending(); mocks.confirm.mockReturnValue(decision.promise);
    const rendered = render(view()); await writeDraft();
    fireEvent.click(screen.getByRole('button', { name: labels.publish }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(1));
    mocks.role = 'readonly'; rendered.rerender(view());
    await act(async () => decision.resolve(true));
    expect(mocks.postForm).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(labels.comment)).not.toBeInTheDocument();
  });

  it('uses an explicit restore command, predecessor CAS and source receipt', async () => {
    mocks.get.mockResolvedValue(history(row(2), [row(2), row()]));
    render(view());
    fireEvent.change(await screen.findByLabelText(labels.comment), { target: { value: 'Restore reviewed earlier bytes' } });
    fireEvent.click(screen.getByRole('button', { name: labels.restore }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][0]).toBe('/documents/document/versions/restore');
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ source_version_id: 'version-1', expected_head_id: 'version-2', confirmed: true });
  });

  it('compares stored hashes and metadata without reading live OCR', async () => {
    mocks.role = 'readonly';
    mocks.get.mockResolvedValue(history(row(2), [row(2, { metadata_snapshot: { title: 'New title' } }), row()]));
    render(view()); await screen.findByRole('button', { name: labels.refresh });
    await screen.findByLabelText(labels.compareVersion.replace('{{number}}', '2'));
    fireEvent.click(screen.getByLabelText(labels.compareVersion.replace('{{number}}', '2')));
    fireEvent.click(screen.getByLabelText(labels.compareVersion.replace('{{number}}', '1')));
    await screen.findByText(labels.sameBytes);
    expect(screen.getByText('New title → Synthetic original')).toBeInTheDocument();
    expect(mocks.get.mock.calls.every(([path]) => !path.includes('ocr'))).toBe(true);
  });

  it('paginates with bounded keyset requests instead of loading all history', async () => {
    mocks.role = 'readonly';
    mocks.get.mockImplementation(async path => path.includes('before=2') ? history(row(3), [row()]) : { ...history(row(3), [row(3), row(2)]), next_before: 2 });
    render(view()); fireEvent.click(await screen.findByRole('button', { name: labels.next }));
    await screen.findByRole('heading', { name: labels.version.replace('{{number}}', '1') });
    expect(mocks.get.mock.calls.at(-1)[0]).toBe('/documents/document/versions?limit=25&before=2');
    fireEvent.click(screen.getByRole('button', { name: labels.previous }));
    await waitFor(() => expect(mocks.get.mock.calls.at(-1)[0]).toBe('/documents/document/versions?limit=25'));
  });

  it('downloads only a complete matching Blob through a constructed authenticated route', async () => {
    mocks.role = 'readonly'; mocks.get.mockResolvedValue(history(row(1, { download_url: 'https://foreign.test/file' })));
    render(view()); fireEvent.click(await screen.findByRole('button', { name: labels.download }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(mocks.getBlob.mock.calls[0][0]).toBe('/documents/document/versions/version-1/download');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:version');
  });

  it.each(['wrong-bytes', 'html', 'json'])('refuses a %s download without creating a success file', async mode => {
    mocks.role = 'readonly';
    mocks.getBlob.mockResolvedValue(new NodeBlob([mode === 'wrong-bytes' ? 'bad' : 'abc'], { type: mode === 'html' ? 'text/html' : mode === 'json' ? 'application/json' : 'application/octet-stream' }));
    render(view()); fireEvent.click(await screen.findByRole('button', { name: labels.download }));
    await screen.findByRole('alert');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('retains a failed malformed publication draft and shows no saved receipt', async () => {
    mocks.postForm.mockResolvedValue({ id: 'incomplete' });
    render(view()); await writeDraft();
    fireEvent.click(screen.getByRole('button', { name: labels.publish }));
    await screen.findByText(labels.invalidResponse);
    expect(screen.getByLabelText(labels.comment)).toHaveValue('Explicit reason retained');
    expect(screen.queryByText(labels.saved.replace('{{number}}', '2'))).not.toBeInTheDocument();
  });

  it.each([401, 403, 404])('clears prior evidence after a current %i permission/ownership failure', async statusCode => {
    mocks.role = 'readonly';
    render(view()); await screen.findByRole('button', { name: labels.download });
    mocks.get.mockRejectedValue(Object.assign(new Error('Rights changed'), { statusCode }));
    fireEvent.click(screen.getByRole('button', { name: labels.refresh }));
    await screen.findByText('Rights changed');
    expect(screen.queryByRole('button', { name: labels.download })).not.toBeInTheDocument();
  });

  it('restores opener focus, traps keyboard focus and aborts a stale request on close', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus();
    mocks.role = 'readonly';
    const rendered = render(view()); await screen.findByRole('button', { name: labels.download });
    const close = screen.getByRole('button', { name: labels.close }); close.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole('checkbox'));
    const signal = mocks.get.mock.calls[0][1].signal;
    rendered.unmount(); expect(signal.aborted).toBe(true); expect(document.activeElement).toBe(opener); opener.remove();
  });

  it('does not carry an unfinished file/comment into a different actor', async () => {
    const rendered = render(view()); await writeDraft();
    mocks.userId = 'another-actor'; rendered.rerender(view());
    await waitFor(() => expect(screen.getByLabelText(labels.comment)).toHaveValue(''));
    expect(screen.getByLabelText(labels.newFile).files.length).toBe(0);
    expect(mocks.postForm).not.toHaveBeenCalled();
  });
});
