import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { PlusIcon } from './Icons';
import { newEntryLink } from '../utils/newEntry';

/** "Neu für …": a small menu of New forms of other lists that start with these values
 * (the property, the unit). items: [[listPath, label], …]. */
export default function NewForMenu({ label, items, prefill }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = event => {
      if (event.type === 'keydown' ? event.key === 'Escape' : !ref.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('keydown', close);
    document.addEventListener('mousedown', close);
    return () => { document.removeEventListener('keydown', close); document.removeEventListener('mousedown', close); };
  }, [open]);
  return (
    <div className="dossier-new" ref={ref}>
      <button type="button" className="btn btn-primary btn-sm" aria-expanded={open} aria-haspopup="true"
        onClick={() => setOpen(value => !value)}><PlusIcon size={15} /> {label}</button>
      {open && <ul className="dossier-new-menu">
        {items.map(([path, text]) => {
          const link = newEntryLink(path, prefill);
          return <li key={path}><Link to={link.to} state={link.state}>{text}</Link></li>;
        })}
      </ul>}
    </div>
  );
}
