/** Short text for the users table. */
export function accessSummary(user, portfolios, u) {
  if (user.role === 'eigentuemer' || user.portfolio_access === 'all') return { text: u('summaryAll'), tone: 'neutral' };
  const names = (user.portfolio_ids || [])
    .map(pid => portfolios?.find(p => p.id === pid)?.name)
    .filter(Boolean);
  if (!user.portfolio_ids?.length) return { text: u('summaryNone'), tone: 'warning' };
  return { text: names.length ? names.join(', ') : u('summaryCount', { count: user.portfolio_ids.length }), tone: 'neutral' };
}
