import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BankImport from '../components/BankImport';
import FinTSImport from '../components/FinTSImport';
import BankMatch from '../components/BankMatch';
import { api } from '../api';
import { bankOriginalPath } from '../utils/bankOriginal';

vi.mock('../api', () => ({ api: { captureSession: vi.fn(() => () => {}), get: vi.fn(), post: vi.fn(), getBlob: vi.fn() } }));
const preview = { id: 'import-1', account_id: 'a1', filename: 'Original.csv', format: 'csv', state: 'staged', revision: 1,
  preview_sha256: 'a'.repeat(64), row_count: 101, error_count: 0, total_cents: 12345, offset: 0, next_offset: 100,
  rows: [{ line: 2, date: '2026-10-01', cents: 12345, text: 'Miete', reference: 'BANK-1', index: 0, duplicate_candidates: [] }], errors: [], links: [] };

beforeEach(() => vi.clearAllMocks());

describe('Bankimport', () => {
  const savedProfile = { format: 'csv', revision: 4, options: { encoding: 'cp1252', delimiter: ';', decimal: ',', date_format: '%d.%m.%Y', columns: { date: 'Buchungstag', amount: 'Umsatz', text: 'Verwendungszweck' } } };
  const openImport = () => {
    const panel = screen.getByText('Bankdatei importieren und Übernahmebeleg öffnen').parentElement;
    panel.open = true;
    fireEvent(panel, new Event('toggle', { bubbles: false }));
  };

  it('uses the effective saved profile for new imports', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.endsWith('/bank-import-profile') ? savedProfile : preview));
    render(<BankImport accounts={[]} onImported={() => {}} />);
    openImport();
    await waitFor(() => expect(screen.getByLabelText('Datumsspalte')).toHaveValue('Buchungstag'));
    expect(screen.getByLabelText('Dezimalzeichen')).toHaveValue(',');
    expect(screen.getByLabelText('Kodierung')).toHaveValue('cp1252');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('never overwrites edits with a late default and lets the user explicitly apply it', async () => {
    let finishProfile;
    api.get.mockImplementation(() => new Promise(resolve => { finishProfile = resolve; }));
    render(<BankImport accounts={[]} onImported={() => {}} />);
    openImport();
    fireEvent.change(screen.getByLabelText('Betragsspalte'), { target: { value: 'Meine Spalte' } });
    finishProfile(savedProfile);
    await screen.findByText('Gespeicherte Formatvorlage anwenden');
    expect(screen.getByLabelText('Betragsspalte')).toHaveValue('Meine Spalte');
    fireEvent.click(screen.getByText('Gespeicherte Formatvorlage anwenden'));
    expect(screen.getByLabelText('Betragsspalte')).toHaveValue('Umsatz');
  });

  it('keeps the mapping of a reopened import when the saved default arrives later', async () => {
    let finishProfile;
    api.get.mockImplementation(path => path.endsWith('/bank-import-profile')
      ? new Promise(resolve => { finishProfile = resolve; }) : Promise.resolve({ ...preview, options: { columns: { date: 'Originaldatum', amount: 'Originalbetrag', text: 'Originaltext' } } }));
    render(<BankImport accounts={[]} onImported={() => {}} />);
    openImport();
    fireEvent.change(screen.getByLabelText('Gespeicherte Importkennung'), { target: { value: 'import-1' } });
    fireEvent.click(screen.getByText('Vorgang wieder öffnen'));
    await screen.findByText('Miete');
    finishProfile(savedProfile);
    await screen.findByText('Gespeicherte Formatvorlage anwenden');
    expect(screen.getByLabelText('Datumsspalte')).toHaveValue('Originaldatum');
  });

  it('recognizes only its exact authenticated original route', () => {
    const id = 'a1234567-1234-4123-8123-123456789abc';
    expect(bankOriginalPath(`/api/v1/bank-imports/${id}/original`)).toBe(`/bank-imports/${id}/original`);
    for (const value of [`https://foreign.example/api/v1/bank-imports/${id}/original`, `/api/v1/bank-imports/${id}/original?token=other`, '/api/v1/files/private', '//foreign.example/']) {
      expect(bankOriginalPath(value)).toBeNull();
    }
  });
  it('uploads the exact original bytes and reuses its command after a lost response', async () => {
    const raw = 'date;amount;text\r\n2026-10-01;1.23;Original\r\n';
    const file = new File([raw], 'Original.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode(raw).buffer });
    api.post.mockRejectedValueOnce(new Error('Antwort verloren')).mockResolvedValueOnce(preview);
    api.get.mockResolvedValue(preview);
    render(<BankImport accounts={[{ id: 'a1', name: 'Bank' }]} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Konto'), { target: { value: 'a1' } });
    fireEvent.change(screen.getByLabelText('Originaldatei'), { target: { files: [file] } });
    fireEvent.click(screen.getByText('Vollständige Vorschau vorbereiten'));
    await screen.findByText(/Antwort verloren/);
    fireEvent.click(screen.getByText('Vollständige Vorschau vorbereiten'));
    await screen.findByText('Miete');
    const first = api.post.mock.calls[0][1];
    const second = api.post.mock.calls[1][1];
    expect(second).toEqual(first);
    expect(atob(first.source_base64)).toBe(raw);
    expect(first.account_id).toBe('a1');
  });
  it('opens a durable preview, pages every row, and requires explicit confirmation', async () => {
    api.get.mockResolvedValue(preview);
    api.post.mockResolvedValue({ state: 'confirmed' });
    const imported = vi.fn();
    render(<BankImport accounts={[{ id: 'a1', name: 'Bank' }]} onImported={imported} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Importkennung'), { target: { value: 'import-1' } });
    fireEvent.click(screen.getByText('Vorgang wieder öffnen'));
    await screen.findByText('Miete');
    expect(screen.getByText('Buchungen verbindlich übernehmen')).toBeDisabled();
    fireEvent.click(screen.getByText('Weitere Zeilen und Fehler'));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/bank-imports/import-1?offset=100'));
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByText('Buchungen verbindlich übernehmen'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bank-imports/import-1/confirm', expect.objectContaining({ base_revision: 1, confirm: true, preview_sha256: 'a'.repeat(64) })));
    await waitFor(() => expect(imported).toHaveBeenCalledOnce());
  });

  it('shows errors and never offers confirmation for an invalid source', async () => {
    api.get.mockResolvedValue({ ...preview, state: 'invalid', error_count: 1, errors: [{ line: 3, error: 'Saldo stimmt nicht' }] });
    render(<BankImport accounts={[]} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Importkennung'), { target: { value: 'import-1' } });
    fireEvent.click(screen.getByText('Vorgang wieder öffnen'));
    await screen.findByText('Zeile 3: Saldo stimmt nicht');
    expect(screen.queryByText('Buchungen verbindlich übernehmen')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('labels a legacy text receipt without claiming original file bytes', async () => {
    api.get.mockResolvedValue({ ...preview, source_provenance: 'submitted_text_utf8' });
    render(<BankImport accounts={[]} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Importkennung'), { target: { value: 'import-1' } });
    fireEvent.click(screen.getByText('Vorgang wieder öffnen'));
    await screen.findByText(/Textübernahme aus der bisherigen Schnittstelle/);
    expect(screen.getByText('Übermittelten Text herunterladen')).toBeInTheDocument();
    expect(screen.queryByText('Original herunterladen')).toBeNull();
  });

  it('requires a fresh preview after the mapping form changes', async () => {
    api.get.mockResolvedValue(preview);
    render(<BankImport accounts={[{ id: 'a1', name: 'Bank' }]} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Importkennung'), { target: { value: 'import-1' } });
    fireEvent.click(screen.getByText('Vorgang wieder öffnen'));
    await screen.findByText('Miete');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.change(screen.getByLabelText('Betragsspalte'), { target: { value: 'Anderer Betrag' } });
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByText('Buchungen verbindlich übernehmen')).toBeDisabled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('rejects a late response after the session boundary changes', async () => {
    let finish;
    let valid = true;
    api.captureSession.mockReturnValue(() => { if (!valid) throw Object.assign(new Error('Sitzung geändert'), { code: 'SESSION_CHANGED' }); });
    api.get.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<BankImport accounts={[]} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Importkennung'), { target: { value: 'import-1' } });
    fireEvent.click(screen.getByText('Vorgang wieder öffnen'));
    valid = false; finish(preview);
    await waitFor(() => expect(screen.queryByText('Bankvorgang wird verarbeitet …')).toBeNull());
    expect(screen.queryByText('Miete')).toBeNull();
    api.captureSession.mockReturnValue(() => {});
  });

  it('FinTS GET only loads a session and never contacts the bank implicitly', async () => {
    api.get.mockResolvedValue({ id: 'session-1', revision: 2, state: 'running', accounts: [], expires_at: '2026-10-16T12:10:00Z' });
    render(<FinTSImport accounts={[]} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Abrufkennung'), { target: { value: 'session-1' } });
    fireEvent.click(screen.getByText('Abrufstand laden'));
    await screen.findByText(/Abruf läuft oder Antwort steht aus/);
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByText('Fortsetzen')).toBeNull();
  });

  it('shows the TAN challenge and sends a revision-bound explicit continuation', async () => {
    api.get.mockResolvedValue({ id: 'session-1', revision: 2, state: 'tan_required', accounts: [], challenge: 'Bankfreigabe prüfen', expires_at: '2026-10-16T12:10:00Z' });
    api.post.mockResolvedValue({ id: 'session-1', revision: 4, state: 'select_account', accounts: [['DE-SYNTHETIC', 'TEST']], expires_at: '2026-10-16T12:10:00Z' });
    render(<FinTSImport accounts={[]} />);
    fireEvent.change(screen.getByLabelText('Gespeicherte Abrufkennung'), { target: { value: 'session-1' } });
    fireEvent.click(screen.getByText('Abrufstand laden'));
    await screen.findByText('Bankfreigabe prüfen');
    fireEvent.change(screen.getByLabelText('TAN'), { target: { value: '654321' } });
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Fortsetzen'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bank-imports/fints/sessions/session-1/step', expect.objectContaining({ base_revision: 2, tan: '654321' })));
    await screen.findByLabelText('Abgerufenes Konto');
    expect(screen.queryByLabelText('TAN')).toBeNull();
  });

  it('keeps payment matching as a proposal until explicitly confirmed', async () => {
    api.get.mockResolvedValue({ expected_revision: 'b'.repeat(64), budget_cents: 12345, assigned_cents: 0,
      remaining_cents: 12345, reversal_count: 0, suggestions: [{ tenant_id: 'tenant-1', name: 'Mia', reason: 'Name im Verwendungszweck', allocations: { contract1: 10001 } }] });
    api.post.mockResolvedValue({});
    const assigned = vi.fn();
    render(<BankMatch bookingId="booking-1" onAssigned={assigned} />);
    fireEvent.click(screen.getByText('Aktuelle Vorschläge laden'));
    await screen.findByText('Mia · Name im Verwendungszweck');
    expect(api.post).not.toHaveBeenCalled();
    expect(assigned).not.toHaveBeenCalled();
    expect(screen.getByText('Diese Zuordnung ausdrücklich übernehmen')).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByText('Diese Zuordnung ausdrücklich übernehmen'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bank-imports/matching/booking-1', expect.objectContaining({ expected_revision: 'b'.repeat(64), allocations: { contract1: 10001 }, tenant_id: 'tenant-1' })));
    await waitFor(() => expect(assigned).toHaveBeenCalledOnce());
  });
});
