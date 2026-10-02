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

function CapabilityProbe() {
  const auth = useAuth();
  return <><output data-testid="permissions">{[auth.canWrite('/api/v1/accounts/record'), auth.canWrite('/meters/record'), auth.isAdmin].join(':')}</output>
    <button onClick={() => auth.updateUser({ role: 'buchhaltung', write_permissions: ['finance', 'billing', 'documents', 'communication'] })}>Accountant grant</button>
    <button onClick={() => auth.updateUser({ role: 'techniker', write_permissions: ['operations', 'documents', 'communication'] })}>Technician grant</button>
    <button onClick={() => auth.updateUser({ role: 'eigentuemer', write_permissions: [] })}>Revoke all</button>
    <button onClick={auth.clearUser}>Logout</button></>;
}
it('updates endpoint capabilities from the authoritative session grants and clears them on logout', () => {
  render(<AuthProvider><CapabilityProbe /></AuthProvider>);
  expect(screen.getByTestId('permissions')).toHaveTextContent('false:false:false');
  act(() => screen.getByText('Accountant grant').click());
  expect(screen.getByTestId('permissions')).toHaveTextContent('true:false:false');
  act(() => screen.getByText('Technician grant').click());
  expect(screen.getByTestId('permissions')).toHaveTextContent('false:true:false');
  act(() => screen.getByText('Revoke all').click());
  expect(screen.getByTestId('permissions')).toHaveTextContent('false:false:false');
  act(() => screen.getByText('Logout').click());
  expect(screen.getByTestId('permissions')).toHaveTextContent('false:false:false');
});
