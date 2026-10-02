import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BoundedReferencePicker from '../features/tenancyWorkflows/BoundedReferencePicker';

const page = (start, count) => Array.from({ length: count }, (_, index) => ({
  id: `item-${start + index}`,
  name: `Item ${start + index}`,
}));

describe('BoundedReferencePicker', () => {
  it('preserves opaque cursors and selects a later server page', async () => {
    const loadPage = vi.fn(async ({ cursor, limit }) => (
      cursor == null
        ? { items: page(0, limit), next_cursor: 'opaque-cursor', has_more: true, selected: null }
        : { items: [{ id: 'published-late', name: 'Published late' }], next_cursor: null, has_more: false, selected: null }
    ));
    const onChange = vi.fn();
    render(<BoundedReferencePicker label="Template" loadPage={loadPage} onChange={onChange} />);

    expect(await screen.findByRole('option', { name: 'Item 0' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere laden' }));
    const late = await screen.findByRole('option', { name: 'Published late' });
    fireEvent.click(late);

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'published-late' }));
    expect(loadPage).toHaveBeenNthCalledWith(2, expect.objectContaining({
      cursor: 'opaque-cursor',
      search: '',
      selectedId: null,
      limit: 25,
      signal: expect.any(AbortSignal),
    }));
  });

  it('sends search to the loader and restarts from an empty cursor when search changes', async () => {
    const loadPage = vi.fn(async ({ cursor, search }) => {
      if (search === 'spät') {
        return {
          items: [{ id: 'late-match', name: 'Server-normalized result' }],
          next_cursor: null,
          has_more: false,
          selected: null,
        };
      }
      return cursor == null
        ? { items: [{ id: 'first', name: 'First' }], next_cursor: 'opaque-next', has_more: true, selected: null }
        : { items: [{ id: 'second', name: 'Second' }], next_cursor: null, has_more: false, selected: null };
    });
    render(<BoundedReferencePicker label="Contract" loadPage={loadPage} />);

    await screen.findByRole('option', { name: 'First' });
    fireEvent.click(screen.getByRole('button', { name: 'Weitere laden' }));
    await screen.findByRole('option', { name: 'Second' });

    fireEvent.change(screen.getByRole('searchbox', { name: 'Contract' }), {
      target: { value: 'spät' },
    });

    expect(await screen.findByRole('option', { name: 'Server-normalized result' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Second' })).not.toBeInTheDocument();
    expect(loadPage).toHaveBeenLastCalledWith(expect.objectContaining({
      cursor: null,
      search: 'spät',
      selectedId: null,
      limit: 25,
    }));
  });

  it('keeps a selected reference hydrated separately from the current result page', async () => {
    const selected = { id: 'chosen-42', name: 'Chosen record' };
    const loadPage = vi.fn(async ({ selectedId }) => ({
      items: [{ id: 'other', name: 'Other record' }],
      next_cursor: null,
      has_more: false,
      selected: selectedId === selected.id ? selected : null,
    }));
    render(<BoundedReferencePicker label="User" value={selected.id} loadPage={loadPage} />);

    expect(await screen.findByText('Chosen record')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Other record' })).toBeInTheDocument();
    expect(loadPage).toHaveBeenCalledWith(expect.objectContaining({ selectedId: 'chosen-42' }));
  });

  it('does not restart page one when an inline loader callback changes identity', async () => {
    const backend = vi.fn(async () => ({
      items: [{ id: 'user-1', name: 'Active user' }],
      next_cursor: null,
      has_more: false,
      selected: null,
    }));
    function Harness({ tick }) {
      const inlineLoader = args => backend(tick, args);
      return <BoundedReferencePicker label="User" sourceKey="same-scope" loadPage={inlineLoader} />;
    }

    const view = render(<Harness tick={1} />);
    await screen.findByRole('option', { name: 'Active user' });
    expect(backend).toHaveBeenCalledTimes(1);

    view.rerender(<Harness tick={2} />);
    await waitFor(() => expect(backend).toHaveBeenCalledTimes(1));
  });
});
