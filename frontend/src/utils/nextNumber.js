/** The number after the highest one in use, in its pattern (MV-2024-007 → MV-2024-008), never one
 * that exists already; `fallback` while there is none. */
export function nextNumber(existing, fallback) {
  const taken = new Set(existing.map(value => String(value || '').trim()).filter(Boolean));
  let best = null;
  for (const value of taken) {
    const match = /^(.*?)(\d+)(\D*)$/.exec(value);
    if (!match) continue;
    const number = Number(match[2]);
    if (!best || number > best.number) best = { prefix: match[1], number, width: match[2].length, suffix: match[3] };
  }
  if (!best) return taken.has(fallback) ? `${fallback}-2` : fallback;
  let next = best.number + 1;
  const format = n => `${best.prefix}${String(n).padStart(best.width, '0')}${best.suffix}`;
  while (taken.has(format(next))) next += 1;
  return format(next);
}
