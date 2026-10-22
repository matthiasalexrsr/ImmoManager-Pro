// Mirrors finance_ledger.booking_side: refunds and reversals reduce their
// original side rather than becoming unrelated income/expenses.
export function cashflowSide(booking, categories) {
  const categoryType = categories instanceof Map ? categories.get(booking.category_id)
    : categories.find(category => category.id === booking.category_id)?.category_type;
  if (categoryType === 'income' || categoryType === 'expense') return categoryType;
  const positive = Number(booking.amount) > 0;
  const incoming = booking.reverses_booking_id ? !positive : positive;
  // the owners' own money moves the balance, it is no income or expense
  if (categoryType === 'private') return incoming ? 'contribution' : 'withdrawal';
  if (booking.tenant_id) return 'income';
  return incoming ? 'income' : 'expense';
}
