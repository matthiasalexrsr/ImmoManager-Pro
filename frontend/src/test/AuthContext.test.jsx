import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { AuthProvider, useAuth } from '../contexts/AuthContext';

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="role">{auth?.role || 'none'}</span>
      <span data-testid="isAdmin">{String(auth?.isAdmin)}</span>
      <span data-testid="isReadonly">{String(auth?.isReadonly)}</span>
      <button onClick={() => auth?.updateUser({ role: 'eigentuemer', username: 'admin' })}>
        set-admin
      </button>
      <button onClick={() => auth?.updateUser({ role: 'readonly', username: 'viewer' })}>
        set-readonly
      </button>
      <button onClick={() => auth?.clearUser()}>clear</button>
    </div>
  );
}

describe('AuthContext', () => {
  it('starts with no user', () => {
    render(
      <AuthProvider><TestConsumer /></AuthProvider>
    );
    expect(screen.getByTestId('role').textContent).toBe('none');
    expect(screen.getByTestId('isAdmin').textContent).toBe('false');
    expect(screen.getByTestId('isReadonly').textContent).toBe('false');
  });

  it('detects admin role', () => {
    render(
      <AuthProvider><TestConsumer /></AuthProvider>
    );
    act(() => {
      screen.getByText('set-admin').click();
    });
    expect(screen.getByTestId('role').textContent).toBe('eigentuemer');
    expect(screen.getByTestId('isAdmin').textContent).toBe('true');
    expect(screen.getByTestId('isReadonly').textContent).toBe('false');
  });

  it('detects readonly role', () => {
    render(
      <AuthProvider><TestConsumer /></AuthProvider>
    );
    act(() => {
      screen.getByText('set-readonly').click();
    });
    expect(screen.getByTestId('role').textContent).toBe('readonly');
    expect(screen.getByTestId('isAdmin').textContent).toBe('false');
    expect(screen.getByTestId('isReadonly').textContent).toBe('true');
  });

  it('clears user', () => {
    render(
      <AuthProvider><TestConsumer /></AuthProvider>
    );
    act(() => screen.getByText('set-admin').click());
    expect(screen.getByTestId('role').textContent).toBe('eigentuemer');
    act(() => screen.getByText('clear').click());
    expect(screen.getByTestId('role').textContent).toBe('none');
  });
});
