import { afterEach, describe, it, expect, vi } from 'vitest';
import { act, cleanup, render, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
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
  it('sends only one save while a keyboard submission is pending', async () => {
    let complete;
    const onSave = vi.fn(() => new Promise(resolve => { complete = resolve; }));
    const onClose = vi.fn();
    const { container } = render(<FormModal title="Mieter" fields={fields} onSave={onSave} onClose={onClose} />);
    const input = screen.getByLabelText('Name');
    fireEvent.change(input, { target: { value: 'Anna' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    fireEvent.submit(container.querySelector('form'));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(input).toBeDisabled();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => complete());
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('requires explicit discard even when close is requested twice', () => {
    const onClose = vi.fn();
    render(<FormModal title="Mieter" fields={fields} onSave={vi.fn()} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Anna' } });
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.close' }));
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.close' }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    const afterDiscard = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(afterDiscard);
    expect(afterDiscard.defaultPrevented).toBe(false);
  });

  it('protects drafts before following a missing-prerequisite link', () => {
    const Where = () => <span data-testid="where">{useLocation().pathname}</span>;
    render(<MemoryRouter initialEntries={['/properties']}><FormModal title="Immobilie" fields={[
      { key: 'name', label: 'Name' }, { key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select', options: [] },
    ]} onSave={vi.fn()} onClose={vi.fn()} /><Where /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Entwurf' } });
    fireEvent.click(screen.getByRole('link', { name: 'Portfolio anlegen' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/properties');
    fireEvent.click(screen.getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Entwurf');
    fireEvent.click(screen.getByRole('link', { name: 'Portfolio anlegen' }));
    fireEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/portfolios');
  });

  it('protects an unsaved draft from browser reload until a save succeeds', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    const { container } = render(<FormModal title="Mieter" fields={fields} onSave={onSave} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Anna' } });
    const before = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(before);
    expect(before.defaultPrevented).toBe(true);
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
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

  it('closes an untouched form at once and starts in its first field', () => {
    const onClose = vi.fn();
    render(<FormModal title="Mieter" fields={fields} initial={{ full_name: 'Anna' }} onSave={vi.fn()} onClose={onClose} />);
    expect(screen.getByLabelText('Name')).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('asks before discarding typed input, and a second Escape returns to editing', () => {
    const onClose = vi.fn();
    render(<FormModal title="Mieter" fields={fields} initial={{ full_name: 'Anna' }} onSave={vi.fn()} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Anna Neu' } });

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Ungespeicherte Änderungen verwerfen?');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Anna Neu');

    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.close' }));
    fireEvent.click(screen.getByRole('button', { name: 'Verwerfen' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on the backdrop only for a click that started there', () => {
    const onClose = vi.fn();
    const { container } = render(<FormModal title="Mieter" fields={fields} initial={{}} onSave={vi.fn()} onClose={onClose} />);
    const overlay = container.querySelector('.modal-overlay');
    // selecting text in the field and releasing the mouse over the backdrop
    fireEvent.mouseDown(screen.getByLabelText('Name'));
    fireEvent.click(overlay);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('saves with Ctrl+Enter from a field and closes without asking', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<FormModal title="Mieter" fields={[...fields, { key: 'notes', label: 'Notiz', type: 'textarea' }]}
      initial={{}} onSave={onSave} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Notiz'), { target: { value: 'Zeile 1' } });
    screen.getByLabelText('Notiz').focus();
    fireEvent.keyDown(screen.getByLabelText('Notiz'), { key: 'Enter', ctrlKey: true });
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ full_name: null, notes: 'Zeile 1' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  describe('Speichern & weiteren', () => {
    const series = [
      { key: 'account_id', label: 'Konto', type: 'select', required: true, options: [{ value: 'a1', label: 'Giro' }, { value: 'a2', label: 'Rücklage' }] },
      { key: 'booking_date', label: 'Datum', type: 'date', required: true },
      { key: 'amount', label: 'Betrag', type: 'number', required: true },
      { key: 'payment_text', label: 'Text' },
      { key: 'status', label: 'Status', type: 'select', default: 'open', options: [{ value: 'open', label: 'Offen' }, { value: 'paid', label: 'Bezahlt' }] },
    ];

    it('clears copied values outside repeatKeep after saving a duplicate', async () => {
      render(<FormModal title="Buchung" fields={series} initial={{ account_id: 'a2', booking_date: '2026-10-01', amount: 120, payment_text: 'Original' }}
        onSave={vi.fn().mockResolvedValue(undefined)} onClose={vi.fn()} repeatKeep={['account_id', 'booking_date']} />);
      fireEvent.click(screen.getByRole('button', { name: 'Speichern & weiteren' }));
      await screen.findByRole('status');
      expect(screen.getByLabelText('Konto *')).toHaveValue('a2');
      expect(screen.getByLabelText('Betrag *')).toHaveValue(null);
      expect(screen.getByLabelText('Text')).toHaveValue('');
    });

    it('saves, keeps the named fields, clears the others and continues in the first cleared field', async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const onClose = vi.fn();
      render(<FormModal title="Buchung" fields={series} initial={null} onSave={onSave} onClose={onClose} repeatKeep={['account_id', 'booking_date']} />);
      fireEvent.change(screen.getByLabelText('Konto *'), { target: { value: 'a2' } });
      fireEvent.change(screen.getByLabelText('Datum *'), { target: { value: '2026-10-01' } });
      fireEvent.change(screen.getByLabelText('Betrag *'), { target: { value: '120.5' } });
      fireEvent.change(screen.getByLabelText('Text'), { target: { value: 'Miete Oktober' } });
      fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'paid' } });
      fireEvent.click(screen.getByRole('button', { name: 'Speichern & weiteren' }));

      await waitFor(() => expect(onSave).toHaveBeenCalledWith({ account_id: 'a2', booking_date: '2026-10-01', amount: 120.5, payment_text: 'Miete Oktober', status: 'paid' }));
      expect(await screen.findByRole('status')).toHaveTextContent('1 gespeichert – nächster Eintrag');
      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByLabelText('Konto *')).toHaveValue('a2');
      expect(screen.getByLabelText('Datum *')).toHaveValue('2026-10-01');
      expect(screen.getByLabelText('Betrag *')).toHaveValue(null);
      expect(screen.getByLabelText('Text')).toHaveValue('');
      expect(screen.getByLabelText('Status')).toHaveValue('open');
      await waitFor(() => expect(screen.getByLabelText('Betrag *')).toHaveFocus());

      // nothing typed since the save: closing does not ask
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('checks required fields first and keeps everything when saving fails', async () => {
      const onSave = vi.fn().mockRejectedValueOnce(new Error('Konto gesperrt')).mockResolvedValue(undefined);
      render(<FormModal title="Buchung" fields={series} initial={null} onSave={onSave} onClose={vi.fn()} repeatKeep={['account_id']} />);
      fireEvent.click(screen.getByRole('button', { name: 'Speichern & weiteren' }));
      expect(onSave).not.toHaveBeenCalled();

      fireEvent.change(screen.getByLabelText('Konto *'), { target: { value: 'a1' } });
      fireEvent.change(screen.getByLabelText('Datum *'), { target: { value: '2026-10-02' } });
      fireEvent.change(screen.getByLabelText('Betrag *'), { target: { value: '5' } });
      fireEvent.click(screen.getByRole('button', { name: 'Speichern & weiteren' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('Konto gesperrt');
      expect(screen.getByLabelText('Betrag *')).toHaveValue(5);

      // Ctrl+Shift+Enter is the same as the button
      fireEvent.keyDown(screen.getByLabelText('Betrag *'), { key: 'Enter', ctrlKey: true, shiftKey: true });
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
      expect(await screen.findByRole('status')).toHaveTextContent('1 gespeichert');
    });

    it('is not offered when editing an existing record', () => {
      render(<FormModal title="Buchung" fields={series} initial={{ id: 'b1', account_id: 'a1' }} onSave={vi.fn()} onClose={vi.fn()} repeatKeep={['account_id']} />);
      expect(screen.queryByRole('button', { name: 'Speichern & weiteren' })).not.toBeInTheDocument();
    });
  });
});


it('hebt den Browser-Verlassensschutz direkt nach einem nachweislich erfolgreichen Speichern auf', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const unloadDuringClose = vi.fn();
  const onClose = vi.fn(() => {
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    unloadDuringClose(after.defaultPrevented);
  });
  const { container } = render(<FormModal title="Mieter" fields={fields} onSave={onSave} onClose={onClose} />);
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Anna' } });
  const before = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(before);
  expect(before.defaultPrevented).toBe(true);
  fireEvent.submit(container.querySelector('form'));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(unloadDuringClose).toHaveBeenCalledWith(false);
});
