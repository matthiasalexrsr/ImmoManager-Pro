import CrudPage from './CrudPage';

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'document_type', label: 'Typ', filterType: 'select' },
  { key: 'document_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'tags', label: 'Tags', filterType: 'text' },
];

const FIELDS = [
  { key: 'title', label: 'Titel', required: true },
  { key: 'document_type', label: 'Dokumententyp', type: 'select', options: [
    { value: 'Mietvertrag', label: 'Mietvertrag' },
    { value: 'Rechnung', label: 'Rechnung' },
    { value: 'Nebenkostenabrechnung', label: 'Nebenkostenabrechnung' },
    { value: 'Protokoll', label: 'Protokoll' },
    { value: 'Versicherung', label: 'Versicherung' },
    { value: 'Sonstiges', label: 'Sonstiges' },
  ]},
  { key: 'document_date', label: 'Datum', type: 'date' },
  { key: 'description', label: 'Beschreibung', type: 'textarea' },
  { key: 'tags', label: 'Tags', placeholder: 'kommagetrennt' },
  { key: 'file_url', label: 'Datei-URL', required: true, placeholder: '/dokumente/vertrag.pdf' },
];

export default function Documents() {
  return <CrudPage title="Dokumente" endpoint="/documents" columns={COLUMNS} formFields={FIELDS} />;
}
