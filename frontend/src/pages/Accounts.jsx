import { Link } from 'react-router-dom';
import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import KpiAction from '../components/KpiAction';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { formatIban, formatMoney } from '../utils/format';

export default function Accounts() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const { items: portfolios } = useEntities('portfolios', '/portfolios');

  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [modal, setModal] = useState(null);
  const [basisOpen, setBasisOpen] = useState(false);
  const [drilldown, setDrilldown] = useState(0);

  const refreshData = () => {
    setLoading(true);
    setLoadError(null);
    api.list('/accounts')
      .then(data => { if (!Array.isArray(data)) throw new Error('Konten konnten nicht gelesen werden.'); setAccounts(data); })
      .catch(failure => setLoadError(failure.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.list('/accounts')
      .then(data => { if (!Array.isArray(data)) throw new Error('Konten konnten nicht gelesen werden.'); if (!cancelled) setAccounts(data); })
      .catch(failure => { if (!cancelled) setLoadError(failure.message); })
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
  const totalBalance = enriched.reduce((s, a) => s + Math.round(Number(a.balance || 0) * 100), 0) / 100;

  const columns = [
    // the name opens the account's bookings
    { key: 'name', label: t('finance.accounts.form.name') || 'Kontoname', filterType: 'text',
      render: (v, row) => <Link to={`/bookings?konto=${encodeURIComponent(row.id)}`} className="entity-link" onClick={e => e.stopPropagation()}>{v}</Link> },
    { key: 'portfolio_name', label: 'Portfolio', filterType: 'text' },
    { key: 'bank_name', label: t('finance.accounts.form.bank') || 'Bank', filterType: 'text' },
    { key: 'iban', label: 'IBAN', render: v => (v ? <span className="cell-iban">{formatIban(v)}</span> : '—') },
    { key: 'account_type', label: t('finance.accounts.form.type') || 'Typ', filterType: 'select' },
    { key: 'balance', label: t('finance.accounts.form.balance') || 'Saldo (€)', type: 'number', sum: true, align: 'right', filterType: 'numberRange',
      render: v => {
        const n = Number(v);
        if (v == null || isNaN(n)) return '—';
        const cls = n < 0 ? 'text-red' : n > 0 ? 'text-green' : '';
        return <span className={cls}>{formatMoney(n)}</span>;
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
    // The balance follows from the opening balance and the bookings.
    { key: 'opening_balance', label: t('finance.accounts.form.openingBalance') || 'Anfangssaldo (€)', type: 'number', default: 0 },
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
    if (!await confirm(`"${row.name || row.id}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    try {
      await api.del(`/accounts/${row.id}`);
    } catch (err) {
      toast.error(err.message);
      return;
    }
    refreshData();
    if (store) store.invalidateRelated('accounts', 'portfolios', 'bookings');
  };

  if (loading && !modal) return <div className="page-loading">Lade Konten...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('finance.accounts.title') || 'Konten'}</h1>
      {loadError && <p className="alert-error" role="alert">Konten konnten nicht aktualisiert werden. {loadError}<button type="button" className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></p>}

      {/* Summary cards */}
      {!loadError && <div className="kpi-row">
        <KpiAction label="Anzahl Konten" value={totalCount} onClick={() => setDrilldown(value => value + 1)} />
        <KpiAction label="Gesamtsaldo" value={formatMoney(totalBalance)} onClick={() => setBasisOpen(value => !value)} />
      </div>}
      {basisOpen && !loadError && <section aria-label="Grundlage des Gesamtsaldos" className="draft-recovery"><h2>Grundlage des Gesamtsaldos</h2>
        <p>Der Saldo besteht aus dem erfassten Anfangssaldo und den Buchungen jedes Kontos.</p>
        <div className="table-scroll"><table className="data-table"><thead><tr><th>Konto</th><th>Anfangssaldo</th><th>Buchungen netto</th><th>Saldo</th></tr></thead><tbody>{enriched.map(account => <tr key={account.id}>
          <td><Link to={`/bookings?konto=${encodeURIComponent(account.id)}`}>{account.name}</Link></td>
          <td>{formatMoney(account.opening_balance || 0)}</td><td>{formatMoney((Math.round(Number(account.balance || 0) * 100) - Math.round(Number(account.opening_balance || 0) * 100)) / 100)}</td><td>{formatMoney(account.balance || 0)}</td>
        </tr>)}</tbody></table></div></section>}

      <DataTable
        title={t('finance.accounts.title') || 'Konten'}
        columns={columns}
        data={enriched}
        drilldownKey={drilldown}
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
