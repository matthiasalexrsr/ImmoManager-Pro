import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFECT, ROOM, detailFixture } from './handoverFixtures';

const authState = vi.hoisted(() => ({ user: null, write: null }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url, title }) => <div data-testid="pdf">{title}|{url}</div> }));
vi.mock('../utils/uploadAccess', () => ({ prepareUploadAccess: vi.fn(async () => {}), isOwnUploadUrl: () => true }));

import HandoverProtocolEditor from '../features/handoverProtocol/HandoverProtocolEditor';

const HASH = 'a'.repeat(64);

function finalized(detail) {
  return {
    ...detail,
    protocol: { ...detail.protocol, status: 'finalized', finalized_at: '2026-07-01T10:00:00', document_id: 'doc-1',
      revision: '"rev-final"' },
    state: { ...detail.state, finalized: true, editable: false },
    original: { document_id: 'doc-1', version_id: 'v-1', pdf_sha256: 'b'.repeat(64), content_matches: true,
      file_url: '/uploads/handover-protocols/doc-1.pdf', missing: false },
  };
}

const correctionDraft = () => detailFixture({ protocol: { ...detailFixture().protocol, id: 'p-2',
  correction_of_id: 'p-1', revision: '"rev-c"' }, correction_of: { id: 'p-1', protocol_date: '2026-06-30' } });

function service(overrides = {}, initial = detailFixture()) {
  let current = initial;
  return {
    load: vi.fn(async id => (id === 'p-2' ? correctionDraft() : current)),
    save: vi.fn(async (_id, payload) => {
      current = { ...current, protocol: { ...current.protocol, revision: '"rev-2"', notes: payload.notes },
        rooms: payload.rooms.map((room, position) => ({ ...room, protocol_id: 'p-1', position })),
        defects: payload.defects.map((defect, position) => ({ ...defect, protocol_id: 'p-1', position,
          resolved_at: null, resolution_note: null })),
        meter_readings: payload.meter_readings.map(r => ({ ...r, handover_id: 'p-1', meter_type: r.meter_type || 'cold_water',
          unit: r.unit || 'm³' })) };
      return current;
    }),
    uploadPhoto: vi.fn(async () => {
      current = { ...current, photos: [{ id: 'ph-1', protocol_id: 'p-1', defect_id: DEFECT, room_id: null,
        meter_reading_id: null, file_url: '/uploads/handover-photos/p-1/a.png', caption: null, sha256: HASH }] };
      return current.photos[0];
    }),
    deletePhoto: vi.fn(async () => null),
    preview: vi.fn(async () => ({ review_hash: HASH, pdf_sha256: 'c'.repeat(64), size_bytes: 900,
      revision: current.protocol.revision, ready: true,
      problems: [{ code: 'METER_NOT_READ', message: 'Ohne Stand: KW-1.', blocking: false }],
      counts: { rooms: 1, defects: 1, keys: 1, meter_readings: 0, photos: 0 } })),
    previewPdfUrl: vi.fn(async () => 'blob:preview'),
    finalize: vi.fn(async () => { current = finalized(current); return current; }),
    startCorrection: vi.fn(async () => correctionDraft()),
    followUp: vi.fn(async (_id, defectId, values) => {
      current = { ...current, defects: current.defects.map(d => (d.id === defectId ? { ...d, ...values } : d)) };
      return current;
    }),
    downloadOriginal: vi.fn(async () => {}),
    ...overrides,
  };
}

async function openEditor(api, props = {}) {
  render(<StrictMode><HandoverProtocolEditor protocolId="p-1" service={api} onClose={vi.fn()} {...props} /></StrictMode>);
  await screen.findByText('V-1 · Bautzner Straße 61 · WE 3');
}

