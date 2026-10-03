import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import useHousingConfirmationCommand from '../features/housingConfirmation/useHousingConfirmationCommand';

describe('housing confirmation command', () => {
  it('retries an unknown publication with the exact frozen payload object', async () => {
    const network = Object.assign(new Error('lost response'), { isNetwork: true });
    const send = vi.fn()
      .mockRejectedValueOnce(network)
      .mockResolvedValueOnce({ id: 'saved-1' });
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useHousingConfirmationCommand('actor-a:contract-1'));

    const payload = {
      idempotency_key: 'same-key',
      expected_revision: 'source-rev-1',
      nested: { review_hash: 'a'.repeat(64) },
    };
    await act(() => result.current.execute({
      label: 'publish',
      payload,
      send,
      onSuccess,
    }));

    expect(result.current.state.phase).toBe('unknown');
    const firstPayload = send.mock.calls[0][0];
    expect(Object.isFrozen(firstPayload)).toBe(true);
    expect(Object.isFrozen(firstPayload.nested)).toBe(true);

    await act(() => result.current.retryExact());
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0]).toBe(firstPayload);
    expect(onSuccess).toHaveBeenCalledWith({ id: 'saved-1' });
  });

  it('returns neutral command state on the first render of a new binding', async () => {
    const send = vi.fn().mockRejectedValue(Object.assign(new Error('lost'), { isNetwork: true }));
    const { result, rerender } = renderHook(
      ({ binding }) => useHousingConfirmationCommand(binding),
      { initialProps: { binding: 'actor-a:contract-1' } },
    );
    await act(() => result.current.execute({ label: 'publish', payload: { key: 'a' }, send }));
    expect(result.current.state.phase).toBe('unknown');

    rerender({ binding: 'actor-b:contract-2' });
    expect(result.current.state.phase).toBe('idle');
    expect(result.current.hasExactRetry).toBe(false);
  });
});
