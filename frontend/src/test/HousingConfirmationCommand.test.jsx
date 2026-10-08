import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import useHousingConfirmationCommand from '../features/housingConfirmation/useHousingConfirmationCommand';

describe('housing confirmation command', () => {
  it('retries an unknown publication with the exact frozen payload object', async () => {
    const network = Object.assign(new Error('lost response'), { isNetwork: true });
    const send = vi.fn().mockRejectedValueOnce(network).mockResolvedValueOnce({ id: 'saved-1' });
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useHousingConfirmationCommand('actor-a:contract-1'));

    const payload = { idempotency_key: 'same-key', nested: { review_hash: 'a'.repeat(64) } };
    await act(() => result.current.execute({ label: 'publish', payload, send, onSuccess }));

    expect(result.current.state.phase).toBe('unknown');
    const firstPayload = send.mock.calls[0][0];
    expect(Object.isFrozen(firstPayload) && Object.isFrozen(firstPayload.nested)).toBe(true);

    await act(() => result.current.retryExact());
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0]).toBe(firstPayload);
    expect(onSuccess).toHaveBeenCalledWith({ id: 'saved-1' });
  });

  it('starts neutral for a new binding and forgets a pending retry', async () => {
    const send = vi.fn().mockRejectedValue(Object.assign(new Error('lost'), { isNetwork: true }));
    const { result, rerender } = renderHook(({ binding }) => useHousingConfirmationCommand(binding),
      { initialProps: { binding: 'actor-a:contract-1' } });
    await act(() => result.current.execute({ label: 'publish', payload: { key: 'a' }, send }));
    expect(result.current.state.phase).toBe('unknown');

    rerender({ binding: 'actor-b:contract-2' });
    expect(result.current.state.phase).toBe('idle');
    expect(result.current.hasExactRetry).toBe(false);
  });

  it('delivers the answer under StrictMode (effects run twice)', async () => {
    // Regression: the cleanup marked the hook unmounted and the second setup never marked it
    // mounted again, so every answer was silently dropped in development builds.
    const send = vi.fn().mockResolvedValue({ id: 'saved-2' });
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useHousingConfirmationCommand('actor-a:contract-1'), { wrapper: StrictMode });

    await act(() => result.current.execute({ label: 'publish', payload: { key: 'b' }, send, onSuccess }));

    expect(onSuccess).toHaveBeenCalledWith({ id: 'saved-2' });
    expect(result.current.state.phase).toBe('success');
  });
});
