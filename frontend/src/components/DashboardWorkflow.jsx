import { useState } from 'react';
import { Link } from 'react-router-dom';
import { buildDashboardWorkflow } from '../utils/dashboardWorkflow';
import { ArrowRightIcon, PortfolioIcon, ContractIcon, AccountIcon, StatementIcon, MaintenanceIcon } from './Icons';
import './DashboardWorkflow.css';

const ICONS = { portfolio: PortfolioIcon, rental: ContractIcon, finance: AccountIcon, billing: StatementIcon, operations: MaintenanceIcon };
const AREA_NAMES = { portfolio: 'Bestand', rental: 'Vermietung', finance: 'Finanzen', billing: 'Abrechnung', operations: 'Betrieb' };
const TONE_ORDER = { critical: 0, warning: 1, info: 2 };

function translate(t, key, fallback, params) {
  const value = t(key, params);
  if (value && value !== key) return value;
  return Object.entries(params || {}).reduce((result, [name, replacement]) => result.replace(`{{${name}}}`, replacement), fallback || '');
}

function areaStep(step, stats, t) {
  // The former checklist labels described its done flag, not these open counts.
  const key = step.labelKey.split('.').pop();
  if (key === 'receivablesClear') return { label: 'Offene Forderungen', count: stats.openReceivables };
  if (key === 'tasksClear') return { label: 'Offene Aufgaben', count: stats.openTasks };
  if (key === 'maintenanceClear') return stats.overdueMaintenance > 0
    ? { label: 'Überfällige Instandhaltung', count: stats.overdueMaintenance }
    : { label: 'Offene Instandhaltung', count: stats.openMaintenance };
  if (key === 'documents' && stats.missingContractDocuments > 0) return { label: 'Fehlende Vertragsdokumente', count: stats.missingContractDocuments };
  if (key === 'invoices') return { label: 'Offene Rechnungen', count: stats.openInvoices };
  if (key === 'statements') return { label: 'Abrechnungen', count: stats.utilityStatements };
  return { label: translate(t, step.labelKey, step.fallback), count: step.count };
}

export default function DashboardWorkflow({ stats, expiring, notifications, t, section = 'attention', statsReady = true, complete = true }) {
  const [expanded, setExpanded] = useState(false);
  const { workflows, attentionItems, processSteps } = buildDashboardWorkflow({ stats, expiring, notifications });
  if (section === 'areas') return <section className="dashboard-work-areas" aria-labelledby="dashboard-areas-heading">
    <div className="dashboard-section-heading"><div><h2 id="dashboard-areas-heading">Verwaltungsbereiche</h2><p>Die passenden Werkzeuge für jeden Arbeitsschritt.</p></div></div>
    <div className="dashboard-area-list">{workflows.map(item => {
      const Icon = ICONS[item.id] || PortfolioIcon;
      return <details className="dashboard-area" key={item.id}>
        <summary><span className="dashboard-area-icon"><Icon size={18} /></span><strong>{AREA_NAMES[item.id]}</strong>{statsReady && <span className="dashboard-area-metric">{translate(t, item.metricKey, item.metricFallback, { count: item.metricCount })}</span>}<span className="dashboard-area-chevron" aria-hidden="true">⌄</span></summary>
        <div className="dashboard-area-content"><p>{translate(t, item.descriptionKey, item.descriptionFallback)}</p><div className="dashboard-area-links">{item.steps.map(step => {
          const display = areaStep(step, stats, t);
          return <Link key={step.labelKey} to={step.to} aria-label={statsReady ? `${display.label} ${display.count}` : display.label}><span>{display.label}</span>{statsReady && <strong>{display.count}</strong>}</Link>;
        })}</div><Link className="dashboard-area-action" to={item.actionTo}>Bereich öffnen <ArrowRightIcon size={14} /></Link></div>
      </details>;
    })}</div>
    <details className="dashboard-setup"><summary>Einrichtung im Überblick</summary><p>Vorhandene Grundlagen und direkte Einstiege in Ihre Verwaltung.</p><ol>{processSteps.map(step => <li key={step.id}><Link to={step.to}><span>{translate(t, step.labelKey, step.fallback)}</span>{statsReady && <strong>{step.count}</strong>}<ArrowRightIcon size={13} /></Link></li>)}</ol></details>
  </section>;

  const items = [...attentionItems].sort((left, right) => TONE_ORDER[left.tone] - TONE_ORDER[right.tone]);
  const shown = expanded ? items : items.slice(0, 4);
  return <section className="dashboard-attention" aria-labelledby="dashboard-attention-heading">
    <div className="dashboard-section-heading"><div><p className="dashboard-eyebrow">Im Fokus</p><h2 id="dashboard-attention-heading">Handlungsbedarf</h2><p>Offene Vorgänge nach ihrer Dringlichkeit.</p></div><Link to="/review" className="dashboard-review-link">Prüfliste <ArrowRightIcon size={14} /></Link></div>
    {!complete && <p className="dashboard-attention-incomplete" role="status">Die Übersicht ist noch unvollständig. Ladezustände und Wiederholung finden Sie beim jeweiligen Bereich.</p>}
    {shown.length ? <ul className="dashboard-attention-list">{shown.map(item => <li key={item.id}><Link to={item.to} className={`dashboard-attention-item tone-${item.tone}`}><span className="dashboard-attention-dot" aria-hidden="true" /><span>{translate(t, item.titleKey, item.titleFallback)}</span><strong>{item.value}</strong><ArrowRightIcon size={15} /></Link></li>)}</ul> : complete ? <div className="dashboard-attention-empty"><strong>Keine offenen Hinweise aus den geladenen Daten.</strong><p>Ihre Aufgaben und kommenden Vertragsfristen finden Sie darunter.</p></div> : null}
    {items.length > 4 && <button type="button" className="dashboard-attention-more" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? 'Weniger anzeigen' : `Alle ${items.length} Hinweise anzeigen`}</button>}
  </section>;
}
