import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Meters from '../pages/Meters';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => true }));
const none = vi.hoisted(() => []);                         // stable, as the data store hands out the same list
vi.mock('../contexts/DataStoreContext', () => ({ useEntities: () => ({ items: none }), useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));

const meter = { id: 'm1', unit_id: 'u1', meter_type: 'cold_water', measure_unit: 'm³', serial_number: 'WZ 26958890', is_active: true };
const reading = { id: 'rp', revision: 1, surface: 'meter_photo', reader: 'claude', reader_label: 'Claude', status: 'open', chat: true,
  changed: ['serial', 'value', 'reading_date'], duplicates: [], decision: null, questions: [], notes: ['Rote Ziffern: 0,6'], dropped: [],
  confirm_mode: 'confirm', file: { name: 'zaehler.jpg' }, meter: { id: 'm1', label: 'WZ 26958890' },
  messages: [{ id: 'a', role: 'assistant', text: 'Kaltwasserzähler 26958890, Stand 647.', changed: ['value'] }],
  values: { serial: { value: '26958890', evidence: '26958890', confidence: 'high', source: 'claude' },
    value: { value: '647', evidence: '00647', confidence: 'medium', source: 'claude' },
    reading_date: { value: '2026-10-20', evidence: 'Display 20.10.26', confidence: 'low', source: 'claude' } } };

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockImplementation(path => Promise.resolve(path === '/meters' ? [meter] : []));
  api.get.mockImplementation(path => path.startsWith('/ai/readings/options') ? Promise.resolve({
    readers: [{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }, { id: 'claude', label: 'Claude', available: true, ai: true }],
    default_reader: 'auto', ai_enabled: true, chat: true, confirm_mode: 'confirm',
    surfaces: [{ id: 'meter_photo', label: 'Zählerfoto', may_use: true, ai_allowed: true, needs_ai: true,
      fields: [{ name: 'serial', label: 'Gerätenummer', kind: 'text' }, { name: 'value', label: 'Zählerstand', kind: 'number' },
        { name: 'reading_date', label: 'Ablesedatum', kind: 'date' }] }] }) : Promise.reject(new Error(`unexpected ${path}`)));
  api.upload.mockResolvedValue({ file_url: '/uploads/meter-photos/zaehler.jpg' });
  api.post.mockImplementation(path => Promise.resolve(path === '/ai/readings' ? reading : path === '/meters/m1/readings' ? { id: 'rd1' } : {}));
});
afterEach(cleanup);

describe('Zählerstand aus Foto', () => {
  it('liest das Foto mit der KI, wählt den Zähler über die Gerätenummer und speichert nach Bestätigung', async () => {
    render(<MemoryRouter><Meters /></MemoryRouter>);
    await screen.findByText('WZ 26958890');
    fireEvent.change(screen.getByLabelText('Zählerfoto wählen'), { target: { files: [new File(['jpg'], 'zaehler.jpg', { type: 'image/jpeg' })] } });
    const dialog = await screen.findByRole('dialog', { name: 'Zählerstand aus Foto' });
    expect(api.upload).toHaveBeenCalledWith('/files/upload?folder=meter-photos', expect.any(FormData));
    await waitFor(() => expect(within(dialog).getByRole('radio', { name: /Claude/ })).toBeChecked());
    expect(within(dialog).getByRole('radio', { name: /Lokale Regeln/ })).toBeDisabled();          // a photo needs the AI
    fireEvent.click(within(dialog).getByRole('button', { name: /Einlesen/ }));
    expect(await within(dialog).findByText('Rote Ziffern: 0,6')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ablesung prüfen und speichern' }));
    const form = await screen.findByRole('dialog', { name: 'Ablesung erfassen' });
    expect(within(form).getByLabelText(/^Zähler/, { selector: 'select' })).toHaveValue('m1');
    expect(within(form).getByLabelText(/^Zählerstand/, { selector: 'input' })).toHaveValue(647);
    expect(within(form).getByText('3 noch zu bestätigen')).toBeInTheDocument();
    expect(within(form).getByText(/unsicher – bitte genau prüfen/)).toBeInTheDocument();
    fireEvent.click(within(form).getByRole('button', { name: 'Alle bestätigen' }));
    fireEvent.submit(form.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/meters/m1/readings', expect.objectContaining({ meter_id: 'm1', value: 647,
      reading_date: '2026-10-20' })));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/readings/rp/finish', expect.objectContaining({
      outcome: 'taken_over', record_kind: 'meter_reading', record_id: 'rd1' })));
  });
});