describe('HandoverProtocolEditor', () => {
  beforeEach(() => {
    authState.user = { id: 'manager-1', role: 'verwalter' };
    authState.write = null;
  });

  it('edits rooms, defects, keys and meters and saves the whole draft', async () => {
    const api = service();
    const changed = vi.fn();
    await openEditor(api, { onChanged: changed });
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Raum 1'), { target: { value: 'Wohnküche' } });
    fireEvent.click(screen.getByRole('button', { name: 'Raum hinzufügen' }));
    fireEvent.change(screen.getByLabelText('Raum 2'), { target: { value: 'Balkon' } });
    fireEvent.change(screen.getByLabelText('Zurückgegeben 1'), { target: { value: '2' } });
    expect(screen.getByText('Fehlend: 1')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Stand KW-1'), { target: { value: '130,5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    await screen.findByText('Gespeichert.');
    const [id, payload] = api.save.mock.calls[0];
    expect(id).toBe('p-1');
    expect(payload.base_revision).toBe('"rev-1"');
    expect(payload.rooms.map(room => room.name)).toEqual(['Wohnküche', 'Balkon']);
    expect(payload.keys[0]).toMatchObject({ handed_over: 3, returned: 2 });
    expect(payload.meter_readings).toEqual([expect.objectContaining({ meter_id: 'm-1', reading_value: 130.5 })]);
    expect(changed).toHaveBeenCalled();
  });

  it('refuses to save rows it cannot send and keeps the input', async () => {
    const api = service();
    await openEditor(api);
    fireEvent.change(screen.getByLabelText('Beschreibung 1'), { target: { value: ' ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Jeder Mangel braucht eine Beschreibung.');
    expect(api.save).not.toHaveBeenCalled();
  });

  it('saves first, then uploads a defect photo', async () => {
    const api = service();
    await openEditor(api);
    fireEvent.change(screen.getByLabelText('Vereinbarung 1'), { target: { value: 'Mieter spachtelt' } });
    const file = new File(['png'], 'loch.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('Fotos Mängel 1', { selector: 'input' }), { target: { files: [file] } });
    await waitFor(() => expect(api.uploadPhoto).toHaveBeenCalled());
    expect(api.save).toHaveBeenCalledTimes(1);
    expect(api.save.mock.invocationCallOrder[0]).toBeLessThan(api.uploadPhoto.mock.invocationCallOrder[0]);
    expect(api.uploadPhoto.mock.calls[0][1]).toBe(file);
    expect(api.uploadPhoto.mock.calls[0][2]).toEqual({ defectId: DEFECT });
    expect(await screen.findByAltText('Foto 1')).toHaveAttribute('src', expect.stringContaining('/uploads/handover-photos/'));
  });

  it('checks, shows the PDF and finalizes only after both confirmations', async () => {
    const api = service();
    await openEditor(api);
    fireEvent.click(screen.getByRole('button', { name: 'Prüfen' }));
    await screen.findByText('Bereit zum Abschließen');
    expect(screen.getByText('Ohne Stand: KW-1.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'PDF-Vorschau öffnen' }));
    expect(await screen.findByTestId('pdf')).toHaveTextContent('Vorschau des Übergabeprotokolls|blob:preview');
    fireEvent.click(screen.getByRole('button', { name: /Zurück zum Protokoll/ }));

    const finalize = await screen.findByRole('button', { name: 'Abschließen und Original speichern' });
    expect(finalize).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/gemeinsam festgestellten Zustand/));
    fireEvent.click(screen.getByLabelText(/unterschreiben bzw. unterschrieben/));
    fireEvent.click(finalize);
    await screen.findByText(/Abgeschlossen: Das PDF ist als unveränderliches Original gespeichert/);
    const [, command] = api.finalize.mock.calls[0];
    expect(command).toEqual({ idempotencyKey: expect.stringMatching(/^handover:/), reviewHash: HASH });
    expect(screen.getByLabelText('Raum 1')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'PDF öffnen' }));
    expect(await screen.findByTestId('pdf')).toHaveTextContent('/uploads/handover-protocols/doc-1.pdf');
  });

  it('a change after the check asks to check again', async () => {
    const api = service();
    await openEditor(api);
    fireEvent.click(screen.getByRole('button', { name: 'Prüfen' }));
    await screen.findByText('Bereit zum Abschließen');
    fireEvent.change(screen.getByLabelText('Bemerkungen – Allgemein'), { target: { value: 'neu' } });
    expect(screen.getByText('Geändert: bitte erneut prüfen.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Abschließen und Original speichern' })).not.toBeInTheDocument();
  });

  it('sends the exact finalization again after a lost answer', async () => {
    const lost = Object.assign(new Error('Verbindung zum Server fehlgeschlagen.'), { isNetwork: true });
    const api = service();
    const real = api.finalize;
    api.finalize = vi.fn().mockRejectedValueOnce(lost).mockImplementation(real);
    await openEditor(api);
    fireEvent.click(screen.getByRole('button', { name: 'Prüfen' }));
    await screen.findByText('Bereit zum Abschließen');
    fireEvent.click(screen.getByLabelText(/gemeinsam festgestellten Zustand/));
    fireEvent.click(screen.getByLabelText(/unterschreiben bzw. unterschrieben/));
    fireEvent.click(screen.getByRole('button', { name: 'Abschließen und Original speichern' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Unverändert erneut senden' }));
    await screen.findByText(/Abgeschlossen: Das PDF/);
    expect(api.finalize).toHaveBeenCalledTimes(2);
    expect(api.finalize.mock.calls[1][1]).toEqual(api.finalize.mock.calls[0][1]);
  });

  it('shows a finalized protocol read-only with follow-up and correction', async () => {
    const api = service({}, finalized(detailFixture()));
    await openEditor(api);
    expect(screen.getByLabelText('Raum 1')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Erledigt am 1'), { target: { value: '2026-07-10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Erledigung speichern' }));
    await waitFor(() => expect(api.followUp).toHaveBeenCalledWith('p-1', DEFECT,
      { resolved_at: '2026-07-10', resolution_note: '' }, expect.anything()));
    fireEvent.click(screen.getByRole('button', { name: 'Korrektur anlegen' }));
    expect(await screen.findByText(/Korrektur des Protokolls vom/)).toBeInTheDocument();
    expect(screen.getByLabelText('Raum 1')).not.toBeDisabled();
    expect(api.startCorrection).toHaveBeenCalledWith('p-1', expect.anything());
    expect(api.load).toHaveBeenLastCalledWith('p-2', expect.anything());
  });

  it('lets a read-only role look but not change', async () => {
    authState.write = ['/auth/users/me/preferences'];
    await openEditor(service());
    expect(screen.getByText(/Nur Lesezugriff/)).toBeInTheDocument();
    expect(screen.getByLabelText('Raum 1')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Prüfen' })).not.toBeInTheDocument();
    expect(screen.queryByText('Foto hinzufügen')).not.toBeInTheDocument();
    expect(within(screen.getByRole('dialog')).getByText('Küche', { selector: 'option' })).toBeInTheDocument();
    void ROOM;
  });
});
