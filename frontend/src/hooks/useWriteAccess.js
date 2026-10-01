import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import { authMayWrite } from '../utils/writeAccess';

export default function useWriteAccess(endpoint, onDenied) {
  const auth = useAuth();
  const { t } = useTranslation();
  const canWrite = authMayWrite(auth, endpoint);
  const reset = useRef(onDenied);
  const principal = `${auth?.user?.id || ''}:${auth?.user?.role || auth?.role || ''}`;
  const grant = useMemo(() => ({ canWrite, principal }), [canWrite, principal]);
  const current = useRef({ canWrite, grant });
  const previous = useRef(principal);
  useLayoutEffect(() => { current.current = { canWrite, grant }; reset.current = onDenied; });
  useEffect(() => {
    if (!canWrite || previous.current !== principal) reset.current?.();
    previous.current = principal;
  }, [canWrite, principal]);
  // A pending confirmation belongs to its original grant. Revocation followed
  // by reauthorization must not revive that already-dismissed operation.
  const isAllowed = useCallback(() => current.current.canWrite && current.current.grant === grant, [grant]);
  const requireWrite = useCallback(() => {
    if (!isAllowed()) throw new Error(t('roleAccess.denied'));
  }, [isAllowed, t]);
  return { canWrite, isAllowed, requireWrite };
}
