import { api } from '../api';

export async function streamBankOriginal(path, filename, { signal } = {}) {
  if (!/^\/bookings\/imports\/[A-Za-z0-9_-]+\/source$/.test(path)) throw new Error('bankImport.invalidResponse');
  const handle = await window.showSaveFilePicker({ suggestedName: filename });
  const writable = await handle.createWritable();
  try {
    const read = () => fetch(`/api/v1${path}`, { signal, headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') || ''}`,
    } });
    let response = await read();
    if (response.status === 401) {
      await api.get('/auth/me', { signal });
      response = await read();
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body?.error?.message || 'bankImport.sourceFailed');
    }
    if (!response.body) throw new Error('bankImport.sourceUnsupported');
    await response.body.pipeTo(writable, { signal });
  } catch (failure) {
    await writable.abort().catch(() => {});
    throw failure;
  }
}
