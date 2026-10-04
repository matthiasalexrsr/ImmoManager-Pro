import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from '../../i18n';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import FormModal from '../../components/FormModal';
import { api } from '../../api';

const ROLES = ['eigentuemer', 'verwalter', 'buchhaltung', 'techniker', 'readonly'];

export default function UsersSection({ currentUser }) {
  const { t } = useTranslation();
  const toast = useToast();
  const confirm = useConfirm();
  const [users, setUsers] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [modal, setModal] = useState(null); // { kind: 'create' | 'edit' | 'password', user? }

  const isOwner = currentUser?.role === 'eigentuemer';
  const u = (key, params) => t(`pages.settings.users.${key}`, params);
  const roleLabel = (role) => u(`roles.${role}`);

  const load = useCallback(() => {
    api.get('/auth/users')
      .then((data) => { setUsers(data); setLoadError(false); })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => { load(); }, [load]);

  // Managers may only administer read-only accounts (enforced by the backend as well).
  const canManage = (user) => isOwner || user.role === 'readonly';
  const isSelf = (user) => user.id === currentUser?.id;

  const roleOptions = useMemo(
    () => (isOwner ? ROLES : ['readonly']).map((r) => ({ value: r, label: t(`pages.settings.users.roles.${r}`) })),
    [isOwner, t],
  );

  const createFields = useMemo(() => [
    { key: 'username', label: u('username'), required: true },
    { key: 'full_name', label: u('fullName'), required: true },
    { key: 'email', label: u('email'), type: 'email', required: true },
    { key: 'password', label: u('password'), type: 'password', required: true, placeholder: u('passwordHint') },
    { key: 'role', label: u('role'), type: 'select', required: true, options: roleOptions, default: 'readonly' },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [roleOptions, t]);

  const editFields = useMemo(() => {
    const fields = [
      { key: 'full_name', label: u('fullName'), required: true },
      { key: 'email', label: u('email'), type: 'email', required: true },
    ];
    if (isOwner && modal?.user && !isSelf(modal.user)) {
      fields.push({ key: 'role', label: u('role'), type: 'select', required: true, options: roleOptions });
    }
    return fields;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOwner, modal, roleOptions, t]);

  const passwordFields = useMemo(() => [
    { key: 'password', label: u('newPassword'), type: 'password', required: true, placeholder: u('passwordHint') },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t]);

  const handleCreate = async (values) => {
    await api.post('/auth/users', values);
    toast.success(u('saved'));
    load();
  };

  const handleEdit = async (values) => {
    await api.patch(`/auth/users/${modal.user.id}`, values);
    toast.success(u('saved'));
    load();
  };

  const handlePassword = async (values) => {
    await api.post(`/auth/users/${modal.user.id}/password`, values);
    toast.success(u('passwordSaved'));
  };

  const toggleActive = async (user) => {
    if (user.is_active && !(await confirm(u('confirmDeactivate', { name: user.username })))) return;
    try {
      await api.patch(`/auth/users/${user.id}`, { is_active: !user.is_active });
      toast.success(u('saved'));
      load();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async (user) => {
    if (!(await confirm(u('confirmDelete', { name: user.username })))) return;
    try {
      await api.del(`/auth/users/${user.id}`);
      toast.success(u('deleted'));
      load();
    } catch (err) {
      toast.error(err.message);
    }
  };

  return (
    <div className="panel">
      <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{u('title')}</span>
        <button className="btn btn-sm btn-primary" onClick={() => setModal({ kind: 'create' })}>{u('add')}</button>
      </div>
      <div className="panel-body">
        {!isOwner && <div className="alert-info">{u('managerHint')}</div>}
        {loadError && <div className="alert-error" role="alert">{u('loadError')}</div>}
        {users && users.length === 0 && <p className="text-muted">{u('empty')}</p>}
        {users && users.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>{u('username')}</th>
                  <th>{u('fullName')}</th>
                  <th>{u('email')}</th>
                  <th>{u('role')}</th>
                  <th>{u('status')}</th>
                  <th>{u('actions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const manageable = canManage(user);
                  const self = isSelf(user);
                  return (
                    <tr key={user.id}>
                      <td>{user.username} {self && <span className="text-muted">{u('you')}</span>}</td>
                      <td>{user.full_name}</td>
                      <td>{user.email}</td>
                      <td>{roleLabel(user.role)}</td>
                      <td>
                        <span className={`badge ${user.is_active ? 'paid' : 'overdue'}`}>
                          {user.is_active ? u('active') : u('inactive')}
                        </span>
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {manageable && (
                          <>
                            <button className="btn btn-sm btn-secondary" onClick={() => setModal({ kind: 'edit', user })}>{u('edit')}</button>{' '}
                            <button className="btn btn-sm btn-secondary" onClick={() => setModal({ kind: 'password', user })}>{u('resetPassword')}</button>{' '}
                            {!self && (
                              <button className="btn btn-sm btn-secondary" onClick={() => toggleActive(user)}>
                                {user.is_active ? u('deactivate') : u('activate')}
                              </button>
                            )}{' '}
                            {isOwner && !self && (
                              <button className="btn btn-sm btn-danger" onClick={() => handleDelete(user)}>{u('delete')}</button>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modal?.kind === 'create' && (
        <FormModal title={u('add')} fields={createFields} onSave={handleCreate} onClose={() => setModal(null)} />
      )}
      {modal?.kind === 'edit' && (
        <FormModal title={u('edit')} fields={editFields} initial={modal.user} onSave={handleEdit} onClose={() => setModal(null)} />
      )}
      {modal?.kind === 'password' && (
        <FormModal
          title={`${u('resetPassword')}: ${modal.user.username}`}
          fields={passwordFields}
          onSave={handlePassword}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
