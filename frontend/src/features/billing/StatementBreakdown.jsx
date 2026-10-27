import { useRef } from 'react';
import { Link } from 'react-router-dom';
import { entityHref } from '../../utils/entityLinks';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { formatDate, formatMoney, formatNumber } from '../../utils/format';
import StatusBadge from '../../components/StatusBadge';

/** Read the exact calculation; edits belong to the period's shared source costs. */
export default function StatementBreakdown({ statement, period, onClose, onCosts, onLetter }) {
  const dialog = useRef(null);
  const pressStartedOnOverlay = useRef(false);
  useModalDialog(dialog, onClose);
  const frozen = statement.final_document;
  const rows = frozen?.rows || (statement.line_items || []).map(line => [
    line.description || 'Kostenposition', line.total_amount == null ? '—' : formatMoney(line.total_amount),
    line.basis == null ? line.key_name || '—' : `${line.key_name || ''}: ${formatNumber(line.basis)} von ${formatNumber(line.total_basis)} ${line.basis_unit || ''}${line.days != null ? ` · ${line.days}/${line.period_days} Tage` : ''}`,
    formatMoney(line.allocated_amount),
  ]);
  const totals = frozen?.totals || [['Kostenanteil', formatMoney(statement.total_cost)],
    ['Vorauszahlungen', formatMoney(statement.advance_paid)],
    [statement.party === 'vacancy' ? 'Eigentümeranteil' : statement.balance > 0 ? 'Nachzahlung' : statement.balance < 0 ? 'Guthaben' : 'Ausgeglichen',
      formatMoney(statement.party === 'vacancy' ? statement.total_cost : Math.abs(statement.balance))]];
  const advances = frozen ? frozen.advances || [] : (statement.advance_sections || []).map(section => [
    `${formatDate(section.start)} – ${formatDate(section.end)}`, formatMoney(section.monthly), formatMoney(section.amount),
  ]);
  return <div className="modal-overlay" onMouseDown={event => { pressStartedOnOverlay.current = event.target === event.currentTarget; }}
    onClick={event => { if (pressStartedOnOverlay.current && event.target === event.currentTarget) onClose(); pressStartedOnOverlay.current = false; }}>
    <section ref={dialog} className="modal modal-wide billing-breakdown" role="dialog" aria-modal="true" aria-labelledby="billing-breakdown-title" tabIndex={-1}>
      <header className="modal-header"><div><h2 id="billing-breakdown-title">Aufschlüsselung der Abrechnung</h2>
        <p>{frozen?.title || period?.label || 'Einzelabrechnung'}</p></div>
        <button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}>×</button></header>
      <div className="modal-body">
        <StatusBadge status={statement.status} />
        {frozen ? <dl className="billing-facts">{(frozen.facts || []).map(([label, value], index) => <div key={`${label}-${index}`}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          : <p>{statement.unit_label} · {statement.party === 'vacancy' ? 'Leerstand (Eigentümer)' : statement.tenant_name}
            {statement.usage_start && <> · {formatDate(statement.usage_start)} – {formatDate(statement.usage_end)}</>}</p>}
        <p className="text-muted">{frozen ? 'Gespeicherter Inhalt der ausgestellten Fassung. Änderungen erfolgen über eine Korrektur.'
          : 'Berechneter Entwurf. Kosten und Verteilerschlüssel werden gemeinsam im Abrechnungszeitraum bearbeitet.'}</p>
        <div className="billing-table-scroll" role="region" aria-label="Verteilung der Kostenpositionen" tabIndex={0}>
          <table className="data-table"><thead><tr><th>Kostenposition</th><th className="text-right">Gesamtkosten</th><th>Verteilung / Zeitraum</th><th className="text-right">Anteil</th></tr></thead>
            <tbody>{rows.map((row, index) => <tr key={index}>{row.map((value, column) => <td key={column} className={column === 1 || column === 3 ? 'text-right td-num' : 'td-wrap'}>{value}</td>)}</tr>)}</tbody>
          </table>
          {!rows.length && <p>Noch keine Kostenpositionen berechnet.</p>}
        </div>
        {advances.length > 0 && <details><summary>Grundlagen der Vorauszahlungen</summary>
          <div className="billing-table-scroll"><table className="data-table"><thead><tr><th>Zeitraum</th><th className="text-right">Monatlich</th><th className="text-right">Berücksichtigt</th></tr></thead>
            <tbody>{advances.map(([period, monthly, amount], index) => <tr key={index}><td>{period}</td>
              <td className="text-right">{monthly}</td><td className="text-right">{amount}</td></tr>)}</tbody></table></div>
        </details>}
        <dl className="billing-result">{totals.map(([label, value], index) => <div key={`${label}-${index}`}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </div>
      <footer className="modal-footer"><button type="button" className="btn btn-secondary" onClick={onClose}>Schließen</button>
        {statement.contract_id && <Link className="btn btn-secondary" to={entityHref('contract', statement.contract_id)}>Mietvertrag</Link>}
        {statement.party !== 'vacancy' && <Link className="btn btn-secondary" to={`/receivables?${new URLSearchParams({ statement_id: statement.id })}`}>Forderungen & Guthaben</Link>}
        {onCosts && <button type="button" className="btn btn-secondary" onClick={onCosts}>Kostenpositionen bearbeiten</button>}
        {statement.party !== 'vacancy' && <button type="button" className="btn btn-primary" onClick={() => onLetter(statement)}>Anschreiben & PDF</button>}
      </footer>
    </section>
  </div>;
}
