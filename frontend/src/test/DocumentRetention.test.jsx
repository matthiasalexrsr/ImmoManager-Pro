import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RetentionLockDialog from '../features/documentRetention/RetentionLockDialog';
import { retentionCell, retentionOptions } from '../features/documentRetention/retentionApi';

vi.mock('../api', () => ({ api: {} }));
afterEach(() => cleanup());

const running = { retention_class: 'booking_record', chosen: false, label: 'Buchungsbeleg', state: 'running', locked: true,
  until: '2033-12-31', years: 8, basis: '§ 147 Abs. 1 Nr. 4, Abs. 3 AO, § 14b UStG',
  text: 'Buchungsbeleg: aufzubewahren bis 31.12.2033.' };
const doc = { id: 'd1', title: 'Heizungswartung 2025' };

describe('retention of documents', () => {
  it('names the period in the list and the classes with their years', () => {
    expect(retentionCell(running)).toBe('bis 31.12.2033');
    expect(retentionCell({ ...running, state: 'ended', until: '2024-12-31' })).toBe('abgelaufen 31.12.2024');
    expect(retentionCell({ state: 'open', years: 3 })).toBe('bis Vertragsende + 3 J.');
    expect(retentionCell({ state: 'permanent' })).toBe('dauerhaft');
    expect(retentionCell({ state: 'none' })).toBe('—');
    const options = retentionOptions({ classes: [{ key: 'booking_record', label: 'Buchungsbeleg', years: 8 },
      { key: 'contract', label: 'Vertragsunterlage', years: 3 }, { key: 'none', label: 'Keine Aufbewahrungsfrist', years: null }] });
    expect(options.map(option => option.label)).toEqual(['Automatisch nach Dokumenttyp', 'Buchungsbeleg (8 Jahre)',
      'Vertragsunterlage (3 Jahre nach Vertragsende)', 'Keine Aufbewahrungsfrist']);
  });

  it('explains the lock and deletes only with a reason for an owner or manager', async () => {
    const service = { remove: vi.fn().mockResolvedValue(null) };
    const onDeleted = vi.fn();
    render(<RetentionLockDialog document={doc} retention={running} canOverride service={service} onClose={vi.fn()} onDeleted={onDeleted} />);
    expect(screen.getByRole('dialog', { name: 'Aufbewahrungspflicht' })).toHaveTextContent('aufzubewahren bis 31.12.2033');
    fireEvent.change(screen.getByLabelText('Trotzdem löschen, weil …'), { target: { value: 'doppelt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Trotzdem löschen' }));
    expect(screen.getByRole('alert')).toHaveTextContent('mindestens 10 Zeichen');
    expect(service.remove).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Trotzdem löschen, weil …'), { target: { value: 'Duplikat der Rechnung R-17' } });
    fireEvent.click(screen.getByRole('button', { name: 'Trotzdem löschen' }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(service.remove).toHaveBeenCalledWith('d1', 'Duplikat der Rechnung R-17');
  });

  it('offers no override to other roles', () => {
    const onClose = vi.fn();
    render(<RetentionLockDialog document={doc} retention={running} canOverride={false} service={{ remove: vi.fn() }} onClose={onClose} onDeleted={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Trotzdem löschen' })).toBeNull();
    expect(screen.getByRole('dialog')).toHaveTextContent('nur Eigentümer und Verwaltung');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
