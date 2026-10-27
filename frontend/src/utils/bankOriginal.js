export function bankOriginalPath(value) {
  if (typeof value !== 'string') return null;
  const match = /^\/api\/v1\/bank-imports\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/original$/.exec(value);
  return match ? `/bank-imports/${match[1]}/original` : null;
}
