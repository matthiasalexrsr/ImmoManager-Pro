import { api } from '../api';

// Bank-package hook: call only on explicit "Profil übernehmen" in its existing
// upload form. Returned keys match StageImport, never include source bytes or PIN.
export async function loadBankImportProfile(options) {
  const same = api.captureSession();
  const result = await api.get('/auth/users/me/settings/bank-import-profile', options);
  same();
  if (!['csv', 'mt940', 'camt'].includes(result?.format) || !result.options?.columns || !Number.isInteger(result.revision)) {
    throw new Error('Das gespeicherte Bankimportprofil ist unvollständig.');
  }
  return { format: result.format, options: result.options, profile_revision: result.revision };
}
