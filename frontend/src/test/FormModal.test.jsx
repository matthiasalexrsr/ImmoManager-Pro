import { afterEach, describe, it, expect, vi } from 'vitest';
import { cleanup, render, fireEvent, screen, waitFor, within } from '@testing-library/react';
import FormModal from '../components/FormModal';

const fields = [{ key: 'full_name', label: 'Name' }];
afterEach(() => cleanup());

function submit(initial) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const { container } = render(
    <FormModal title="Mieter" fields={fields} initial={initial} onSave={onSave} onClose={() => {}} />);
  fireEvent.submit(container.querySelector('form'));
  return onSave;
}

describe('FormModal', () => {
  it('sends the state the record was opened in, so a newer change by someone else is not overwritten', async () => {
    const onSave = submit({ id: 't1', full_name: 'Anna', updated_at: '2026-10-05T10:00:00' });
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toEqual({ full_name: 'Anna', updated_at: '2026-10-05T10:00:00' });
  });

  it('sends no state for a new record', async () => {
    const onSave = submit({ full_name: 'Neu' });
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toEqual({ full_name: 'Neu' });
  });

  it('preserves edited title, tags, selection and focus when party options arrive later', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const initial = { id: 'd1', title: 'Original', tags: 'alt', tenant_id: 't1' };
    const before = [
      { key: 'title', label: 'Titel' },
      { key: 'tags', label: 'Tags' },
      { key: 'tenant_id', label: 'Partei', type: 'select', options: [] },
    ];
    const { container, rerender } = render(<FormModal title="Dokument" fields={before} initial={initial} onSave={onSave} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Geprüfter Titel' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'Kontakt, geprüft' } });
    screen.getByLabelText('Titel').focus();
    const loaded = before.map(field => field.key === 'tenant_id'
      ? { ...field, options: [{ value: 't1', label: 'Anna Müller' }, { value: 't2', label: 'Ben Weber' }] }
      : { ...field });
    rerender(<FormModal title="Dokument" fields={loaded} initial={initial} onSave={onSave} onClose={() => {}} />);
    expect(screen.getByLabelText('Titel')).toHaveValue('Geprüfter Titel');
    expect(screen.getByLabelText('Tags')).toHaveValue('Kontakt, geprüft');
    expect(screen.getByLabelText('Partei')).toHaveValue('t1');
    expect(within(screen.getByLabelText('Partei')).getByRole('option', { name: 'Ben Weber' })).toHaveValue('t2');
    expect(screen.getByLabelText('Titel')).toHaveFocus();
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ title: 'Geprüfter Titel', tags: 'Kontakt, geprüft', tenant_id: 't1' }));
  });

  it('adds defaults for new fields without discarding edits and omits removed fields from the payload', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const initial = { id: 'd1', title: 'Original', tags: 'alt' };
    const before = [{ key: 'title', label: 'Titel' }, { key: 'tags', label: 'Tags' }];
    const { container, rerender } = render(<FormModal title="Dokument" fields={before} initial={initial} onSave={onSave} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText('Titel'), { target: { value: 'Bleibt erhalten' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'nicht senden' } });
    const changed = [{ ...before[0] }, { key: 'document_type', label: 'Typ', type: 'select', default: 'Sonstiges', options: [{ value: 'Sonstiges', label: 'Sonstiges' }] }];
    rerender(<FormModal title="Dokument" fields={changed} initial={initial} onSave={onSave} onClose={() => {}} />);
    expect(screen.getByLabelText('Titel')).toHaveValue('Bleibt erhalten');
    expect(screen.getByLabelText('Typ')).toHaveValue('Sonstiges');
    expect(screen.queryByLabelText('Tags')).not.toBeInTheDocument();
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ title: 'Bleibt erhalten', document_type: 'Sonstiges' }));
  });

  it('preserves a draft when an identical inline prefill object is recreated', () => {
    const props = { title: 'Zahlung', fields: [{ key: 'payment_amount', label: 'Betrag', type: 'number' }], onSave: vi.fn(), onClose: vi.fn() };
    const { rerender } = render(<FormModal {...props} initial={{ payment_amount: 200 }} />);
    fireEvent.change(screen.getByLabelText('Betrag'), { target: { value: '150' } });
    rerender(<FormModal {...props} initial={{ payment_amount: 200 }} />);
    expect(screen.getByLabelText('Betrag')).toHaveValue(150);
  });

  it('keeps the opening version when the same record is refreshed while being edited', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const initial = { id: 't1', full_name: 'Anna', updated_at: '2026-10-05T10:00:00' };
    const { container, rerender } = render(<FormModal title="Mieter" fields={fields} initial={initial} onSave={onSave} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Meine Änderung' } });
    rerender(<FormModal title="Mieter" fields={fields} initial={{ ...initial, full_name: 'Andere Änderung', updated_at: '2026-10-05T11:00:00' }} onSave={onSave} onClose={() => {}} />);
    expect(screen.getByLabelText('Name')).toHaveValue('Meine Änderung');
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ full_name: 'Meine Änderung', updated_at: '2026-10-05T10:00:00' }));
  });

  it('resets edited fields when another initial record is opened', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container, rerender } = render(<FormModal title="Mieter" fields={fields} initial={{ id: 't1', full_name: 'Anna' }} onSave={onSave} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Entwurf für Anna' } });
    rerender(<FormModal title="Mieter" fields={fields} initial={{ id: 't2', full_name: 'Ben', updated_at: '2026-10-06T10:00:00' }} onSave={onSave} onClose={() => {}} />);
    expect(screen.getByLabelText('Name')).toHaveValue('Ben');
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ full_name: 'Ben', updated_at: '2026-10-06T10:00:00' }));
  });
});
