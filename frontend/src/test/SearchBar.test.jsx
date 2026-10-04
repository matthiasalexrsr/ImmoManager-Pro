import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SearchBar from '../components/SearchBar';

const mocks = vi.hoisted(() => ({ get: vi.fn(), navigate: vi.fn(), t: key => key, user: null }));
vi.mock('../api', () => ({ api: { get: mocks.get } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('react-router-dom', () => ({ useNavigate: () => mocks.navigate }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));

const property = (name, id) => ({ entity_type: 'property', display: name, detail: 'Berlin', url: `/properties/${id}` });
const advance = () => act(async () => { await vi.advanceTimersByTimeAsync(350); });
const change = value => fireEvent.change(screen.getByRole('combobox'), { target: { value } });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((success, failure) => { resolve = success; reject = failure; });
  return { promise, resolve, reject };
};

describe('Global search', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.get.mockReset().mockResolvedValue({ results: [] });
    mocks.navigate.mockReset();
    mocks.user = null;
  });
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

  it('selects the visible keyboard option even when API entity types are interleaved', async () => {
    mocks.get.mockResolvedValue({ results: [
      property('First property', 'first'),
      { entity_type: 'tenant', display: 'A tenant', url: '/tenants' },
      property('Second property', 'second'),
    ] });
    render(<SearchBar />);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('combobox');
    expect(input).toHaveFocus();
    change('matching');
    await advance();
    expect(screen.getAllByRole('option').map(option => option.textContent)).toEqual([
      'First propertyBerlin', 'Second propertyBerlin', 'A tenant',
    ]);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    const highlighted = screen.getByRole('option', { name: 'Second property Berlin', selected: true });
    expect(input).toHaveAttribute('aria-activedescendant', highlighted.id);
    expect(screen.getByRole('group', { name: 'navigation.main.properties' })).toContainElement(highlighted);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(mocks.navigate).toHaveBeenCalledWith('/properties/second');
    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('aborts previous requests and ignores stale success and failure completions', async () => {
    const old = deferred(), current = deferred();
    mocks.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    render(<SearchBar />);
    change('old query');
    await advance();
    const oldSignal = mocks.get.mock.calls[0][1].signal;
    change('current query');
    expect(oldSignal.aborted).toBe(true);
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
    await advance();
    await act(async () => { current.resolve({ results: [property('Current answer', 'current')] }); });
    expect(screen.getByRole('option', { name: 'Current answer Berlin' })).toBeInTheDocument();
    // Deliberately ignore cancellation in the transport to exercise the guard.
    await act(async () => { old.resolve({ results: [property('Late old answer', 'old')] }); });
    expect(screen.queryByText('Late old answer')).not.toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(1);

    const staleFailure = deferred();
    mocks.get.mockReturnValueOnce(staleFailure.promise).mockResolvedValueOnce({ results: [property('Newest answer', 'newest')] });
    change('failure query');
    await advance();
    change('newest query');
    await advance();
    await act(async () => { staleFailure.reject(new Error('Old request failed')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Newest answer Berlin' })).toBeInTheDocument();
  });

  it('immediately hides previous results while a new query is pending', async () => {
    const pending = deferred();
    mocks.get.mockResolvedValueOnce({ results: [property('Prior answer', 'prior')] }).mockReturnValueOnce(pending.promise);
    render(<SearchBar />);
    change('prior');
    await advance();
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
    change('next');
    expect(screen.queryByText('Prior answer')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).not.toHaveAttribute('aria-activedescendant');
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' });
    expect(mocks.navigate).not.toHaveBeenCalled();
    await advance();
    await act(async () => { pending.resolve({ results: [] }); });
    expect(screen.getByRole('status')).toHaveTextContent('search.global.noResults');
  });

  it('reports a real search failure and retries the same query', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Search unavailable')).mockResolvedValueOnce({ results: [property('Recovered answer', 'recovered')] });
    render(<SearchBar />);
    change('same query');
    expect(screen.getByRole('status')).toHaveTextContent('ui.table.loading');
    await advance();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Search unavailable');
    fireEvent.click(within(alert).getByRole('button', { name: 'ui.buttons.retry' }));
    await advance();
    expect(mocks.get.mock.calls.map(([path]) => path)).toEqual(['/search/page?q=same%20query', '/search/page?q=same%20query']);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Recovered answer Berlin' })).toBeInTheDocument();
  });

  it('keeps Escape and clear focus on search while outside actions remain usable', async () => {
    mocks.get.mockResolvedValue({ results: [property('An answer', 'answer')] });
    const outside = vi.fn();
    render(<><SearchBar /><button onClick={outside}>Outside action</button></>);
    const input = screen.getByRole('combobox');
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    change('answer');
    await advance();
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(input).not.toHaveAttribute('aria-activedescendant');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    fireEvent.focus(input);
    await advance();
    fireEvent.click(screen.getByRole('button', { name: 'ui.form.search: ui.buttons.reset' }));
    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
    change('again');
    await advance();
    const action = screen.getByRole('button', { name: 'Outside action' });
    fireEvent.pointerDown(action);
    fireEvent.click(action);
    expect(outside).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('filters malformed results and unsafe or unrelated destinations', async () => {
    mocks.get.mockResolvedValue({ results: [
      property('Good result', 'good'),
      { ...property('External', 'bad'), url: 'https://example.invalid/properties/x' },
      { ...property('Protocol-relative', 'bad'), url: '//example.invalid/properties/x' },
      { ...property('Active URI', 'bad'), url: 'javascript:alert(1)' },
      { ...property('Unrelated route', 'bad'), url: '/settings' },
      { ...property('Encoded escape', 'bad'), url: '/properties/%2e%2e/settings' },
      { ...property('Encoded backslash', 'bad'), url: '/properties/x%5cy' },
      { ...property('Malformed label', 'bad'), display: { html: 'invalid' } },
      { entity_type: 'unknown', display: 'Unknown entity', url: '/properties/x' },
      null,
    ] });
    render(<SearchBar />);
    change('query');
    await advance();
    expect(screen.getAllByRole('option')).toHaveLength(1);
    fireEvent.click(screen.getByRole('option', { name: 'Good result Berlin' }));
    expect(mocks.navigate).toHaveBeenCalledWith('/properties/good');
  });

  it('cancels debounce and active requests on unmount', async () => {
    const first = render(<SearchBar />);
    change('debounce');
    first.unmount();
    await advance();
    expect(mocks.get).not.toHaveBeenCalled();
    const pending = deferred();
    mocks.get.mockReturnValueOnce(pending.promise);
    const second = render(<SearchBar />);
    change('pending');
    await advance();
    const signal = mocks.get.mock.calls[0][1].signal;
    second.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { pending.resolve({ results: [property('Late result', 'late')] }); });
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it('traverses all result pages and keeps a failed cursor available for retry', async () => {
    mocks.get.mockResolvedValueOnce({ results: [property('First page', 'first')], has_more: true, next_after: 'signed+cursor' })
      .mockRejectedValueOnce(new Error('Page unavailable'))
      .mockResolvedValueOnce({ results: [property('Second page', 'second')], has_more: false, next_after: null })
      .mockResolvedValueOnce({ results: [property('First page refreshed', 'first')], has_more: true, next_after: 'signed+cursor' });
    render(<SearchBar />);
    change('complete');
    await advance();
    const nextButton = screen.getByRole('button', { name: 'Weitere Treffer' });
    nextButton.focus();
    fireEvent.click(nextButton);
    expect(screen.getByRole('combobox')).toHaveFocus();
    expect(screen.queryByText('First page')).not.toBeInTheDocument();
    await advance();
    expect(screen.getByRole('alert')).toHaveTextContent('Page unavailable');
    expect(screen.queryByText('search.global.noResults')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'ui.buttons.retry' }));
    await advance();
    expect(screen.getByRole('option', { name: 'Second page Berlin' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Weitere Treffer' })).toBeDisabled();
    expect(mocks.get.mock.calls[1][0]).toBe('/search/page?q=complete&after=signed%2Bcursor');
    expect(mocks.get.mock.calls[2][0]).toBe(mocks.get.mock.calls[1][0]);
    fireEvent.click(screen.getByRole('button', { name: 'Vorherige Treffer' }));
    await advance();
    expect(screen.getByRole('option', { name: 'First page refreshed Berlin' })).toBeInTheDocument();
  });

  it('ignores late pages after a query or object scope changes', async () => {
    const late = deferred();
    mocks.user = { id: 'actor', role: 'verwalter', portfolio_ids: ['one'] };
    mocks.get.mockResolvedValueOnce({ results: [property('Private first', 'first')], has_more: true, next_after: 'old-page' })
      .mockReturnValueOnce(late.promise).mockResolvedValueOnce({ results: [property('New query', 'new')] });
    const control = render(<SearchBar />);
    change('private');
    await advance();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Treffer' }));
    await advance();
    change('new query');
    await advance();
    await act(async () => late.resolve({ results: [property('Old private page', 'old')] }));
    expect(screen.queryByText('Old private page')).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'New query Berlin' })).toBeInTheDocument();
    mocks.user = { ...mocks.user, portfolio_ids: ['two'] };
    control.rerender(<SearchBar />);
    expect(screen.queryByText('New query')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('');
  });

  it('reports malformed page replies as a retryable failure', async () => {
    mocks.get.mockResolvedValueOnce({ results: [], has_more: true, next_after: null });
    render(<SearchBar />);
    change('malformed');
    await advance();
    expect(screen.getByRole('alert')).toHaveTextContent('Die Suchantwort ist unvollständig');
    expect(screen.queryByText('search.global.noResults')).not.toBeInTheDocument();
  });
});
