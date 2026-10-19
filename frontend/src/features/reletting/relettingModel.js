// Re-letting project (Neuvermietung): form fields and labels shared by the hub and the project page.

export const PROJECT_STATUS = {
  open: { label: 'Läuft', badge: 'badge-blue' },
  closed: { label: 'Vermietet', badge: 'badge-green' },
  cancelled: { label: 'Abgebrochen', badge: 'badge-gray' },
};

export const APPLICANT_STATUS = {
  new: 'Neu', contacted: 'Kontaktiert', viewing_scheduled: 'Besichtigung geplant', offer_sent: 'Angebot gesendet',
  accepted: 'Als Mieter übernommen', rejected: 'Abgesagt', withdrawn: 'Zurückgezogen',
};
export const APPLICANT_BADGE = {
  new: 'badge-blue', contacted: 'badge-blue', viewing_scheduled: 'badge-yellow', offer_sent: 'badge-yellow',
  accepted: 'badge-green', rejected: 'badge-gray', withdrawn: 'badge-gray',
};
export const VIEWING_STATUS = { scheduled: 'Geplant', completed: 'Wahrgenommen', cancelled: 'Abgesagt', no_show: 'Nicht erschienen' };
export const EMPLOYMENT = {
  permanent: 'Unbefristet angestellt', temporary: 'Befristet angestellt', self_employed: 'Selbstständig',
  retired: 'In Rente / Pension', student: 'In Ausbildung / Studium', other: 'Sonstiges',
};
export const PETS = { allowed: 'Erlaubt', on_request: 'Nach Absprache', not_allowed: 'Nicht erlaubt' };
export const CRITERION_STATE = {
  met: { label: 'erfüllt', symbol: '✓', className: 'reletting-met' },
  not_met: { label: 'nicht erfüllt', symbol: '✕', className: 'reletting-not-met' },
  open: { label: 'offen', symbol: '?', className: 'reletting-open' },
};
export const DOCUMENTS = [
  ['doc_self_disclosure', 'Selbstauskunft'], ['doc_income', 'Einkommensnachweis'],
  ['doc_credit_report', 'Bonitätsauskunft'], ['doc_landlord_reference', 'Vermieterbescheinigung'],
  ['doc_id_checked', 'Ausweis vorgelegt'],
];

const options = map => Object.entries(map).map(([value, label]) => ({ value, label }));
const yesNo = [{ value: 'true', label: 'Ja' }, { value: 'false', label: 'Nein' }];

