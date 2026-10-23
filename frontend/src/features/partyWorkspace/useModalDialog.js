import { useEffect, useRef } from 'react';

const stack = [];
let previousOverflow;
const selector = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])';

/** Only the topmost dialog owns Escape, Tab and focus restoration. */
export function useModalDialog(ref, onClose, active = true) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    const dialog = ref.current;
    if (!active || !dialog) return;
    const priorFocus = document.activeElement;
    const token = { dialog };
    if (stack.length === 0) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
    }
    stack.push(token);
    const elements = () => [...dialog.querySelectorAll(selector)].filter(el => !el.closest('[inert]') && el.getAttribute('aria-hidden') !== 'true');
    const focusFirst = () => (elements()[0] || dialog).focus();
    focusFirst();
    const keydown = event => {
      if (stack.at(-1) !== token) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current?.();
      } else if (event.key === 'Tab') {
        const list = elements();
        const first = list[0] || dialog;
        const last = list.at(-1) || dialog;
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    const focusin = event => {
      if (stack.at(-1) === token && !dialog.contains(event.target)) focusFirst();
    };
    document.addEventListener('keydown', keydown, true);
    document.addEventListener('focusin', focusin);
    return () => {
      document.removeEventListener('keydown', keydown, true);
      document.removeEventListener('focusin', focusin);
      const wasTop = stack.at(-1) === token;
      const index = stack.indexOf(token);
      if (index !== -1) stack.splice(index, 1);
      if (stack.length === 0) document.body.style.overflow = previousOverflow || '';
      if (wasTop && priorFocus?.isConnected) priorFocus.focus();
    };
  }, [active, ref]);
}
