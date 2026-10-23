// The tiles of the dashboard's work view, in their default order. size: share of the row
// (full, wide + narrow side by side, third: three in a row); narrow screens stack them.
export const TILES = [
  { key: 'reports', label: 'Auswertungen und Finanzplanung', size: 'full' },
  { key: 'inventory', label: 'Bestand im Überblick', size: 'full' },
  { key: 'sources', label: 'Offene Vorgänge nach Quelle', size: 'full' },
  { key: 'attention', label: 'Handlungsbedarf', size: 'wide' },
  { key: 'finance', label: 'Finanzen im Überblick', size: 'narrow' },
  { key: 'tasks', label: 'Offene Aufgaben', size: 'third' },
  { key: 'deadlines', label: 'Vertragsfristen', size: 'third' },
  { key: 'notices', label: 'Ungelesene Hinweise', size: 'third' },
  { key: 'areas', label: 'Verwaltungsbereiche', size: 'full' },
];
const KEYS = TILES.map(tile => tile.key);

export const DEFAULT_LAYOUT = { column_order: KEYS, hidden_columns: [] };

/** A saved layout made safe: unknown tiles dropped, tiles added since then at their default place. */
export function arrange(saved) {
  const order = (Array.isArray(saved?.column_order) ? saved.column_order : []).filter((key, index, all) =>
    KEYS.includes(key) && all.indexOf(key) === index);
  for (const key of KEYS) {
    if (order.includes(key)) continue;
    const before = KEYS.slice(0, KEYS.indexOf(key)).reverse().find(other => order.includes(other));
    order.splice(before ? order.indexOf(before) + 1 : 0, 0, key);
  }
  const hidden = (Array.isArray(saved?.hidden_columns) ? saved.hidden_columns : []).filter(key => KEYS.includes(key));
  return { column_order: order, hidden_columns: [...new Set(hidden)] };
}

export function move(layout, key, delta) {
  const order = [...layout.column_order];
  const from = order.indexOf(key);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= order.length) return layout;
  [order[from], order[to]] = [order[to], order[from]];
  return { ...layout, column_order: order };
}

export function toggle(layout, key) {
  const hidden = layout.hidden_columns.includes(key)
    ? layout.hidden_columns.filter(item => item !== key) : [...layout.hidden_columns, key];
  return { ...layout, hidden_columns: hidden };
}

export function tileOf(key) {
  return TILES.find(tile => tile.key === key);
}
