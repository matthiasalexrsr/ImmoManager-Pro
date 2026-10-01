import { useTranslation } from '../i18n';
import FinanceCrudPage from '../components/FinanceCrudPage';
import { useFinanceData } from '../hooks/useFinanceData';

export default function Categories() {
  const { t } = useTranslation();
  const listState = useFinanceData({"items": "/categories", "portfolios": "/portfolios"});
  const { portfolios } = listState.data;

  const COLUMNS = [
    { key: 'name', label: t('pages.categories.columns.name') || 'Name', filterType: 'text' },
    { key: 'category_type', label: t('pages.categories.columns.type') || 'Typ', filterType: 'select' },
  ];

  const fields = [
    { key: 'portfolio_id', label: t('pages.categories.form.portfolio') || 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { key: 'name', label: t('pages.categories.form.name') || 'Name', required: true },
    { key: 'category_type', label: t('pages.categories.form.type') || 'Typ', required: true, type: 'select', options: [
      { value: 'income', label: t('pages.categories.options.income') || 'Einnahme' },
      { value: 'expense', label: t('pages.categories.options.expense') || 'Ausgabe' },
      { value: 'maintenance', label: t('pages.categories.options.maintenance') || 'Instandhaltung' },
      { value: 'other', label: t('pages.categories.options.other') || 'Sonstige' },
    ]},
  ];

  return <FinanceCrudPage relatedKeys={['bookings']} listState={listState} title={t('pages.categories.title') || 'Kategorien'} endpoint="/categories" columns={COLUMNS} formFields={fields} />;
}
