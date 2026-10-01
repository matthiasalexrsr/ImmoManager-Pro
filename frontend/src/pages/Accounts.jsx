import useWriteAccess from '../hooks/useWriteAccess';
import { revisionOptions } from '../editRevision';
import { useState, useMemo, useRef } from 'react';
import { api } from '../api';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import AccountBalancePanel from '../components/AccountBalancePanel';
import { centsInput, euroCents, storedCents } from '../utils/accountMoney';

export default function Accounts() {
  const { t, locale } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { data: { accounts, portfolios }, loading, error, reload: refreshData } = useFinanceData({
    accounts: '/accounts',
    portfolios: '/portfolios',
  });

  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/accounts', () => setModal(null));
  const [actionError, setActionError] = useState(null);
  const [auditAccount, setAuditAccount] = useState(null);
  const auditTrigger = useRef(null);
  const openAudit = (identifier, event) => {
    auditTrigger.current = event.currentTarget;
    setAuditAccount(identifier);
  };
  const closeAudit = () => { setAuditAccount(null); auditTrigger.current?.focus(); };
  const editAuditedAccount = async identifier => {
    requireWrite();
    setActionError(null);
    try {
      const current = await api.get(`/accounts/${encodeURIComponent(identifier)}`);
      if (isAllowed()) setModal(current);
    } catch (err) { setActionError(err.message); }
  };
  const repairValues = source => {
    requireWrite();
    setModal({ id: source.account_id, updated_at: source.account_updated_at, repair: true,
      opening_balance: centsInput(source.opening_balance_cents), balance: centsInput(source.comparison_balance_cents) });
  };


  // Lookup maps
  const portfolioMap = Object.fromEntries(portfolios.map(p => [p.id, p.name]));

  // Enriched data
  const enriched = useMemo(() => accounts.map(a => ({
    ...a,
    portfolio_name: portfolioMap[a.portfolio_id] || '—',
  })), [accounts, portfolioMap]);

  // Summary stats
  const totalCount = enriched.length;
  const comparisons = enriched.map(a => storedCents(a.balance));
  const totalBalance = comparisons.some(value => value === null) ? null
    : comparisons.reduce((sum, value) => sum + BigInt(value), 0n).toString();

  const columns = [
    { key: 'name', label: t('finance.accounts.form.name') || 'Kontoname', filterType: 'text' },
    { key: 'portfolio_name', label: 'Portfolio', filterType: 'text' },
    { key: 'bank_name', label: t('finance.accounts.form.bank') || 'Bank', filterType: 'text' },
    { key: 'iban', label: 'IBAN' },
    { key: 'account_type', label: t('finance.accounts.form.type') || 'Typ', filterType: 'select' },
    { key: 'balance', label: t('accountBalance.comparison'), type: 'number', align: 'right', filterType: 'numberRange',
      render: v => {
        const value = storedCents(v);
        return <span>{euroCents(value, locale)}</span>;
      }},
    { key: 'source', label: t('accountBalance.proof'), render: (_value, row) => <button type="button" className="btn btn-sm btn-secondary"
      aria-label={`${t('accountBalance.openAudit')} ${row.name}`} onClick={event => openAudit(row.id, event)}>{t('accountBalance.openAudit')}</button> },
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
    { key: 'opening_balance', label: t('accountBalance.opening'), type: 'number', default: 0, step: '0.01' },
    { key: 'balance', label: t('accountBalance.comparison'), type: 'number', default: 0, step: '0.01' },
  ];

  const handleSave = async (data) => {
    requireWrite();
    if (modal.repair) {
      if (!['opening_balance', 'balance'].every(key => {
        const value = storedCents(data[key]);
        return value !== null && BigInt(value) >= -999999999999n && BigInt(value) <= 999999999999n;
      })) throw new Error(t('accountBalance.validAccountAmounts'));
      await api.patch(`/accounts/${modal.id}`, data);
      setAuditAccount(null);
    } else if (modal === 'create') {
      await api.post('/accounts', data);
    } else {
      await api.put(`/accounts/${modal.id}`, data);
    }
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('accounts', 'portfolios', 'bookings');
  };

  const handleDelete = async (row) => {
    if (!isAllowed()) return;
    if (!await confirm(`"${row.name || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    setActionError(null);
    try {
      if (!isAllowed()) return;
      await api.del(`/accounts/${row.id}`, revisionOptions(row));
      setModal(null);
      refreshData();
      if (store) store.invalidateRelated('accounts', 'portfolios', 'bookings');
    } catch (err) {
      setActionError(err.message);
    }
  };

  return (
    <div className="page">
      {actionError && <div className="alert alert-error" role="alert">{actionError}</div>}
      <h1 className="page-title">{t('finance.accounts.title') || 'Konten'}</h1>
      <button type="button" className="btn btn-secondary" onClick={event => openAudit('', event)}>{t('accountBalance.title')}</button>
      {auditAccount !== null && <AccountBalancePanel key={auditAccount} initialAccount={auditAccount} onClose={closeAudit}
        onEditAccount={canWrite ? editAuditedAccount : undefined} onRepairValues={canWrite ? repairValues : undefined} />}
      {loading || error ? <FinanceLoadState loading={loading} error={error} onRetry={refreshData} /> : <>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{totalCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>{t('accountBalance.accountCount')}</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{euroCents(totalBalance, locale)}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>{t('accountBalance.comparisonTotal')}</div>
        </div>
      </div>
      <p className="text-muted">{t('accountBalance.comparisonTotalHint')}</p>

      <DataTable
        title={t('finance.accounts.title') || 'Konten'}
        columns={columns}
        data={enriched}
        onAdd={canWrite ? () => setModal('create') : undefined}
        onEdit={canWrite ? row => setModal(row) : undefined}
        onDelete={canWrite ? handleDelete : undefined}
      />
      </>}

      {modal && canWrite && (
        <FormModal
          title={modal.repair ? t('accountBalance.repairValues') : modal === 'create' ? 'Konto erstellen' : 'Konto bearbeiten'}
          fields={modal.repair ? fields.filter(field => ['opening_balance', 'balance'].includes(field.key)).map(field => ({ ...field, required: true })) : fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
