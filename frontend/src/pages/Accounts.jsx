import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

export default function Accounts() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: portfolios } = useEntities('portfolios', '/portfolios');

  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  const refreshData = () => {
    setLoading(true);
    api.get('/accounts').catch(() => [])
      .then(data => setAccounts(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/accounts').catch(err => { console.warn('[Accounts] load:', err.message); return []; })
      .then(data => { if (!cancelled) setAccounts(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Lookup maps
  const portfolioMap = Object.fromEntries(portfolios.map(p => [p.id, p.name]));

  // Enriched data
  const enriched = useMemo(() => accounts.map(a => ({
    ...a,
    portfolio_name: portfolioMap[a.portfolio_id] || '—',
  })), [accounts, portfolioMap]);

  // Summary stats
  const totalCount = enriched.length;
  const totalBalance = enriched.reduce((s, a) => s + Number(a.balance || 0), 0);

  const columns = [
    { key: 'name', label: t('finance.accounts.form.name') || 'Kontoname', filterType: 'text' },
    { key: 'portfolio_name', label: 'Portfolio', filterType: 'text' },
    { key: 'bank_name', label: t('finance.accounts.form.bank') || 'Bank', filterType: 'text' },
    { key: 'iban', label: 'IBAN' },
    { key: 'account_type', label: t('finance.accounts.form.type') || 'Typ', filterType: 'select' },
    { key: 'balance', label: t('finance.accounts.form.balance') || 'Saldo (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => {
        const n = Number(v);
        if (v == null || isNaN(n)) return '—';
        const cls = n < 0 ? 'text-red' : n > 0 ? 'text-green' : '';
        return <span className={cls}>{n.toFixed(2)} €</span>;
      }},
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

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/accounts', data);
    } else {
      await api.put(`/accounts/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('accounts', 'portfolios', 'bookings');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.name || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/accounts/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('accounts', 'portfolios', 'bookings');
  };

  if (loading) return <div className="page-loading">Lade Konten...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('finance.accounts.title') || 'Konten'}</h1>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{totalCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Anzahl Konten</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: totalBalance < 0 ? 'var(--danger)' : totalBalance > 0 ? 'var(--success)' : undefined }}>{totalBalance.toFixed(2)} €</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamtsaldo</div>
        </div>
      </div>

      <DataTable
        title={t('finance.accounts.title') || 'Konten'}
        columns={columns}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Konto erstellen' : 'Konto bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
