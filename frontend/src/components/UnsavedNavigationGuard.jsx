import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useBlocker } from 'react-router-dom';
import { NavigationProtectionContext, useNavigationProtection } from './navigationProtectionContext';

const isPending = protection => typeof protection.pending === 'function' ? protection.pending() : protection.pending;

// One router blocker serves every editor. Registration order follows mounted
// dialogs, while a pending command anywhere takes precedence over discarding.
export function NavigationProtectionProvider({ children }) {
  const registrations = useRef(new Map());
  const owner = useRef(null);
  const excluded = useRef(new Set());
  const [version, setVersion] = useState(0);
  const registry = useMemo(() => ({
    set(token, protection) { registrations.current.set(token, protection); setVersion(value => value + 1); },
    remove(token) { registrations.current.delete(token); setVersion(value => value + 1); },
  }), []);
  const shouldBlock = useCallback(({ currentLocation, nextLocation }) => {
    const mounted = [...registrations.current.entries()].reverse();
    const active = mounted.filter(([, item]) => item.when);
    // A successful save/explicit local discard releases only its own scope.
    // Other dirty editors still own their confirmation for this navigation.
    const bypassed = mounted.filter(([, item]) => item.bypassRef?.current);
    excluded.current = new Set(bypassed.map(([token]) => token));
    for (const [, item] of bypassed) item.bypassRef.current = false;
    const selected = active.find(([token]) => !excluded.current.has(token));
    if (!selected) return false;
    // Keep the visible dialog in charge when its save/close is what attempted
    // navigation; otherwise its focus trap would hide a lower editor's prompt.
    const [token] = bypassed[0] || selected;
    if (currentLocation.pathname === nextLocation.pathname && currentLocation.search === nextLocation.search
      && currentLocation.hash === nextLocation.hash) return false;
    owner.current = token;
    return true;
  }, []);
  const blocker = useBlocker(shouldBlock);
  useEffect(() => {
    const warn = event => {
      if (![...registrations.current.values()].some(item => item.when && !item.bypassRef?.current)) return;
      event.preventDefault(); event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);
  useLayoutEffect(() => {
    if (blocker.state !== 'blocked') return;
    const protection = registrations.current.get(owner.current);
    const currentScopes = () => [...registrations.current.entries()].reverse()
      .filter(([token, item]) => item.when && !excluded.current.has(token));
    if (!protection || (!protection.when && !excluded.current.has(owner.current))) {
      blocker.reset();
      protection?.onBlocked({ cancelled: true });
      return;
    }
    const notify = scopes => {
      if (scopes.some(([, item]) => isPending(item))) {
        // Explicit draft deletion is part of an already approved departure.
        // Hold it in place until cleanup completes; new attempts remain blocked.
        if (protection.holdRef?.current) return;
        blocker.reset(); protection.onBlocked({ pending: true }); return;
      }
      const acknowledged = new Map(scopes.map(([token, item]) => [token, item.label]));
      protection.onBlocked({ pending: false, scopeLabels: scopes.map(([, item]) => item.label || 'Weitere ungespeicherte Eingaben'),
        reset: blocker.reset, proceed: () => {
          const now = currentScopes();
          if (now.some(([, item]) => isPending(item))) {
            blocker.reset(); protection.onBlocked({ pending: true }); return false;
          }
          // A new editor becoming dirty after the question requires a fresh
          // confirmation showing its scope before anything can be discarded.
          if (now.some(([token, item]) => !acknowledged.has(token) || acknowledged.get(token) !== item.label)) {
            notify(now); return false;
          }
          blocker.proceed();
          return true;
        } });
    };
    notify(currentScopes());
  }, [blocker, version]);
  return <NavigationProtectionContext.Provider value={registry}>{children}</NavigationProtectionContext.Provider>;
}

// Outside the application provider the caller's local close/unload guards stay
// in charge. This also preserves plain MemoryRouter and component-only callers.
export default function UnsavedNavigationGuard({ when, pending = false, bypassRef, holdRef, onBlocked, label }) {
  const registry = useNavigationProtection();
  const [token] = useState(() => Symbol('navigation-protection'));
  const callback = useRef(onBlocked);
  useLayoutEffect(() => { callback.current = onBlocked; }, [onBlocked]);
  const notify = useCallback(request => callback.current(request), []);
  useLayoutEffect(() => {
    registry?.set(token, { when, pending, bypassRef, holdRef, onBlocked: notify, label });
  }, [registry, token, when, pending, bypassRef, holdRef, notify, label]);
  useLayoutEffect(() => () => registry?.remove(token), [registry, token]);
  return null;
}

export function NavigationScopeNotice({ labels, locale }) {
  if (!labels?.length) return null;
  const text = { en: 'Leaving discards unsaved changes in all of these editors:', es: 'Al salir se descartan los cambios sin guardar en todos estos editores:',
    de: 'Beim Verlassen werden die ungespeicherten Änderungen in allen folgenden Bereichen verworfen:' }[locale?.slice(0, 2)]
    || 'Beim Verlassen werden die ungespeicherten Änderungen in allen folgenden Bereichen verworfen:';
  return <div><p>{text}</p><ul>{labels.map((label, index) => <li key={index}>{label}</li>)}</ul></div>;
}