export const OFFER_FIELDS = [
  { section: 'Angebot', key: 'available_from', label: 'Bezugsfrei ab', type: 'date', noToday: true },
  { section: 'Angebot', key: 'target_rent', label: 'Kaltmiete (€)', type: 'number' },
  { section: 'Angebot', key: 'service_charge', label: 'Nebenkosten-Vorauszahlung (€)', type: 'number' },
  { section: 'Angebot', key: 'heating_charge', label: 'Heizkosten-Vorauszahlung (€)', type: 'number' },
  { section: 'Angebot', key: 'deposit_amount', label: 'Kaution (€)', type: 'number',
    hint: 'Höchstens drei Nettokaltmieten (§ 551 BGB).' },
  { section: 'Vorgaben für den Vergleich', key: 'income_factor', label: 'Einkommen mindestens das … -fache der Warmmiete',
    type: 'number', default: 3, hint: 'Üblich ist das Dreifache; der Vergleich zeigt, wer die Vorgabe erfüllt.' },
  { section: 'Vorgaben für den Vergleich', key: 'max_persons', label: 'Personen höchstens', type: 'number' },
  { section: 'Vorgaben für den Vergleich', key: 'pets', label: 'Haustiere', type: 'select', options: options(PETS) },
  { section: 'Texte für Exposé und Portale', key: 'headline', label: 'Überschrift', full: true },
  { section: 'Texte für Exposé und Portale', key: 'description', label: 'Objektbeschreibung', type: 'textarea' },
  { section: 'Texte für Exposé und Portale', key: 'features_text', label: 'Ausstattung', type: 'textarea' },
  { section: 'Texte für Exposé und Portale', key: 'location_text', label: 'Lage', type: 'textarea' },
  { section: 'Energieausweis (Pflichtangaben in Anzeigen, § 87 GEG)', key: 'energy_certificate', label: 'Art des Energieausweises',
    type: 'select', options: [{ value: 'consumption', label: 'Verbrauchsausweis' }, { value: 'demand', label: 'Bedarfsausweis' },
      { value: 'none', label: 'Kein Energieausweis erforderlich' }] },
  { section: 'Energieausweis (Pflichtangaben in Anzeigen, § 87 GEG)', key: 'energy_value', label: 'Energiekennwert (kWh/(m²·a))', type: 'number' },
  { section: 'Energieausweis (Pflichtangaben in Anzeigen, § 87 GEG)', key: 'energy_class', label: 'Energieeffizienzklasse', type: 'select',
    options: ['A+', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'].map(value => ({ value, label: value })) },
  { section: 'Energieausweis (Pflichtangaben in Anzeigen, § 87 GEG)', key: 'energy_carrier', label: 'Wesentlicher Energieträger',
    placeholder: 'z. B. Erdgas, Fernwärme' },
  { section: 'Energieausweis (Pflichtangaben in Anzeigen, § 87 GEG)', key: 'year_built', label: 'Baujahr laut Energieausweis', type: 'number' },
  { section: 'Energieausweis (Pflichtangaben in Anzeigen, § 87 GEG)', key: 'heating_type', label: 'Heizungsart',
    placeholder: 'z. B. Zentralheizung' },
  { section: 'Kontakt für Interessenten', key: 'contact_name', label: 'Ansprechpartner' },
  { section: 'Kontakt für Interessenten', key: 'contact_phone', label: 'Telefon' },
  { section: 'Kontakt für Interessenten', key: 'contact_email', label: 'E-Mail', type: 'email' },
  { section: 'Intern', key: 'notes', label: 'Notizen', type: 'textarea' },
];
export const OFFER_KEYS = OFFER_FIELDS.map(field => field.key);

export const APPLICANT_FIELDS = [
  { section: 'Kontakt', key: 'full_name', label: 'Name', required: true },
  { section: 'Kontakt', key: 'email', label: 'E-Mail', type: 'email' },
  { section: 'Kontakt', key: 'phone', label: 'Telefon' },
  { section: 'Kontakt', key: 'source', label: 'Quelle', placeholder: 'z. B. ImmoScout24, Aushang, Empfehlung' },
  { section: 'Kontakt', key: 'status', label: 'Status', type: 'select', default: 'new',
    options: options(APPLICANT_STATUS).filter(option => option.value !== 'accepted') },
  { section: 'Angaben zur Bewerbung', key: 'household_size', label: 'Personen im Haushalt', type: 'number' },
  { section: 'Angaben zur Bewerbung', key: 'net_income', label: 'Haushaltsnettoeinkommen je Monat (€)', type: 'number',
    hint: 'Erst nach der Besichtigung erfragen, wenn ernsthaftes Interesse besteht.' },
  { section: 'Angaben zur Bewerbung', key: 'employment', label: 'Beschäftigung', type: 'select', options: options(EMPLOYMENT) },
  { section: 'Angaben zur Bewerbung', key: 'move_in_date', label: 'Gewünschter Einzug', type: 'date', noToday: true },
  { section: 'Angaben zur Bewerbung', key: 'pets', label: 'Haustiere', placeholder: 'keine, oder z. B. eine Katze' },
  { section: 'Angaben zur Bewerbung', key: 'rating', label: 'Eigene Bewertung (1–5)', type: 'select',
    options: [1, 2, 3, 4, 5].map(value => ({ value: String(value), label: `${value} von 5` })) },
  ...DOCUMENTS.map(([key, label]) => ({
    section: 'Unterlagen', key, label: key === 'doc_id_checked' ? 'Ausweis vorgelegt (nur ansehen, nicht kopieren)' : `${label} liegt vor`,
    type: 'select', default: 'false', options: yesNo,
  })),
  { section: 'Notizen', key: 'notes', label: 'Notizen', type: 'textarea' },
];

export const VIEWING_FIELDS = applicants => [
  { key: 'lead_id', label: 'Bewerber', type: 'select', required: true,
    options: applicants.map(row => ({ value: row.id, label: row.full_name })) },
  { key: 'scheduled_at', label: 'Termin', type: 'datetime-local', required: true },
  { key: 'agent', label: 'Durchgeführt von' },
  { key: 'status', label: 'Status', type: 'select', default: 'scheduled', options: options(VIEWING_STATUS) },
  { key: 'rating', label: 'Eindruck (1–5)', type: 'select', hint: 'Nach der Besichtigung festhalten.',
    options: [1, 2, 3, 4, 5].map(value => ({ value: String(value), label: `${value} von 5` })) },
  { key: 'notes', label: 'Notizen zur Besichtigung', type: 'textarea' },
];

// What the forms send: numbers as numbers, empty as null, ratings as integers.
export function offerPayload(values, project) {
  const payload = Object.fromEntries(OFFER_KEYS.map(key => [key, values[key] === '' ? null : values[key] ?? null]));
  if (payload.income_factor == null) payload.income_factor = 3;
  return { ...payload, base_updated_at: project?.updated_at ?? null };
}

export function applicantPayload(values, row) {
  const payload = Object.fromEntries(APPLICANT_FIELDS.map(field => [field.key, values[field.key] === '' ? null : values[field.key] ?? null]));
  payload.rating = payload.rating == null ? null : Number(payload.rating);
  DOCUMENTS.forEach(([key]) => { payload[key] = payload[key] === true || payload[key] === 'true'; });
  if (row?.status === 'accepted') payload.status = 'accepted';
  return { ...payload, base_updated_at: row?.updated_at ?? null };
}

export function viewingPayload(values) {
  return { lead_id: values.lead_id, scheduled_at: values.scheduled_at, status: values.status || 'scheduled',
    agent: values.agent || null, notes: values.notes || null, rating: values.rating ? Number(values.rating) : null };
}
