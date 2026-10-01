import { useCallback, useEffect, useRef, useState } from 'react';
import { UsersRound, UserPlus, Search, RefreshCw, Pencil, ShieldCheck } from 'lucide-react';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import FormModal from '../../components/FormModal';
import './UserManagementSection.css';

const roles = ['eigentuemer', 'verwalter', 'buchhaltung', 'techniker', 'readonly'];
const validUser = row => row && typeof row.id === 'string' && row.id.length > 0
  && ['username', 'email', 'full_name'].every(key => typeof row[key] === 'string')
  && roles.includes(row.role) && typeof row.is_active === 'boolean'
  && (row.portfolio_access === undefined || (['all', 'selected'].includes(row.portfolio_access)
    && Array.isArray(row.portfolio_ids) && row.portfolio_ids.every(id => typeof id === 'string' && id.length > 0)
    && new Set(row.portfolio_ids).size === row.portfolio_ids.length
    && (row.portfolio_access !== 'all' || row.portfolio_ids.length === 0)));
// Keep only public account fields in page state, even if an adapter returns extras.
const publicUser = row => ({ ...Object.fromEntries(['id', 'username', 'email', 'full_name', 'role', 'is_active', 'created_at', 'updated_at'].map(key => [key, row[key]])),
  portfolio_access: row.role === 'eigentuemer' ? 'all' : row.portfolio_access || 'all', portfolio_ids: Array.isArray(row.portfolio_ids) ? [...row.portfolio_ids] : [],
  portfolio_access_origin: row.portfolio_access_origin || 'legacy_all' });

