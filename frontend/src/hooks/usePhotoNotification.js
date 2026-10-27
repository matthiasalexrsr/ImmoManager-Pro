import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../api';
import { safeInternalHref } from '../utils/internalLinks';

// Opening the correct section is separate from acknowledging a notification.
// PhotoDropZone acknowledges only a photo whose bytes actually finished loading.
export default function usePhotoNotification(parentKind, parentId) {
  const { pathname, search } = useLocation();
  const params = new URLSearchParams(search);
  const noticeId = params.get('notice_id');
  const sourceId = params.get('source_id');
  const requestKey = JSON.stringify([pathname, noticeId, sourceId, parentKind, parentId]);
  const [result, setResult] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!noticeId || !sourceId || !parentId) return;
    const controller = new AbortController();
    let live = true;
    (async () => {
      const same = api.captureSession();
      const { source } = await api.get(`/notifications/${encodeURIComponent(noticeId)}/source`, { signal: controller.signal });
      same();
      if (!live) return;
      const href = safeInternalHref(source?.href);
      const expected = href ? new URL(href, window.location.origin) : null;
      const verified = source?.kind === 'entity_photo' && source.entity_id === sourceId
        && source.values?.entity_type === parentKind && source.values?.entity_id === parentId
        && expected?.pathname === pathname && expected.searchParams.get('source_id') === sourceId;
      setResult({ key: requestKey, open: verified });
    })().catch(error => {
      if (live && error.name !== 'AbortError') setResult({ key: requestKey, error: error.message || 'Die Hinweisquelle konnte nicht geladen werden.' });
    });
    return () => { live = false; controller.abort(); };
  }, [noticeId, sourceId, parentKind, parentId, pathname, requestKey, attempt]);
  return { ...(result?.key === requestKey ? result : {}), retry: () => setAttempt(value => value + 1) };
}
