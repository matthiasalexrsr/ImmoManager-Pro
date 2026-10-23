export default function FeedState({ feed, empty = 'Keine Einträge vorhanden.' }) {
  return <>
    {feed.loading && <p role="status">Wird geladen…</p>}
    {feed.error && <div className="alert alert-error" role="alert">{feed.error} <button type="button" className="btn btn-sm btn-secondary" onClick={feed.retry}>Erneut laden</button></div>}
    {!feed.loading && !feed.error && feed.items.length === 0 && <p className="text-muted">{empty}</p>}
    {feed.next_cursor && <button type="button" className="btn btn-sm btn-secondary" disabled={feed.loadingMore || feed.loading} onClick={feed.loadMore}>{feed.loadingMore ? 'Wird geladen…' : 'Weitere laden'}</button>}
  </>;
}
