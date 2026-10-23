import { ArrowDown, ArrowUp } from 'lucide-react';
import { DEFAULT_LAYOUT, move, tileOf, toggle } from './dashboardTiles';

/** Which tiles the dashboard shows and in which order; saved for the signed-in person. */
export default function TileSettings({ layout, onChange, onClose }) {
  const order = layout.column_order;
  return <section className="dashboard-tile-settings" aria-label="Kacheln anpassen">
    <div className="dashboard-tile-settings__head">
      <h2>Kacheln anpassen</h2>
      <p>Häkchen entfernen blendet eine Kachel aus; die Pfeile ändern die Reihenfolge. Die Einstellung gilt nur für Sie und wird automatisch gespeichert.</p>
    </div>
    <ol className="dashboard-tile-settings__list">
      {order.map((key, index) => {
        const tile = tileOf(key);
        const shown = !layout.hidden_columns.includes(key);
        return <li key={key} className={shown ? '' : 'is-hidden'}>
          <label><input type="checkbox" checked={shown} onChange={() => onChange(toggle(layout, key))} /> {tile.label}</label>
          <span className="dashboard-tile-settings__moves">
            <button type="button" className="btn btn-sm btn-ghost" aria-label={`${tile.label} nach oben`} disabled={index === 0}
              onClick={() => onChange(move(layout, key, -1))}><ArrowUp size={15} aria-hidden="true" /></button>
            <button type="button" className="btn btn-sm btn-ghost" aria-label={`${tile.label} nach unten`} disabled={index === order.length - 1}
              onClick={() => onChange(move(layout, key, 1))}><ArrowDown size={15} aria-hidden="true" /></button>
          </span>
        </li>;
      })}
    </ol>
    <div className="dashboard-tile-settings__actions">
      <button type="button" className="btn btn-sm btn-secondary" onClick={() => onChange(DEFAULT_LAYOUT)}>Standard wiederherstellen</button>
      <button type="button" className="btn btn-sm btn-primary" onClick={onClose}>Fertig</button>
    </div>
  </section>;
}
