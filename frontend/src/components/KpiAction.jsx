import './workspace.css';
export default function KpiAction({ label, value, onClick, color }) {
  return <button type="button" className="kpi kpi-action" onClick={onClick} aria-label={`${label}: Quellvorgänge anzeigen`}>
    <span className="kpi-value" style={color ? { color } : undefined}>{value}</span>
    <span className="kpi-label">{label} <span aria-hidden="true">↗</span></span>
  </button>;
}
