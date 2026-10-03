import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DisputeReferenceChoice from '../features/billingDisputes/DisputeReferenceChoice';
import OriginalEvidencePicker from '../features/billingDisputes/OriginalEvidencePicker';
import { OriginalSnapshot } from '../features/billingDisputes/DisputeOriginals';
import { disputeText } from '../features/billingDisputes/disputeCopy';
import { readCase, readVersionPage } from '../features/billingDisputes/disputeModel';
import { caseRow, evidence, originalStatement } from './fixtures/disputes';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
const tr = key => disputeText('de-DE', key);
const page = (items, selected = null, cursor = null) => ({ items, selected, has_more: Boolean(cursor), next_cursor: cursor });
const row = (number, id = `version-${number}`) => ({ ...evidence, id, document_id: 'document', number, created_at: '2026-10-01T12:00:00Z' });
beforeEach(() => { vi.clearAllMocks(); });

describe('bounded original choices and historically evidenced identity', () => {
  it('retains selected metadata outside search pages and resets an old cursor on search change', async () => {
    mocks.get.mockImplementation(path => {
      const query = new URLSearchParams(path.split('?')[1]);
      return Promise.resolve(page([{ id: query.get('cursor') ? 'second' : 'first', label: query.get('cursor') ? 'Zweite Fassung' : 'Erste Fassung' }], { id: 'retained', label: 'Gewählte Originalfassung' }, query.get('cursor') ? null : 'opaque-cursor'));
    });
    const change = vi.fn(); render(<DisputeReferenceChoice kind="statements" label="Originalwahl" filters={{ period_id: 'period' }} principal="actor" value="retained" onChange={change} tr={tr} />);
    await screen.findByText('Ausgewählt: Gewählte Originalfassung'); fireEvent.click(screen.getByRole('button', { name: 'Nächste Seite' }));
    await screen.findByRole('button', { name: 'Zweite Fassung' }); fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Eigenes Suchwort' } });
    await screen.findByRole('button', { name: 'Erste Fassung' });
    const last = new URLSearchParams(mocks.get.mock.calls.at(-1)[0].split('?')[1]);
    expect(last.get('selected_id')).toBe('retained'); expect(last.get('search')).toBe('Eigenes Suchwort'); expect(last.get('cursor')).toBeNull(); expect(last.get('page_size')).toBe('25'); expect(change).not.toHaveBeenCalled();
  });
  it('rejects a substituted selected packet instead of offering its entries', async () => {
    mocks.get.mockResolvedValue(page([{ id: 'first', label: 'Ungeprüft' }], { id: 'wrong', label: 'Falsche Fassung' }));
    render(<DisputeReferenceChoice kind="statements" label="Originalwahl" principal="actor" value="retained" onChange={vi.fn()} tr={tr} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Aktenantwort konnte nicht geprüft werden.'); expect(screen.queryByRole('button', { name: 'Ungeprüft' })).not.toBeInTheDocument();
  });
  it('retains original version IDs after reload without pretending a document selection is an attachment', async () => {
    mocks.get.mockResolvedValue(page([])); const change = vi.fn();
    render(<OriginalEvidencePicker propertyId="property" principal="actor" value={['retained-version']} onChange={change} tr={tr} />);
    await screen.findByText('Keine passenden Einträge auf dieser Seite.');
    expect(screen.getByText(/Originalname, Zuordnung und Bytes/)).toBeInTheDocument();
    expect(mocks.get.mock.calls.every(([path]) => path.startsWith('/workflow-references/documents?'))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Auswahl entfernen' })); expect(change).toHaveBeenCalledWith([]);
  });
  it('loads archived versions only for the selected document and fences a denied original history', async () => {
    const denied = vi.fn(); mocks.get.mockImplementation(path => path.startsWith('/workflow-references') ? Promise.resolve(page([{ id: 'document', label: 'Dokumentkontext' }]))
      : Promise.reject(Object.assign(new Error('Denied original'), { statusCode: 404 })));
    render(<OriginalEvidencePicker propertyId="property" principal="actor" onChange={vi.fn()} tr={tr} onDenied={denied} />);
    await screen.findByRole('button', { name: 'Dokumentkontext' }); expect(mocks.get).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Dokumentkontext' })); await waitFor(() => expect(denied).toHaveBeenCalledTimes(1));
    expect(mocks.get).toHaveBeenLastCalledWith('/documents/document/versions?limit=25', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });
  it('validates descending history keys, document ownership and complete bounded packets', () => {
    expect(readVersionPage({ document_id: 'document', items: [row(4), row(3)], next_before: 3 }, 'document').items).toHaveLength(2);
    for (const items of [[row(3), row(4)], [{ ...row(3), document_id: 'foreign' }], Array.from({ length: 26 }, (_, index) => row(30 - index))]) {
      expect(() => readVersionPage({ document_id: 'document', items, next_before: null }, 'document')).toThrow('invalidDisputeResponse');
    }
    expect(() => readVersionPage({ document_id: 'document', items: [row(4)], next_before: 3 }, 'document')).toThrow();
  });
  it('displays only the person and postal address contained in the actual frozen original', () => {
    const snapshot = { ...originalStatement, original_party: { statement_id: originalStatement.id, period_id: 'period', revision: 3, contract_id: 'contract', unit_id: 'unit', tenant_id: 'frozen-person', captured_at: '2026-10-01T12:00:00Z',
      identity: { full_name: 'Originalperson', address_line: 'Originalstraße 3', postal_code: '12345', city: 'Originalstadt', country: 'DE' } } };
    expect(readCase({ ...caseRow, original_snapshot: snapshot }, 'case', 'period').original_snapshot).toEqual(snapshot);
    render(<OriginalSnapshot snapshot={snapshot} tr={tr} locale="de-DE" />);
    const original = screen.getByRole('region', { name: 'Belegte Originalmietpartei' });
    expect(within(original).getByText('Originalperson')).toBeInTheDocument(); expect(within(original).getByText('12345 Originalstadt')).toBeInTheDocument();
    expect(() => readCase({ ...caseRow, original_snapshot: { ...snapshot, original_party: { ...snapshot.original_party, revision: 4 } } }, 'case', 'period')).toThrow();
  });
});
