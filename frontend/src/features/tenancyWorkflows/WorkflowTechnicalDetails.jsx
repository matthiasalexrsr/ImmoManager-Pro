import { workflowText } from './workflowCopy';

function technicalText(value) {
  if (value == null || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export default function WorkflowTechnicalDetails({ locale = 'de-DE', rows = [], children }) {
  const tr = (key, params) => workflowText(locale, key, params);
  const visibleRows = rows.filter(row => row && row.value != null && row.value !== '');

  if (visibleRows.length === 0 && !children) return null;

  return (
    <details className="workflow-technical-details">
      <summary>{tr('technicalDetails')}</summary>
      {visibleRows.length > 0 && (
        <dl>
          {visibleRows.map(row => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd><code>{technicalText(row.value)}</code></dd>
            </div>
          ))}
        </dl>
      )}
      {children}
    </details>
  );
}
