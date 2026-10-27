import { useCallback, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Building2, DoorOpen, FileText, UserRound, Folder } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { workspace } from '../../utils/workspaceClient';
import { PartyLink } from '../partyWorkspace/PartyWorkspace';
import { ENTITY_SHELF_CHANGED } from './entityShelfEvents';
import useCursorFeed from './useCursorFeed';
import FeedState from './FeedState';
import './workCenter.css';

const KINDS = { property: ['Immobilie', Building2], unit: ['Einheit', DoorOpen], tenant: ['Partei', UserRound], contract: ['Mietvertrag', FileText] };

export default function EntityShelf({ onOpen } = {}) {
  const auth = useAuth();
  if (!auth?.user?.id) return null;
  return <div className="work-shelves" key={auth.user.id}>
    <Shelf resource="favorites" title="Gemerkte Vorgänge" onOpen={onOpen} />
    <Shelf resource="recents" title="Zuletzt geöffnet" onOpen={onOpen} />
  </div>;
}

function Shelf({ resource, title, onOpen }) {
  const load = useCallback((path, options) => workspace.list(resource,
    Object.fromEntries(new URLSearchParams(path.split('?')[1] || '')), options), [resource]);
  const feed = useCursorFeed(`/workspace/${resource}?limit=8`, true, load);
  useEffect(() => {
    window.addEventListener(ENTITY_SHELF_CHANGED, feed.retry);
    return () => window.removeEventListener(ENTITY_SHELF_CHANGED, feed.retry);
  }, [feed.retry]);
  return <section className="work-shelf" aria-label={title}><h2>{title}</h2>
    <ul className="work-shelf-list">{feed.items.map(item => {
      const [label, Icon] = KINDS[item.kind] || ['Vorgang', Folder];
      const content = <><Icon size={18} aria-hidden="true" /><span><strong>{item.title}</strong><small>{label}</small></span></>;
      const opened = event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) onOpen?.(); };
      return <li key={`${item.kind}:${item.entity_id}`}>
        {item.kind === 'tenant' ? <PartyLink className="work-shelf-entry" aria-label={`${item.title} · ${label}`} tenantId={item.entity_id} onClick={opened}>{content}</PartyLink>
          : <Link className="work-shelf-entry" aria-label={`${item.title} · ${label}`} to={item.href} onClick={opened}>{content}</Link>}
      </li>;
    })}</ul>
    <FeedState feed={feed} empty={resource === 'favorites' ? 'Merken Sie Vorgänge direkt in der Objekt-, Einheiten- oder Parteienakte.' : 'Ihre geöffneten Akten erscheinen hier.'} />
  </section>;
}
