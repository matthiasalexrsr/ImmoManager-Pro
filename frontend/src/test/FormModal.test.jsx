import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/react';
import FormModal from '../components/FormModal';

const fields = [{ key: 'full_name', label: 'Name' }];

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
});
