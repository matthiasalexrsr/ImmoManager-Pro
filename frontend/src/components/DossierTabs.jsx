import { useId, useRef } from 'react';

/** Automatic activation: these panels are already loaded as part of the dossier. */
export default function DossierTabs({ tabs, value, onChange, children, label = 'Bereiche der Akte' }) {
  const id = useId();
  const ref = useRef(null);
  const keydown = event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = tabs.findIndex(tab => tab.key === value);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowLeft' ? -1 : 1) + tabs.length) % tabs.length;
    onChange(tabs[next].key);
    ref.current?.querySelectorAll('[role="tab"]')[next]?.focus();
  };
  return <>
    <div className="detail-tabs" role="tablist" aria-label={label} ref={ref} onKeyDown={keydown}>
      {tabs.map(tab => <button key={tab.key} type="button" role="tab" id={`${id}-${tab.key}`} aria-controls={`${id}-panel`}
        aria-selected={value === tab.key} tabIndex={value === tab.key ? 0 : -1} className={`detail-tab ${value === tab.key ? 'active' : ''}`}
        onClick={() => onChange(tab.key)}>{tab.label}</button>)}
    </div>
    <div className="detail-tab-content" role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${value}`} tabIndex={0}>{children}</div>
  </>;
}
