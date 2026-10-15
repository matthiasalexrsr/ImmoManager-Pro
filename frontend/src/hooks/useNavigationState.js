import { useEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { privateStorageKey } from '../utils/workspaceIdentity';

export function markWorkspaceRow(context, id) {
  try { sessionStorage.setItem(privateStorageKey(`row-mark:${context}`), String(id)); } catch { /* optional */ }
}
export function readWorkspaceRow(context) {
  try { return sessionStorage.getItem(privateStorageKey(`row-mark:${context}`)); } catch { return null; }
}

// Keep each concrete address independent. POP restores once content is tall enough;
// it does not snap back after the user has started scrolling or typing.
export default function useNavigationState() {
  const { pathname, search } = useLocation();
  const navigation = useNavigationType();
  const owner = useAuth()?.user?.id;
  const last = useRef(null);
  useEffect(() => {
    if (!owner) return;
    const key = privateStorageKey(`scroll:${pathname}${search}`);
    const node = document.querySelector('.main-content-body');
    const targets = [node, document.querySelector('.main-content'), document.scrollingElement].filter(Boolean);
    const read = () => targets.map(target => ({ top: target.scrollTop, left: target.scrollLeft }));
    const save = () => { try { sessionStorage.setItem(key, JSON.stringify(read())); } catch { /* optional */ } };
    let saved;
    try { saved = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { saved = null; }
    let cancelled = false;
    const cancel = () => { cancelled = true; };
    let frame;
    let attempts = 0;
    const restore = () => {
      if (cancelled || !saved) return;
      const ready = targets.every((target, index) => !saved[index] || target.scrollHeight >= saved[index].top + target.clientHeight);
      if (ready || ++attempts > 120) {
        targets.forEach((target, index) => { if (saved[index]) { target.scrollTop = saved[index].top; target.scrollLeft = saved[index].left; } });
      } else frame = requestAnimationFrame(restore);
    };
    if (navigation === 'POP') frame = requestAnimationFrame(restore);
    else if (last.current !== key) targets.forEach(target => { target.scrollTop = 0; target.scrollLeft = 0; });
    last.current = key;
    targets.forEach(target => target.addEventListener('scroll', save, { passive: true }));
    window.addEventListener('pagehide', save);
    window.addEventListener('wheel', cancel, { passive: true });
    window.addEventListener('touchstart', cancel, { passive: true });
    window.addEventListener('keydown', cancel);
    return () => {
      save(); cancelAnimationFrame(frame);
      targets.forEach(target => target.removeEventListener('scroll', save));
      window.removeEventListener('pagehide', save); window.removeEventListener('wheel', cancel);
      window.removeEventListener('touchstart', cancel); window.removeEventListener('keydown', cancel);
    };
  }, [pathname, search, navigation, owner]);
}
