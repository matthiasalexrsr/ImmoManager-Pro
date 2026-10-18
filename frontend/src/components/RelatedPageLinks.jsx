import { Link } from 'react-router-dom';
import './RelatedPageLinks.css';

// Contextual route navigation belongs to the current record. Unlike action
// buttons, these are ordinary links and support browser history/open-in-new-tab.
export default function RelatedPageLinks({ items = [], label = 'Verknüpfte Seiten' }) {
  const links = items.filter(item => typeof item?.to === 'string' && item.to.startsWith('/')
    && !item.to.startsWith('//') && typeof item.label === 'string' && item.label.trim());
  if (!links.length) return null;
  return <nav className="related-page-links" aria-label={label}>
    <span className="related-page-links__heading">Direkt weiter</span>
    <div className="related-page-links__items">
      {links.map(item => <Link className="related-page-links__link" key={item.to + item.label} to={item.to}>
        <span>{item.label}</span><span className="related-page-links__arrow" aria-hidden="true">↗</span>
      </Link>)}
    </div>
  </nav>;
}