export default function UserManagementSection() {
  const { t, locale } = useTranslation();
  const auth = useAuth();
  const currentUser = auth?.user;
  const role = auth?.role || currentUser?.role;
  const canManage = role === 'eigentuemer' || (role === 'verwalter' && currentUser?.portfolio_access !== 'selected');
  const isOwner = role === 'eigentuemer';
  const [source, setSource] = useState({ status: 'loading', users: [], error: null });
  const [portfolios, setPortfolios] = useState([]);
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [editor, setEditor] = useState(null);
  const [message, setMessage] = useState(null);
  const loadController = useRef(null);
  const mutationController = useRef(null);
  const mounted = useRef(false);
  const text = key => t(`userManagement.${key}`);

  const load = useCallback(async () => {
    if (!canManage) return;
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    setSource({ status: 'loading', users: [], error: null });
    try {
      const rows = await api.getAll('/auth/users', { signal: controller.signal });
      if (!Array.isArray(rows) || !rows.every(validUser) || new Set(rows.map(row => row.id)).size !== rows.length) throw new Error(t('userManagement.invalidResponse'));
      const available = isOwner ? await api.getAll('/portfolios', { signal: controller.signal }) : [];
      if (!Array.isArray(available) || !available.every(row => row && typeof row.id === 'string' && typeof row.name === 'string') || new Set(available.map(row => row.id)).size !== available.length) throw new Error(t('userManagement.scopeLoadError'));
      if (mounted.current && !controller.signal.aborted) setPortfolios(available.map(row => ({ id: row.id, name: row.name })));
      if (mounted.current && !controller.signal.aborted) setSource({ status: 'ready', users: rows.map(publicUser), error: null });
    } catch (error) {
      if (mounted.current && !controller.signal.aborted) setSource({ status: 'error', users: [], error: error.message || t('userManagement.loadError') });
    }
  }, [canManage, isOwner, t]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      loadController.current?.abort();
      mutationController.current?.abort();
    };
  }, [load]);

  useEffect(() => {
    setEditor(null); setMessage(null);
    if (!canManage) { setPortfolios([]); setSource({ status: 'idle', users: [], error: null }); }
  }, [currentUser?.id, canManage, isOwner]);

  const canEdit = row => canManage && (isOwner || row.role !== 'eigentuemer');
  const save = async values => {
    if (!canManage || !editor || (editor.mode === 'create' && !isOwner)) throw new Error(text('permissionError'));
    const original = editor.user;
    const creating = editor.mode === 'create';
    if (!creating && !canEdit(original)) throw new Error(text('permissionError'));
    const payload = {};
    for (const key of ['full_name', 'email']) {
      const value = String(values[key] || '').trim();
      if (!value || (key === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))) throw new Error(text(key === 'email' ? 'emailInvalid' : 'nameRequired'));
      if (creating || value !== original[key]) payload[key] = value;
    }
    if (creating) {
      payload.username = String(values.username || '').trim();
      payload.password = String(values.password || '');
      payload.role = values.role;
      if (!payload.username) throw new Error(text('usernameRequired'));
      if (payload.password.length < 12) throw new Error(text('passwordHint'));
      if (!roles.includes(payload.role)) throw new Error(text('roleRequired'));
    } else if (original.id !== currentUser?.id) {
      if (isOwner && values.role !== original.role) {
        if (!roles.includes(values.role)) throw new Error(text('roleRequired'));
        payload.role = values.role;
      }
      const active = values.account_status === 'active';
      if (!['active', 'inactive'].includes(values.account_status)) throw new Error(text('statusRequired'));
      if (active !== original.is_active) payload.is_active = active;
    }
    if (isOwner && (creating || (!editingSelf && original.role !== 'eigentuemer'))) {
      const access = values.role === 'eigentuemer' ? 'all' : values.portfolio_access;
      const ids = access === 'all' ? [] : [...(values.portfolio_ids || [])].sort();
      if (!['all', 'selected'].includes(access) || ids.some(id => !portfolios.some(row => row.id === id))) throw new Error(text('scopeInvalid'));
      if (creating || access !== original.portfolio_access || JSON.stringify(ids) !== JSON.stringify([...original.portfolio_ids].sort())) {
        payload.portfolio_access = access; payload.portfolio_ids = ids;
      }
    }
    if (!Object.keys(payload).length) {
      setMessage(text('unchanged'));
      return;
    }
    const controller = new AbortController();
    mutationController.current = controller;
    const result = creating
      ? await api.post('/auth/users', payload, { signal: controller.signal })
      : await api.patch(`/auth/users/${encodeURIComponent(original.id)}`, payload, { signal: controller.signal });
    if (!validUser(result)) throw new Error(text('savedInvalidResponse'));
    if (!mounted.current || controller.signal.aborted) return;
    const account = publicUser(result);
    setSource(previous => ({ ...previous, users: creating ? [...previous.users, account] : previous.users.map(row => row.id === account.id ? account : row) }));
    if (account.id === currentUser?.id) auth.updateUser?.({ ...currentUser, ...account });
    setMessage(t(creating ? 'userManagement.created' : 'userManagement.updated', { name: account.full_name || account.username }));
  };

  const openEditor = user => { setMessage(null); setEditor(user ? { mode: 'edit', user } : { mode: 'create', user: null }); };
  const creating = editor?.mode === 'create';
  const editingSelf = editor?.user?.id === currentUser?.id;
  const roleOptions = roles.map(value => ({ value, label: text(`roles.${value}`) }));
  const fields = editor ? [
    { key: 'username', label: text('username'), required: creating, readOnly: !creating, autoComplete: creating ? 'off' : undefined, hint: creating ? text('usernameHint') : text('usernameFixed') },
    { key: 'full_name', label: text('fullName'), required: true, autoComplete: 'name' },
    { key: 'email', label: text('email'), type: 'email', required: true, autoComplete: 'email' },
    ...(creating ? [{ key: 'password', label: text('password'), type: 'password', required: true, minLength: 12, autoComplete: 'new-password', hint: text('passwordHint') }] : []),
    ...(creating || (isOwner && !editingSelf) ? [{ key: 'role', label: text('role'), type: 'select', required: true, default: 'readonly', options: roleOptions, hint: text('roleHint'), onChange: value => value === 'eigentuemer' ? { portfolio_access: 'all', portfolio_ids: [] } : {} }] : []),
    ...(isOwner && (creating || (!editingSelf && editor.user.role !== 'eigentuemer')) ? [
      { key: 'portfolio_access', label: text('scopeLabel'), type: 'select', required: true, default: 'selected', options: [{ value: 'selected', label: text('scopeSelected') }, { value: 'all', label: text('scopeAll') }], hint: text('scopeHint'), onChange: value => value === 'all' ? { portfolio_ids: [] } : {} },
      { key: 'portfolio_ids', label: text('scopePortfolios'), type: 'multiselect', options: portfolios.map(row => ({ value: row.id, label: row.name })), hint: text('scopeSelectionHint'), onChange: values => values.length ? { portfolio_access: 'selected' } : {} },
    ] : []),
    ...(!creating && !editingSelf ? [{ key: 'account_status', label: text('status'), type: 'select', required: true, options: [{ value: 'active', label: text('active') }, { value: 'inactive', label: text('inactive') }], hint: text('activationHint') }] : []),
  ] : [];
  const initial = editor?.user ? { ...editor.user, account_status: editor.user.is_active ? 'active' : 'inactive' } : { role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] };
  const search = query.trim().toLocaleLowerCase(locale);
  const users = source.users.filter(row => (!roleFilter || row.role === roleFilter)
    && (!statusFilter || row.is_active === (statusFilter === 'active'))
    && (!search || [row.username, row.full_name, row.email].some(value => value.toLocaleLowerCase(locale).includes(search))))
    .sort((a, b) => a.full_name.localeCompare(b.full_name, locale) || a.username.localeCompare(b.username, locale));
  const filtered = Boolean(query || roleFilter || statusFilter);
  const resetFilters = () => { setQuery(''); setRoleFilter(''); setStatusFilter(''); };
  const scopeSummary = row => row.portfolio_access === 'all' ? text('scopeAll') : row.portfolio_ids.length
    ? (isOwner ? row.portfolio_ids.map(id => portfolios.find(item => item.id === id)?.name || text('scopeUnavailable')).join(', ')
      : t('userManagement.scopeCount', { count: row.portfolio_ids.length })) : text('scopeNone');

  if (!canManage) return null;
  return <section className="panel user-management" aria-labelledby="user-management-title">
    <header className="user-management-heading"><div><span className="user-management-eyebrow"><ShieldCheck size={15} aria-hidden="true" />{text('eyebrow')}</span><h2 id="user-management-title">{text('title')}</h2><p>{text(isOwner ? 'ownerIntro' : 'managerIntro')}</p></div><div className="user-management-header-actions"><button type="button" className="btn btn-secondary" onClick={load} disabled={source.status === 'loading' || Boolean(editor)} aria-label={text('refresh')}><RefreshCw size={16} aria-hidden="true" />{text('refresh')}</button>{isOwner && <button type="button" className="btn btn-primary" onClick={() => openEditor(null)} disabled={source.status !== 'ready'}><UserPlus size={17} aria-hidden="true" />{text('create')}</button>}</div></header>
    {message && <p role="status" className="user-management-success">{message}</p>}
    {source.status === 'loading' && <p role="status" className="user-management-state">{text('loading')}</p>}
    {source.status === 'error' && <div role="alert" className="user-management-error"><div><strong>{text('loadError')}</strong><p>{source.error}</p></div><button type="button" className="btn btn-secondary" onClick={load}>{text('retry')}</button></div>}
    {source.status === 'ready' && <>
      <div className="user-management-summary" aria-label={text('summary')}><span><b>{source.users.length}</b>{text('total')}</span><span><b>{source.users.filter(row => row.is_active).length}</b>{text('active')}</span><span><b>{source.users.filter(row => !row.is_active).length}</b>{text('inactive')}</span></div>
      {source.users.length > 0 && <div className="user-management-filters"><div><label htmlFor="user-management-search">{text('search')}</label><span className="user-management-search"><Search size={17} aria-hidden="true" /><input id="user-management-search" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={text('searchPlaceholder')} /></span></div><div><label htmlFor="user-management-role">{text('role')}</label><select id="user-management-role" value={roleFilter} onChange={event => setRoleFilter(event.target.value)}><option value="">{text('allRoles')}</option>{roleOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div><div><label htmlFor="user-management-status">{text('status')}</label><select id="user-management-status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="">{text('allStatuses')}</option><option value="active">{text('active')}</option><option value="inactive">{text('inactive')}</option></select></div>{filtered && <button type="button" className="btn btn-secondary" onClick={resetFilters}>{text('resetFilters')}</button>}</div>}
      {users.length ? <><p className="user-management-result-count">{t('userManagement.resultCount', { count: users.length, total: source.users.length })}</p><div className="user-management-table-scroll" tabIndex={0} role="region" aria-label={text('table')}><table><caption>{text('table')}</caption><thead><tr><th scope="col">{text('account')}</th><th scope="col">{text('email')}</th><th scope="col">{text('role')}</th><th scope="col">{text('status')}</th><th scope="col">{text('scopeLabel')}</th><th scope="col">{text('actions')}</th></tr></thead><tbody>{users.map(row => <tr key={row.id}><th scope="row"><span className="user-management-name">{row.full_name || row.username}</span><span className="user-management-username">{row.username}{row.id === currentUser?.id && <small>{text('you')}</small>}</span></th><td>{row.email}</td><td><span className={`user-management-role ${row.role === 'eigentuemer' ? 'owner' : ''}`}>{text(`roles.${row.role}`)}</span></td><td><span className={`user-management-status ${row.is_active ? 'active' : 'inactive'}`}>{text(row.is_active ? 'active' : 'inactive')}</span></td><td className="user-management-scope">{scopeSummary(row)}{row.portfolio_access_origin === 'legacy_all' && <small>{text('scopeLegacy')}</small>}</td><td>{canEdit(row) ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => openEditor(row)} aria-label={t('userManagement.editAccount', { name: row.full_name || row.username })}><Pencil size={15} aria-hidden="true" />{text('edit')}</button> : <span className="user-management-protected"><ShieldCheck size={15} aria-hidden="true" />{text('ownerProtected')}</span>}</td></tr>)}</tbody></table></div></> : <div className="user-management-empty"><UsersRound size={31} aria-hidden="true" /><h3>{text(filtered ? 'noMatches' : 'emptyTitle')}</h3><p>{text(filtered ? 'noMatchesHint' : 'emptyHint')}</p>{filtered && <button type="button" className="btn btn-secondary" onClick={resetFilters}>{text('resetFilters')}</button>}</div>}
      <p className="user-management-caption">{text('accountHint')}</p>
    </>}
    {editor && <FormModal key={creating ? 'create' : editor.user.id} title={text(creating ? 'createTitle' : 'editTitle')} fields={fields} initial={initial} onSave={save} onClose={() => setEditor(null)}>
      <p className="user-management-form-note">{text(creating ? 'createHint' : editingSelf ? 'selfHint' : isOwner ? 'editOwnerHint' : 'editManagerHint')}</p>
    </FormModal>}
  </section>;
}
