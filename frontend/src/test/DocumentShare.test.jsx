import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../api';
import BulkBar from '../components/BulkBar';
import ShareDocumentDialog from '../features/documentShare/ShareDocumentDialog';
import { filenameOf, printDocuments, skippedNote, whatsAppLink, whatsAppNumber } from '../features/documentShare/documentShare';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { full_name: 'Linda Reiser' } }), useCanWrite: () => true }));

beforeEach(() => {
  vi.restoreAllMocks();
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:datei');
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(cleanup);

describe('Weitergeben und Drucken', () => {
  it('macht aus deutschen Rufnummern internationale WhatsApp-Nummern', () => {
    expect(whatsAppNumber('0170 123 45 67')).toBe('491701234567');
    expect(whatsAppNumber('+49 (0) 170/1234567')).toBe('491701234567');
    expect(whatsAppNumber('0043 664 1234567')).toBe('436641234567');
    expect(whatsAppNumber('12')).toBe('');
    expect(whatsAppNumber('')).toBe('');
    expect(whatsAppLink('0170 1234567', 'Anbei die Abrechnung')).toBe('https://wa.me/491701234567?text=Anbei%20die%20Abrechnung');
    expect(whatsAppLink('', '')).toBe('https://wa.me/');
  });

  it('liest den Dateinamen und die ausgelassenen Dokumente aus der Antwort', async () => {
    expect(filenameOf(new Headers({ 'Content-Disposition': "attachment; filename*=UTF-8''Nebenkosten%202025.eml" }), 'x')).toBe('Nebenkosten 2025.eml');
    expect(filenameOf(new Headers(), 'Dokument')).toBe('Dokument');
    const skipped = [{ id: 'd2', title: 'Liste', reason: 'Dateiformat ohne Druckansicht' }];
    vi.spyOn(api, 'postFile').mockResolvedValue({ blob: new Blob(['%PDF-']), headers: new Headers({ 'X-Print-Skipped': encodeURIComponent(JSON.stringify(skipped)) }) });
    const print = vi.fn();
    expect(await printDocuments(['d1', 'd2'], { print })).toEqual({ skipped });
    expect(api.postFile).toHaveBeenCalledWith('/documents/print', { ids: ['d1', 'd2'] }, { signal: undefined });
    expect(print).toHaveBeenCalledTimes(1);
    expect(skippedNote(skipped)).toBe('Nicht gedruckt: „Liste“ (Dateiformat ohne Druckansicht).');
  });

  it('füllt den Empfänger aus der Partei und erstellt den E-Mail-Entwurf mit Anhang', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ full_name: 'Ayşe Wolf', email: 'ayse.wolf@beispiel-mail.de', phone: '0170 1234567' });
    const service = { emailDraft: vi.fn().mockResolvedValue(undefined), currentFile: vi.fn() };
    render(<ShareDocumentDialog document={{ id: 'd1', title: 'Nebenkostenabrechnung 2025' }} partyId="t1" onClose={vi.fn()} service={service} />);
    await waitFor(() => expect(screen.getByLabelText('E-Mail')).toHaveValue('ayse.wolf@beispiel-mail.de'));
    expect(api.get).toHaveBeenCalledWith('/tenants/t1', expect.anything());
    expect(screen.getByLabelText('Nachricht').value).toContain('Guten Tag Ayşe Wolf,');
    expect(screen.getByLabelText('Nachricht').value).toContain('„Nebenkostenabrechnung 2025“');
    expect(screen.getByLabelText('Nachricht').value).toMatch(/Linda Reiser$/);
    fireEvent.click(screen.getByRole('button', { name: /E-Mail mit Anhang/ }));
    await screen.findByText(/E-Mail-Entwurf mit Anhang wurde heruntergeladen/);
    expect(service.emailDraft).toHaveBeenCalledWith('d1', expect.objectContaining({
      to: ['ayse.wolf@beispiel-mail.de'], subject: 'Nebenkostenabrechnung 2025' }));
  });

  it('öffnet WhatsApp mit der Mobilnummer und legt die Datei zum Anhängen bereit', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ full_name: 'Ayşe Wolf', email: '', phone: '0170 1234567' });
    const popup = { location: { replace: vi.fn() }, opener: {} };
    vi.spyOn(window, 'open').mockReturnValue(popup);
    const file = new File(['%PDF-'], 'abrechnung.pdf', { type: 'application/pdf' });
    const service = { emailDraft: vi.fn(), currentFile: vi.fn().mockResolvedValue(file) };
    render(<ShareDocumentDialog document={{ id: 'd1', title: 'Abrechnung' }} partyId="t1" onClose={vi.fn()} service={service} />);
    await waitFor(() => expect(screen.getByLabelText('Mobilnummer')).toHaveValue('0170 1234567'));
    fireEvent.click(screen.getByRole('button', { name: /WhatsApp/ }));
    await screen.findByText(/liegt in Ihren Downloads/);
    expect(popup.location.replace).toHaveBeenCalledWith(expect.stringMatching(/^https:\/\/wa\.me\/491701234567\?text=Guten%20Tag/));
    expect(popup.opener).toBeNull();
    expect(URL.createObjectURL).toHaveBeenCalledWith(file);

    fireEvent.change(screen.getByLabelText('Mobilnummer'), { target: { value: '12' } });
    expect(screen.getByText(/Diese Nummer erkennt WhatsApp nicht/)).toBeInTheDocument();
  });
});

describe('Sammelaktion auf der ganzen Auswahl', () => {
  it('läuft einmal für alle Zeilen und meldet die ausgelassenen', async () => {
    const rows = [{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }];
    const runAll = vi.fn().mockResolvedValue({ failed: [{ row: { id: 'b', title: 'B' }, message: 'keine Datei' }] });
    const setReport = vi.fn();
    const onFinished = vi.fn();
    const words = { region: 'Auswahl', selected: n => `${n} ausgewählt`, selectAll: () => '', clear: 'Leeren', applies: () => '',
      progress: () => 'läuft', report: () => '', dismiss: 'OK', rowName: row => row.title };
    render(<BulkBar rows={rows} total={2} allSelected actions={[{ key: 'print', label: 'Drucken', runAll }]} onSelectAll={vi.fn()}
      onClear={vi.fn()} onFinished={onFinished} words={words} report={null} setReport={setReport} />);
    fireEvent.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(onFinished).toHaveBeenCalled());
    expect(runAll).toHaveBeenCalledTimes(1);
    expect(runAll).toHaveBeenCalledWith(rows);
    expect(onFinished.mock.calls[0][0].succeeded).toEqual([rows[0]]);
    expect(setReport).toHaveBeenLastCalledWith(expect.objectContaining({ label: 'Drucken', succeeded: 1 }));
  });
});
