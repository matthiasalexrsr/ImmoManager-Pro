import { useCallback, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { workspace } from '../../utils/workspaceClient';
import { PartyLink } from '../partyWorkspace/PartyWorkspace';
import { ENTITY_SHELF_CHANGED } from './entityShelfEvents';
import useCursorFeed from './useCursorFeed';
import FeedState from './FeedState';
import './workCenter.css';

export default function EntityShelf() {
  const auth = useAuth();
  if (!auth?.user?.id) return null;
  return <div className="work-shelves" key={auth.user.id}>
    <Shelf resource="favorites" title="Gemerkte Vorgänge" />
    <Shelf resource="recents" title="Zuletzt geöffnet" />
  </div>;
}

function Shelf({ resource, title }) {
  const load = useCallback((path, options) => workspace.list(resource,
    Object.fromEntries(new URLSearchParams(path.split('?')[1] || '')), options), [resource]);
  const feed = useCursorFeed(`/workspace/${resource}?limit=8`, true, load);
  useEffect(() => {
    window.addEventListener(ENTITY_SHELF_CHANGED, feed.retry);
    return () => window.removeEventListener(ENTITY_SHELF_CHANGED, feed.retry);
  }, [feed.retry]);
  return <section className="work-shelf" aria-label={title}><h2>{title}</h2>
    <ul className="work-shelf-list">{feed.items.map(item => <li key={`${item.kind}:${item.entity_id}`}>
      {item.kind === 'tenant' ? <PartyLink tenantId={item.entity_id}>{item.title}</PartyLink> : <Link to={item.href}>{item.title}</Link>}
    </li>)}</ul>
    <FeedState feed={feed} empty={resource === 'favorites' ? 'Merken Sie Vorgänge direkt in der Objekt-, Einheiten- oder Parteienakte.' : 'Ihre geöffneten Akten erscheinen hier.'} />
  </section>;
}
