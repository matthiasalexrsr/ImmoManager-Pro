import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal } from 'lucide-react';
import './RowActionMenu.css';

/** The rarer actions of a table row behind one "⋯" button, each with its icon and label.
 *  items: [{ key, label, icon, onSelect, danger }]. The list is placed on the page, not in the
 *  table, so a scrolling table cannot cut it off. */
export default function RowActionMenu({ items, label = 'Weitere Aktionen', description }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState(null);
  const button = useRef(null);
  const list = useRef(null);

  useLayoutEffect(() => {
    if (!open || !button.current || !list.current) return;
    const anchor = button.current.getBoundingClientRect();
    const menu = list.current.getBoundingClientRect();
    const below = anchor.bottom + 4 + menu.height <= window.innerHeight - 8;
    setPlace({
      top: below ? anchor.bottom + 4 : Math.max(8, anchor.top - 4 - menu.height),
      left: Math.max(8, Math.min(anchor.right - menu.width, window.innerWidth - menu.width - 8)),
    });
  }, [open]);

  // Only a placed (visible) list can take the focus.
  useEffect(() => {
    if (open && place) list.current?.querySelector('[role="menuitem"]')?.focus();
  }, [open, place]);

  useEffect(() => {
    if (!open) return undefined;
    const close = event => {
      if (list.current?.contains(event.target) || button.current?.contains(event.target)) return;
      setOpen(false);
    };
    const shut = () => setOpen(false);
    document.addEventListener('mousedown', close);
    window.addEventListener('resize', shut);
    window.addEventListener('scroll', shut, true);
    return () => {
      document.removeEventListener('mousedown', close);
      window.removeEventListener('resize', shut);
      window.removeEventListener('scroll', shut, true);
    };
  }, [open]);

  const onKeyDown = event => {
    const entries = [...(list.current?.querySelectorAll('[role="menuitem"]') || [])];
    const index = entries.indexOf(document.activeElement);
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.preventDefault();
      setOpen(false);
      button.current?.focus();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      entries[(index + step + entries.length) % entries.length]?.focus();
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      entries[event.key === 'Home' ? 0 : entries.length - 1]?.focus();
    }
  };

  return (
    <>
      <button ref={button} type="button" className="btn btn-sm btn-ghost row-action-menu__toggle"
        aria-label={label} aria-description={description} title={label}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? `${id}-menu` : undefined}
        onClick={() => { setPlace(null); setOpen(value => !value); }}>
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {open && createPortal(
        <ul ref={list} id={`${id}-menu`} role="menu" aria-label={label} className="row-action-menu"
          style={place ? { top: place.top, left: place.left } : { visibility: 'hidden', top: 0, left: 0 }}
          onKeyDown={onKeyDown}>
          {items.map(item => (
            <li key={item.key || item.label} role="none">
              <button type="button" role="menuitem" tabIndex={-1}
                className={`row-action-menu__item${item.danger ? ' row-action-menu__item--danger' : ''}`}
                onClick={event => { setOpen(false); item.onSelect(event); }}>
                {item.icon && <span className="row-action-menu__icon" aria-hidden="true">{item.icon}</span>}
                {item.label}
              </button>
            </li>
          ))}
        </ul>,
        document.body,
      )}
    </>
  );
}
