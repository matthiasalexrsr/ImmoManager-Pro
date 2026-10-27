import { Link } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { safeInternalHref } from '../utils/internalLinks';
import './RelatedPageLinks.css';

// Contextual route navigation belongs to the current record. Unlike action
// buttons, these are ordinary links and support browser history/open-in-new-tab.
export default function RelatedPageLinks({ items = [], label, heading }) {
  const { locale } = useTranslation();
  const words = { en: ['Related pages', 'Continue to'], es: ['Páginas relacionadas', 'Continuar'], de: ['Verknüpfte Seiten', 'Direkt weiter'] }[locale?.slice(0, 2)] || ['Verknüpfte Seiten', 'Direkt weiter'];
  const links = [...new Map(items.filter(item => safeInternalHref(item?.to) && typeof item.label === 'string' && item.label.trim())
    .map(item => [item.to + '\n' + item.label, item])).values()];
  if (!links.length) return null;
  return <nav className="related-page-links" aria-label={label || words[0]}>
    <span className="related-page-links__heading">{heading || words[1]}</span>
    <div className="related-page-links__items">
      {links.map(item => <Link className="related-page-links__link" key={item.to + item.label} to={item.to}>
        <span>{item.label}</span><span className="related-page-links__arrow" aria-hidden="true">↗</span>
      </Link>)}
    </div>
  </nav>;
}
