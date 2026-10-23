import { Link, useInRouterContext } from 'react-router-dom';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import { entityHref } from '../utils/entityLinks';

// A click on a name inside a clickable row opens the name, not the row.
const stop = event => event.stopPropagation();

export default function EntityLink({ kind, id, text, children, title }) {
  const inRouter = useInRouterContext();
  const content = children ?? text;
  const empty = content == null || content === '' || content === '—';
  if (empty) return content || '—';
  if (kind === 'tenant') return id ? <PartyLink tenantId={id} title={title}>{content}</PartyLink> : content;
  const href = entityHref(kind, id, typeof text === 'string' ? text : undefined);
  if (!href) return content;
  // outside the app's router (isolated views, tests) a plain link does the same
  if (!inRouter) return <a href={href} className="entity-link" onClick={stop} title={title}>{content}</a>;
  return <Link to={href} className="entity-link" onClick={stop} title={title}>{content}</Link>;
}
