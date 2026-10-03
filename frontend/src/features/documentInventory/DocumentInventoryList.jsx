import ReferenceChoice from '../unitInventory/ReferenceChoice';
import { errorMessage } from '../unitInventory/read';
import '../unitInventory/UnitInventory.css';

export default function DocumentInventoryList({ listing, principal, types, onAdd, onEdit, onDelete, onView, onHistory }) {
  const { filters, change, state, page, failure, stats, summary } = listing;
  return <>
    <section aria-label="Kennzahlen der gefilterten Dokumente" className="inventory-summary">
      {summary.loading ? <p role="status">Kennzahlen werden berechnet …</p> : stats ?
        [[stats.total, 'Dokumente'], [stats.with_file, 'Mit Dateiverweis'], [stats.analyzed, 'Analyse gespeichert'], [stats.no_assignment, 'Ohne Zuordnung']].map(([value, label]) => <div className="panel" key={label}><strong>{value}</strong><span>{label}</span></div>)
        : <div role="alert">Kennzahlen nicht verfügbar. {errorMessage(summary.error)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    </section>
    <section className="panel inventory-filters" aria-label="Dokumente filtern">
      <label>Dokumente durchsuchen<input type="search" value={filters.search} onChange={event => change('search', event.target.value)} placeholder="Titel, Tags oder Zuordnung" /></label>
      <label>Dokumententyp<select value={filters.document_type} onChange={event => change('document_type', event.target.value)}><option value="">Alle Typen</option>{types.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      <label>Prüfansicht<select value={filters.view} onChange={event => change('view', event.target.value)}>{[['all', 'Alle Dokumente'], ['no_assignment', 'Ohne Zuordnung'], ['not_analyzed', 'Ohne gespeicherte Analyse'], ['analyzed', 'Analyse gespeichert'], ['with_file', 'Mit Dateiverweis'], ['without_file', 'Ohne Dateiverweis']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Datum von<input type="date" value={filters.date_from} onChange={event => change('date_from', event.target.value)} /></label>
      <label>Datum bis<input type="date" value={filters.date_to} onChange={event => change('date_to', event.target.value)} /></label>
      <label>Sortierung<select value={filters.sort_by} onChange={event => change('sort_by', event.target.value)}>{[['title', 'Titel'], ['document_date', 'Dokumentdatum'], ['updated_at', 'Zuletzt geändert'], ['document_type', 'Dokumententyp'], ['property_name', 'Immobilie'], ['unit_label', 'Einheit'], ['contract_label', 'Vertrag']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Reihenfolge<select value={filters.sort_order} onChange={event => change('sort_order', event.target.value)}><option value="asc">Aufsteigend</option><option value="desc">Absteigend</option></select></label>
      <details className="inventory-property-filter"><summary>Immobilie auswählen{filters.property_id ? ' · Filter aktiv' : ''}</summary><ReferenceChoice kind="properties" label="Immobilie" value={filters.property_id} onChange={value => change('property_id', value)} principal={principal} /></details>
      <button className="btn btn-secondary" onClick={listing.reset}>Filter zurücksetzen</button>
    </section>
    <div className="inventory-actions"><button className="btn btn-secondary" onClick={listing.refresh}>Aktualisieren</button>
      <button className="btn btn-secondary" disabled={listing.exporting} onClick={listing.download}>{listing.exporting ? 'Export wird erstellt …' : 'Alle gefilterten Dokumente exportieren'}</button>
      {onAdd && <button className="btn btn-primary" onClick={onAdd}>Dokument erstellen</button>}</div>
    {listing.exportError && <div className="panel inventory-error" role="alert">{errorMessage(listing.exportError)}</div>}
    {state.loading && <p role="status">Dokumente werden geladen …</p>}
    {failure && <div className="panel inventory-error" role="alert">{errorMessage(failure)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    {page && <section className="panel inventory-results" aria-label="Gefilterte Dokumente">
      {!page.items.length ? <p>Keine passenden Dokumente auf dieser Seite.</p> : <div className="inventory-table-scroll" tabIndex={0} role="region" aria-label="Dokumententabelle horizontal scrollen"><table>
        <thead><tr>{['Dokument', 'Typ', 'Zuordnung', 'Datum', 'Analyse', 'Aktionen'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{page.items.map(row => <tr key={row.id}><th scope="row">{row.file_url ? <button className="btn btn-secondary btn-sm" onClick={() => onView(row)}>{row.title}</button> : row.title}</th>
          <td>{row.document_type || '—'}{row.tags && <p>{row.tags}</p>}</td><td>{[row.property_name, row.unit_label, row.contract_label].filter(Boolean).join(' · ') || 'Ohne Zuordnung'}</td>
          <td>{row.document_date || '—'}</td><td>{row.ai_analyzed_at ? 'Analyse gespeichert' : 'Keine Analyse gespeichert'}</td>
          <td><div className="inventory-actions"><button className="btn btn-secondary btn-sm" onClick={() => onHistory(row)} aria-label={`${row.title} Versionshistorie`}>Versionen</button>
            {onEdit && <button className="btn btn-secondary btn-sm" onClick={() => onEdit(row)} aria-label={`${row.title} bearbeiten`}>Bearbeiten</button>}
            {onDelete && <button className="btn btn-secondary btn-sm" onClick={() => onDelete(row)} aria-label={`${row.title} löschen`}>Löschen</button>}</div></td></tr>)}</tbody></table></div>}
      <nav className="inventory-pager" aria-label="Dokumentseiten"><button className="btn btn-secondary" disabled={listing.pageNumber === 1} onClick={listing.previous}>Vorherige Seite</button><span>Seite {listing.pageNumber}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={listing.next}>Nächste Seite</button></nav>
      <p className="text-muted">Kennzahlen und CSV umfassen alle passenden Dokumente. „Analyse gespeichert“ bezeichnet vorhandene Analysedaten; daraus folgt kein laufender OCR-Auftrag. Der CSV-Export enthält Metadaten.</p>
    </section>}
  </>;
}
