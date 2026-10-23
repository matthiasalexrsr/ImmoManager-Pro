import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import { prepareUploadAccess } from '../utils/uploadAccess';
import { setWorkspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
afterEach(() => { setWorkspaceOwner(null); localStorage.clear(); vi.resetAllMocks(); });
it('does not authorize an old file viewer using the newly signed-in account', async () => {
  let finish;
  setWorkspaceOwner('owner-a');
  localStorage.setItem('access_token', 'token-a');
  api.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const access = prepareUploadAccess('/uploads/private-a.pdf');
  const denied = expect(access).rejects.toThrow('Die Anmeldung hat sich geändert');
  setWorkspaceOwner('owner-b');
  localStorage.setItem('access_token', 'token-b');
  finish({ id: 'owner-b' });
  await denied;
  expect(api.get).toHaveBeenCalledTimes(1);
});
it('permits same-owner token renewal and verifies the new file session', async () => {
  setWorkspaceOwner('owner-a');
  localStorage.setItem('access_token', 'token-a');
  api.get.mockImplementationOnce(async () => {
    localStorage.setItem('access_token', 'renewed-a');
    return { id: 'owner-a' };
  }).mockResolvedValueOnce({ id: 'owner-a' });
  await expect(prepareUploadAccess('/uploads/private-a.pdf')).resolves.toBeUndefined();
  expect(api.get).toHaveBeenCalledTimes(2);
});
