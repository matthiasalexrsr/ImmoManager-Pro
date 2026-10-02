import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BoundedReferencePicker from '../features/tenancyWorkflows/BoundedReferencePicker';

const page = (start, count) => Array.from({ length: count }, (_, index) => ({
  id: `item-${start + index}`,
  name: `Item ${start + index}`,
  is_active: true,
}));

describe('BoundedReferencePicker', () => {
  it('keeps legacy offset pages bounded and can select a late item', async () => {
    const loadPage = vi.fn(async ({ offset, limit }) => (
      offset === 0 ? page(0, limit) : [{ id: 'item-25', name: 'Late item', is_active: true }]
    ));
    const onChange = vi.fn();
    render(<BoundedReferencePicker label="Contract" loadPage={loadPage} onChange={onChange} />);

    expect(await screen.findByRole('option', { name: 'Item 0' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Late item' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere laden' }));
    const late = await screen.findByRole('option', { name: 'Late item' });
    fireEvent.click(late);

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'item-25' }));
    expect(loadPage).toHaveBeenNthCalledWith(2, expect.objectContaining({
      offset: 25,
      cursor: null,
      limit: 25,
      signal: expect.any(AbortSignal),
    }));
  });

  it('preserves opaque workflow cursors instead of translating them to offsets', async () => {
    const loadPage = vi.fn(async ({ cursor, limit }) => (
      cursor == null
        ? { items: page(0, limit), next_cursor: 'opaque-cursor', has_more: true }
        : { items: [{ id: 'published-late', name: 'Published late' }], next_cursor: null, has_more: false }
    ));
    render(<BoundedReferencePicker label="Template" loadPage={loadPage} />);

    await screen.findByRole('option', { name: 'Item 0' });
    fireEvent.click(screen.getByRole('button', { name: 'Weitere laden' }));
    expect(await screen.findByRole('option', { name: 'Published late' })).toBeInTheDocument();
    expect(loadPage).toHaveBeenNthCalledWith(2, expect.objectContaining({
      offset: 25,
      cursor: 'opaque-cursor',
      limit: 25,
    }));
  });

  it('does not restart page one when an inline loader callback changes identity', async () => {
    const backend = vi.fn(async () => [{ id: 'user-1', name: 'Active user', is_active: true }]);
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

  it('shows inactive references but makes them non-selectable', async () => {
    const onChange = vi.fn();
    render(<BoundedReferencePicker
      label="User"
      loadPage={async () => [{ id: 'inactive', name: 'Inactive', is_active: false }]}
      isSelectable={item => item.is_active}
      onChange={onChange}
    />);

    const item = await screen.findByRole('option', { name: 'Inactive' });
    expect(item).toBeDisabled();
    fireEvent.click(item);
    expect(onChange).not.toHaveBeenCalled();
  });
});
