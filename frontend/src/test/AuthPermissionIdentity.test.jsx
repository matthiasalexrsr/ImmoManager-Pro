import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
function AccountSwitch() {
  const auth = useAuth();
  return <>
    <button onClick={() => auth.updateUser({ id: 'a', role: 'eigentuemer' })}>Konto A</button>
    <button onClick={() => auth.updateUser({ id: 'b', role: 'readonly' })}>Konto B</button>
    <button onClick={auth.clearUser}>Abmelden</button>
    <output data-testid="permissions">{JSON.stringify(auth.write)}</output>
  </>;
}
it('does not apply another account’s late permissions after switching to a reader', async () => {
  let finishA;
  api.get.mockImplementationOnce(() => new Promise(resolve => { finishA = resolve; }))
    .mockResolvedValueOnce({ write: [] });
  render(<AuthProvider><AccountSwitch /></AuthProvider>);
  fireEvent.click(screen.getByText('Konto A'));
  await act(async () => { fireEvent.click(screen.getByText('Konto B')); });
  expect(screen.getByTestId('permissions')).toHaveTextContent('[]');
  await act(async () => { finishA({ write: null }); });
  expect(screen.getByTestId('permissions')).toHaveTextContent('[]');
});
it('ignores an expired permission response after logout', async () => {
  let finish;
  api.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  render(<AuthProvider><AccountSwitch /></AuthProvider>);
  fireEvent.click(screen.getByText('Konto A'));
  fireEvent.click(screen.getByText('Abmelden'));
  await act(async () => { finish({ write: ['documents'] }); });
  expect(screen.getByTestId('permissions')).toHaveTextContent('null');
});
