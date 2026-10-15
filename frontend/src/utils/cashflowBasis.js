// Mirrors finance_ledger.booking_side: refunds and reversals reduce their
// original side rather than becoming unrelated income/expenses.
export function cashflowSide(booking, categories) {
  const categoryType = categories instanceof Map ? categories.get(booking.category_id)
    : categories.find(category => category.id === booking.category_id)?.category_type;
  if (categoryType === 'income' || categoryType === 'expense') return categoryType;
  if (booking.tenant_id) return 'income';
  const positive = Number(booking.amount) > 0;
  return (booking.reverses_booking_id ? !positive : positive) ? 'income' : 'expense';
}
