import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function Accounts() {
  const { t } = useTranslation();
  const [portfolios, setPortfolios] = useState([]);
  useEffect(() => { api.get('/portfolios').then(setPortfolios).catch(err => console.warn('[Accounts] portfolios:', err.message)); }, []);

  const columns = [
    { key: 'name', label: t('finance.accounts.form.name') || 'Kontoname', filterType: 'text' },
    { key: 'bank_name', label: t('finance.accounts.form.bank') || 'Bank', filterType: 'text' },
    { key: 'iban', label: 'IBAN' },
    { key: 'account_type', label: t('finance.accounts.form.type') || 'Typ', filterType: 'select' },
    { key: 'balance', label: t('finance.accounts.form.balance') || 'Saldo (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  ];

  const fields = [
    { key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { key: 'name', label: t('finance.accounts.form.name') || 'Kontoname', required: true },
    { key: 'bank_name', label: t('finance.accounts.form.bank') || 'Bank' },
    { key: 'iban', label: 'IBAN' },
    { key: 'bic', label: 'BIC' },
    { key: 'account_type', label: t('finance.accounts.form.accountType') || 'Kontotyp', required: true, type: 'select', options: [
      { value: 'Girokonto', label: t('finance.accounts.types.checking') || 'Girokonto' },
      { value: 'Mietkonto', label: t('finance.accounts.types.rent') || 'Mietkonto' },
      { value: 'Sparkonto', label: t('finance.accounts.types.savings') || 'Sparkonto' },
      { value: 'Kautionskonto', label: t('finance.accounts.types.deposit') || 'Kautionskonto' },
    ]},
    { key: 'opening_balance', label: t('finance.accounts.form.openingBalance') || 'Anfangssaldo (€)', type: 'number', default: 0 },
    { key: 'balance', label: t('finance.accounts.form.currentBalance') || 'Aktueller Saldo (€)', type: 'number', default: 0 },
  ];

  return <CrudPage title={t('finance.accounts.title') || 'Konten'} endpoint="/accounts" columns={columns} formFields={fields} />;
}
