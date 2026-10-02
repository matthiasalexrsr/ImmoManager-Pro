import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import useWorkflowCommand from '../features/tenancyWorkflows/useWorkflowCommand';

describe('useWorkflowCommand', () => {
  it('freezes an unknown-success command and replays the exact same payload object', async () => {
    const networkError = Object.assign(new Error('lost response'), {
      isNetwork: true,
      code: 'NETWORK_ERROR',
    });
    const send = vi.fn()
      .mockRejectedValueOnce(networkError)
      .mockResolvedValueOnce({ ok: true });
    const success = vi.fn();
    const payload = {
      idempotency_key: 'same-key',
      expected_revision: 'rev-1',
      preview_hash: 'abc123',
      nested: { value: 7 },
    };
    const { result } = renderHook(() => useWorkflowCommand('actor-1'));

    await act(() => result.current.execute({
      label: 'start-change',
      payload,
      send,
      onSuccess: success,
    }));
    expect(result.current.state.phase).toBe('unknown');
    expect(result.current.hasExactRetry).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);

    payload.expected_revision = 'silently-new-revision';
    payload.nested.value = 99;
    await act(() => result.current.retryExact());

    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0]).toBe(send.mock.calls[0][0]);
    expect(send.mock.calls[1][0]).toEqual({
      idempotency_key: 'same-key',
      expected_revision: 'rev-1',
      preview_hash: 'abc123',
      nested: { value: 7 },
    });
    expect(Object.isFrozen(send.mock.calls[1][0])).toBe(true);
    expect(Object.isFrozen(send.mock.calls[1][0].nested)).toBe(true);
    expect(success).toHaveBeenCalledWith({ ok: true });
  });

  it.each([409, 412])('requires conscious review after HTTP %s and never exact-replays it', async statusCode => {
    const send = vi.fn().mockRejectedValue(
      Object.assign(new Error('changed'), { statusCode }),
    );
    const { result } = renderHook(() => useWorkflowCommand('actor-1'));

    await act(() => result.current.execute({
      label: 'edit-step',
      payload: { idempotency_key: 'k', expected_revision: 'r1', state: 'completed' },
      send,
    }));
    expect(result.current.state.phase).toBe('conflict');
    expect(result.current.hasExactRetry).toBe(false);

    await act(() => result.current.retryExact());
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('treats a fresh 403 rights revocation as final for this UI command and never exact-replays it', async () => {
    const send = vi.fn().mockRejectedValue(
      Object.assign(new Error('forbidden'), { statusCode: 403 }),
    );
    const { result } = renderHook(() => useWorkflowCommand('actor-1:verwalter:portfolio-a'));

    await act(() => result.current.execute({
      label: 'edit-step',
      payload: {
        idempotency_key: 'k-403',
        expected_revision: 'step-rev-1',
        expected_change_revision: 'change-rev-1',
        state: 'completed',
      },
      send,
    }));

    expect(result.current.state.phase).toBe('error');
    expect(result.current.hasExactRetry).toBe(false);
    await act(() => result.current.retryExact());
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('drops pending private command state when the authenticated principal changes', async () => {
    const send = vi.fn().mockRejectedValue(
      Object.assign(new Error('unclear'), { statusCode: 503 }),
    );
    const { result, rerender } = renderHook(
      ({ principal }) => useWorkflowCommand(principal),
      { initialProps: { principal: 'actor-1:verwalter' } },
    );

    await act(() => result.current.execute({
      label: 'publish',
      payload: { idempotency_key: 'k', expected_revision: 'r1' },
      send,
    }));
    expect(result.current.state.phase).toBe('unknown');

    rerender({ principal: 'actor-2:verwalter' });
    expect(result.current.state.phase).toBe('idle');
    expect(result.current.hasExactRetry).toBe(false);
  });
});
