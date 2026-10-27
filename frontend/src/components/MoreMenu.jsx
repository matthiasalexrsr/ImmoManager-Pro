import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';
import './MoreMenu.css';

/** "Mehr": what a page offers that most people rarely need, each entry with a line saying what it
 *  is for. items: [{ key, label, description, to } | { key, label, description, onSelect }]. */
export default function MoreMenu({ label = 'Mehr', items, align = 'end' }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const button = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = event => {
      if (event.type === 'keydown') {
        if (event.key !== 'Escape') return;
        setOpen(false);
        button.current?.focus();
      } else if (!ref.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('keydown', close);
    document.addEventListener('mousedown', close);
    return () => { document.removeEventListener('keydown', close); document.removeEventListener('mousedown', close); };
  }, [open]);
  const shown = (items || []).filter(Boolean);
  if (!shown.length) return null;
  const content = item => <><span className="more-menu__label">{item.label}</span>
    {item.description && <span className="more-menu__description">{item.description}</span>}</>;
  return (
    <div className={`more-menu more-menu--${align}`} ref={ref}>
      <button ref={button} type="button" className="btn btn-secondary btn-sm more-menu__toggle" aria-expanded={open}
        aria-controls={`${id}-list`} onClick={() => setOpen(value => !value)}>
        {label} <ChevronDown size={15} aria-hidden="true" />
      </button>
      {open && <ul id={`${id}-list`} className="more-menu__list" aria-label={label}>
        {shown.map(item => <li key={item.key || item.label}>
          {item.to ? <Link to={item.to} className="more-menu__item" onClick={() => setOpen(false)}>{content(item)}</Link>
            : <button type="button" className="more-menu__item" onClick={() => { setOpen(false); item.onSelect?.(); }}>{content(item)}</button>}
        </li>)}
      </ul>}
    </div>
  );
}
