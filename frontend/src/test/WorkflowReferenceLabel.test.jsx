import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WorkflowLocationLabel } from '../features/tenancyWorkflows/WorkflowReferenceLabel';
import { resolvePinnedReference, usePinnedReference } from '../features/tenancyWorkflows/workflowReferenceResolution';

function page(selected) {
  return {
    items: [],
    next_cursor: null,
    has_more: false,
    selected,
  };
}

describe('workflow reference labels', () => {
  it('resolves a readable name only through selected_id with a bounded one-record request', async () => {
    const loader = vi.fn(async () => page({ id: 'property-7', name: 'Haus am Park' }));
    const controller = new AbortController();

    const result = await resolvePinnedReference(loader, 'property-7', {
      signal: controller.signal,
    });

    expect(result).toEqual({ id: 'property-7', name: 'Haus am Park' });
    expect(loader).toHaveBeenCalledWith({
      cursor: null,
      search: '',
      selectedId: 'property-7',
      limit: 1,
      signal: controller.signal,
    });
  });

  it('shows property and unit names via separate bounded selected references', async () => {
    const propertyLoader = vi.fn(async ({ selectedId }) => (
      page({ id: selectedId, name: 'Haus B' })
    ));
    const unitLoader = vi.fn(async ({ selectedId }) => (
      page({ id: selectedId, label: 'Wohnung 2. OG links' })
    ));
    const unitLoaderForProperty = vi.fn(() => unitLoader);

    render(
      <WorkflowLocationLabel
        propertyId="property-b"
        unitId="unit-b"
        principalKey="actor-a:portfolio-b"
        propertyLoader={propertyLoader}
        unitLoaderForProperty={unitLoaderForProperty}
      />,
    );

    expect(await screen.findByText('Haus B · Wohnung 2. OG links')).toBeInTheDocument();
    expect(unitLoaderForProperty).toHaveBeenCalledWith('property-b');
    expect(propertyLoader).toHaveBeenCalledWith(expect.objectContaining({
      selectedId: 'property-b',
      limit: 1,
    }));
    expect(unitLoader).toHaveBeenCalledWith(expect.objectContaining({
      selectedId: 'unit-b',
      limit: 1,
    }));
  });

  it('returns neutral on the first render of a different id/loader/principal binding before effects flush', async () => {
    const renderValues = [];
    let resolveSecond;
    const firstLoader = vi.fn(async ({ selectedId }) => (
      page({ id: selectedId, name: 'Haus Alt' })
    ));
    const secondLoader = vi.fn(() => new Promise(resolve => {
      resolveSecond = resolve;
    }));

    function Probe({ loader, id, principal }) {
      const value = usePinnedReference(loader, id, principal);
      renderValues.push(value);
      return <span>{value?.name || 'neutral'}</span>;
    }

    const view = render(
      <Probe loader={firstLoader} id="property-old" principal="actor-a" />,
    );
    expect(await screen.findByText('Haus Alt')).toBeInTheDocument();

    const before = renderValues.length;
    view.rerender(
      <Probe loader={secondLoader} id="property-new" principal="actor-b" />,
    );

    expect(renderValues[before]).toBeUndefined();
    expect(screen.queryByText('Haus Alt')).not.toBeInTheDocument();
    expect(screen.getByText('neutral')).toBeInTheDocument();
    await waitFor(() => expect(secondLoader).toHaveBeenCalledWith(expect.objectContaining({
      selectedId: 'property-new',
      limit: 1,
      cursor: null,
    })));

    await act(async () => {
      resolveSecond(page({ id: 'property-new', name: 'Haus Neu' }));
    });
    expect(await screen.findByText('Haus Neu')).toBeInTheDocument();
  });

  it('drops a previously visible authorized name while the new principal is rechecked', async () => {
    let resolveSecond;
    const loader = vi.fn(({ selectedId }) => {
      if (loader.mock.calls.length === 1) {
        return Promise.resolve(page({ id: selectedId, name: 'Haus A' }));
      }
      return new Promise(resolve => {
        resolveSecond = resolve;
      });
    });

    const view = render(
      <WorkflowLocationLabel
        propertyId="property-1"
        principalKey="actor-a:portfolio-a"
        propertyLoader={loader}
      />,
    );
    expect(await screen.findByText('Haus A')).toBeInTheDocument();

    view.rerender(
      <WorkflowLocationLabel
        propertyId="property-1"
        principalKey="actor-b:portfolio-b"
        propertyLoader={loader}
      />,
    );

    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('Haus A')).not.toBeInTheDocument();
    expect(screen.getByText('Lade …')).toBeInTheDocument();

    await act(async () => {
      resolveSecond(page(null));
    });

    expect(await screen.findByText('Objekt nicht verfügbar')).toBeInTheDocument();
    expect(loader).toHaveBeenNthCalledWith(2, expect.objectContaining({
      selectedId: 'property-1',
      limit: 1,
      cursor: null,
    }));
  });
});
