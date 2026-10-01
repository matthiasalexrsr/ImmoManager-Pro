import { api } from '../api';

export function saveBlob(blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'bookings.csv';
  link.click();
  // Keep the owned URL alive until the browser has begun its download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function streamBookingCsv(path, { signal } = {}) {
  if (!path.startsWith('/bookings/export.csv?')) throw new Error('Ungültiger Exportpfad.');
  const handle = await window.showSaveFilePicker({ suggestedName: 'bookings.csv', types: [{
    description: 'CSV', accept: { 'text/csv': ['.csv'] },
  }] });
  const writable = await handle.createWritable();
  try {
    const read = () => fetch(`/api/v1${path}`, { signal, headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') || ''}`,
    } });
    let response = await read();
    if (response.status === 401) {
      // Use the existing refresh serialization; the retry remains same-origin.
      await api.get('/auth/me', { signal });
      response = await read();
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body?.error?.message || 'CSV konnte nicht geladen werden.');
    }
    if (!response.body) throw new Error('Der Browser stellt keinen Downloadstream bereit.');
    await response.body.pipeTo(writable, { signal });
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
}
