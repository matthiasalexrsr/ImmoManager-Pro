import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function TaxRates() {
  const { t } = useTranslation();

  const COLUMNS = [
    { key: 'name', label: t('pages.taxRates.columns.name') || 'Bezeichnung', filterType: 'text' },
    { key: 'rate', label: t('pages.taxRates.columns.rate') || 'Satz (%)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(1)} %` : '—' },
    { key: 'description', label: t('pages.taxRates.columns.description') || 'Beschreibung' },
    { key: 'is_default', label: t('pages.taxRates.columns.isDefault') || 'Standard',
      render: v => v ? (t('pages.taxRates.columns.yes') || 'Ja') : (t('pages.taxRates.columns.no') || 'Nein') },
    { key: 'valid_from', label: t('pages.taxRates.columns.validFrom') || 'Gültig ab', type: 'date' },
    { key: 'valid_until', label: t('pages.taxRates.columns.validUntil') || 'Gültig bis', type: 'date' },
  ];

  const FIELDS = [
    { key: 'name', label: t('pages.taxRates.form.name') || 'Bezeichnung', required: true, placeholder: t('pages.taxRates.form.namePlaceholder') || 'z.B. Regelsteuersatz' },
    { key: 'rate', label: t('pages.taxRates.form.rate') || 'Steuersatz (%)', type: 'number', required: true, placeholder: t('pages.taxRates.form.ratePlaceholder') || 'z.B. 19.0' },
    { key: 'description', label: t('pages.taxRates.form.description') || 'Beschreibung' },
    { key: 'is_default', label: t('pages.taxRates.form.isDefault') || 'Standard', type: 'select', options: [
      { value: 'true', label: t('pages.taxRates.form.yes') || 'Ja' },
      { value: 'false', label: t('pages.taxRates.form.no') || 'Nein' },
    ]},
    { key: 'valid_from', label: t('pages.taxRates.form.validFrom') || 'Gültig ab', type: 'date' },
    { key: 'valid_until', label: t('pages.taxRates.form.validUntil') || 'Gültig bis', type: 'date' },
  ];

  return <CrudPage title={t('pages.taxRates.title') || 'Steuersätze'} endpoint="/tax-rates" columns={COLUMNS} formFields={FIELDS} />;
}
