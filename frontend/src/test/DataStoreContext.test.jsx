import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DataStoreProvider, useEntities } from '../contexts/DataStoreContext';

function Inventory() {
  const { items, loading, error, reload } = useEntities('units', '/units');
  return <div>
    <output aria-label="inventory">{loading ? 'loading' : items.length}</output>
    {error && <p role="alert">{error}</p>}
    <button onClick={reload}>Reload</button>
  </div>;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

describe('shared inventory cache', () => {
  it('loads the complete paginated inventory before reporting its count', async () => {
    const pages = [];
    vi.stubGlobal('fetch', vi.fn(async url => {
      const skip = Number(new URL(url, 'http://localhost').searchParams.get('skip'));
      pages.push(skip);
      return new Response(JSON.stringify(skip === 0
        ? Array.from({ length: 1000 }, (_, id) => ({ id, occupancy_status: 'occupied' }))
        : [{ id: 1000, occupancy_status: 'vacant' }]), { status: 200 });
    }));
    render(<DataStoreProvider><Inventory /></DataStoreProvider>);
    await waitFor(() => expect(screen.getByLabelText('inventory')).toHaveTextContent(/^1001$/));
    expect(pages).toEqual([0, 1000]);
  });

  it('keeps an incomplete paginated load in an error state and recovers on retry', async () => {
    let available = false;
    vi.stubGlobal('fetch', vi.fn(async url => {
      const skip = Number(new URL(url, 'http://localhost').searchParams.get('skip'));
      if (skip === 0) return new Response(JSON.stringify(Array.from({ length: 1000 }, (_, id) => ({ id }))), { status: 200 });
      return new Response(JSON.stringify(available ? [{ id: 1000 }] : { detail: 'Inventory unavailable' }), { status: available ? 200 : 503 });
    }));
    render(<DataStoreProvider><Inventory /></DataStoreProvider>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Inventory unavailable');
    expect(screen.getByLabelText('inventory')).toHaveTextContent(/^0$/);
    available = true;
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(screen.getByLabelText('inventory')).toHaveTextContent(/^1001$/));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
