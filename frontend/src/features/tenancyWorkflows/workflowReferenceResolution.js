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

export function usePinnedReference(loadPage, id, principalKey = '') {
  const [value, setValue] = useState(undefined);

  useEffect(() => {
    const controller = new AbortController();
    setValue(undefined);
    if (!id || typeof loadPage !== 'function') return () => controller.abort();

    resolvePinnedReference(loadPage, id, { signal: controller.signal })
      .then(result => {
        if (!controller.signal.aborted) setValue(result);
      })
      .catch(error => {
        if (!controller.signal.aborted && error?.name !== 'AbortError') setValue(null);
      });

    return () => controller.abort();
  }, [id, loadPage, principalKey]);

  return value;
}
