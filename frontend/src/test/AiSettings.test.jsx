import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AiSettingsSection from '../pages/settings/AiSettingsSection';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), put: vi.fn(), list: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: false }) }));
vi.mock('../contexts/PreferencesContext', () => ({ usePreferences: () => null }));
afterEach(cleanup);

const options = {
  readers: [{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }, { id: 'claude', label: 'Claude', available: true, ai: true },
    { id: 'codex', label: 'ChatGPT', available: false, ai: true }],
  ai_enabled: true, chat: true, confirm_mode: 'confirm', default_reader: 'auto',
  policy: { send_images: true, max_pages: 4, context: 'standard', keep_days: 30, check_duplicates: true, calls_per_window: 40, window_minutes: 10 },
  surfaces: [{ id: 'invoice', label: 'Rechnungseingang', entry: 'Rechnungsprüfung → Rechnung erfassen → Beleg einlesen', purpose: 'Liest Rechnungen.',
    needs_ai: false, may_use: true, ai_allowed: true }, { id: 'meter_photo', label: 'Zählerfoto', entry: 'Zähler → Stand aus Foto',
    purpose: 'Liest Zählerfotos.', needs_ai: true, may_use: false, ai_allowed: false }],
};
const items = [
  { key: 'ai_confirm_mode', label: 'Von der KI eingetragene Werte in der Maske', value: 'confirm', origin: 'default', scope: 'personal',
    editable: true, revision: 1, group: 'KI-Verarbeitung', choices: [{ value: 'confirm', label: 'Jeden Wert vor dem Speichern bestätigen' },
      { value: 'mark', label: 'Nur markieren (KI, geändert, neu)' }] },
  { key: 'theme', label: 'Darstellung', value: 'light', origin: 'default', scope: 'personal', editable: true, revision: 1, group: 'Ansicht und Arbeitsweise' },
];

describe('Einstellungen zur KI-Verarbeitung', () => {
  it('erklärt, was an die KI geht, zeigt Verbindungen, Stellen und nur die KI-Einstellungen in Worten', async () => {
    api.get.mockResolvedValue({ items });
    const service = { options: vi.fn().mockResolvedValue(options) };
    render(<MemoryRouter><AiSettingsSection service={service} /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'KI-Verarbeitung' })).toBeInTheDocument();
    expect(screen.getByText(/bis zu 4 Seitenbilder/)).toBeInTheDocument();
    expect(screen.getByText(/nach 30 Tagen gelöscht/)).toBeInTheDocument();
    const readers = screen.getByRole('heading', { name: 'Verbindungen' }).closest('.panel');
    expect(within(readers).getByText('Claude').parentElement).toHaveTextContent('verbunden');
    expect(within(readers).getByText('ChatGPT').parentElement).toHaveTextContent('nicht verbunden');
    const table = screen.getByRole('table');
    expect(within(table).getByText('Zähler → Stand aus Foto')).toBeInTheDocument();
    expect(within(table).getByText('nicht in Ihrer Rolle')).toBeInTheDocument();
    expect(screen.getByRole('note', { name: 'Datenschutz' })).toHaveTextContent('Art. 28');
    const mode = screen.getByLabelText('Von der KI eingetragene Werte in der Maske');
    expect(within(mode).getByRole('option', { name: 'Jeden Wert vor dem Speichern bestätigen' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Darstellung')).toBeNull();
    expect(screen.getByText(/legt die Verwaltung fest/)).toBeInTheDocument();
  });
});
