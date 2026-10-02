import { useEffect, useState } from 'react';

export async function resolvePinnedReference(loadPage, id, { signal } = {}) {
  if (!id || typeof loadPage !== 'function') return null;
  const page = await loadPage({
    cursor: null,
    search: '',
    selectedId: id,
    limit: 1,
    signal,
  });
  if (!page || !Array.isArray(page.items)) throw new Error('invalid_reference_page');
  if (page.selected?.id === id) return page.selected;
  return page.items.find(item => item?.id === id) || null;
}

function sameBinding(state, loadPage, id, principalKey) {
  return state.id === id
    && state.loadPage === loadPage
    && state.principalKey === principalKey;
}

export function usePinnedReference(loadPage, id, principalKey = '') {
  const [resolved, setResolved] = useState(() => ({
    id: null,
    loadPage: null,
    principalKey: null,
    value: undefined,
  }));

  const value = sameBinding(resolved, loadPage, id, principalKey)
    ? resolved.value
    : undefined;

  useEffect(() => {
    const controller = new AbortController();
    const binding = { id, loadPage, principalKey };
    setResolved({ ...binding, value: undefined });
    if (!id || typeof loadPage !== 'function') return () => controller.abort();

    resolvePinnedReference(loadPage, id, { signal: controller.signal })
      .then(result => {
        if (!controller.signal.aborted) setResolved({ ...binding, value: result });
      })
      .catch(error => {
        if (!controller.signal.aborted && error?.name !== 'AbortError') {
          setResolved({ ...binding, value: null });
        }
      });

    return () => controller.abort();
  }, [id, loadPage, principalKey]);

  return value;
}
