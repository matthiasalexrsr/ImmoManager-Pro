// Shared "delete the selected rows" for DataTable's bulkActions. Each row goes through the
// page's normal DELETE, so a record the server protects (409 with its dependents) is reported
// as failed and stays selected; the others are deleted.
export function bulkDelete({ one, many, remove, finished, label = 'Löschen' }) {
  return {
    key: 'delete',
    label,
    write: true,
    danger: true,
    confirm: rows => `${rows.length} ${rows.length === 1 ? one : many} löschen? Diese Aktion kann nicht rückgängig gemacht werden.`,
    run: remove,
    finished,
  };
}
