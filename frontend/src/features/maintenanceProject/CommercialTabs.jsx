import { useCallback, useState } from 'react';
import { projectApi } from './projectApi';
import { day, money } from './projectFormat';
import { Empty, Fact, Pill, PickerDialog, Section } from './ProjectUi';

const QUOTE_TONE = { received: 'blue', accepted: 'green', rejected: 'gray' };
const ORDER_TONE = { active: 'blue', completed: 'green', cancelled: 'gray' };
const CHANGE_TONE = { proposed: 'yellow', approved: 'green', rejected: 'gray' };
const cents = value => Math.round(Number(value || 0) * 100);

export function ProcurementTab({ ctx }) {
  const { project, caseId, tx, can, act, openForm, contactOptions, busy } = ctx;
  const packageOptions = project.work_packages.map(wp => ({ value: wp.id, label: wp.title }));
  const orderCosts = Object.fromEntries(project.costs.orders.map(entry => [entry.order_id, entry]));
  const yesNo = [{ value: 'true', label: tx.yes }, { value: 'false', label: tx.no }];

  const quoteFields = [
    { key: 'contact_id', label: tx.contact, type: 'select', options: contactOptions },
    { key: 'supplier_name', label: tx.supplier, hint: tx.supplierHint },
    { key: 'work_package_id', label: tx.workPackage, type: 'select', options: packageOptions },
    { key: 'quote_number', label: tx.quoteNumber },
    { key: 'quote_date', label: tx.quoteDate, type: 'date', required: true },
    { key: 'valid_until', label: tx.validUntil, type: 'date' },
    { key: 'net_amount', label: tx.net, type: 'number', required: true },
    { key: 'gross_amount', label: tx.gross, type: 'number', required: true },
    { key: 'description', label: tx.description, type: 'textarea' },
  ];
  const addQuote = () => openForm({ title: tx.addQuote, fields: quoteFields, onSave: values => projectApi.addQuote(caseId, values) });
  const editQuote = quote => openForm({ title: tx.editQuote, fields: quoteFields, initial: quote,
    onSave: values => projectApi.updateQuote(caseId, quote.id, values) });
  const acceptQuote = quote => openForm({
    title: tx.acceptTitle,
    initial: { order_date: new Date().toISOString().slice(0, 10), reject_competing: 'false' },
    fields: [
      { key: 'order_number', label: tx.orderNumber },
      { key: 'order_date', label: tx.orderDate, type: 'date' },
      { key: 'note', label: tx.note, type: 'textarea' },
      ...(quote.work_package_id ? [{ key: 'reject_competing', label: tx.rejectCompeting, type: 'select', options: yesNo }] : []),
    ],
    onSave: values => projectApi.acceptQuote(caseId, quote.id, { ...values, reject_competing: values.reject_competing === true }),
  });
  const rejectQuote = quote => openForm({ title: tx.rejectTitle, fields: [{ key: 'note', label: tx.reason, type: 'textarea' }],
    onSave: values => projectApi.rejectQuote(caseId, quote.id, values) });
  const cancelOrder = order => openForm({ title: tx.cancelOrderTitle,
    fields: [{ key: 'note', label: tx.reason, type: 'textarea', required: true }],
    onSave: values => projectApi.cancelOrder(caseId, order.id, values) });
  const addChange = order => openForm({
    title: tx.addChangeOrder,
    fields: [
      { key: 'title', label: tx.changeTitle, required: true },
      { key: 'net_amount', label: tx.net, type: 'number', required: true, hint: tx.amountsHint },
      { key: 'gross_amount', label: tx.gross, type: 'number', required: true },
      { key: 'reason', label: tx.changeReason, type: 'textarea' },
    ],
    onSave: values => projectApi.addChangeOrder(caseId, order.id, values),
  });
  const decideChange = (change, approve) => openForm({
    title: approve ? tx.approve : tx.reject, fields: [{ key: 'note', label: tx.note, type: 'textarea' }],
    onSave: values => (approve ? projectApi.approveChangeOrder : projectApi.rejectChangeOrder)(caseId, change.id, values),
  });

  return (
    <div className="mp-stack">
      <Section id="mp-quotes" title={tx.quotes}
        actions={can.record_quotes && <button type="button" className="btn btn-primary btn-sm" onClick={addQuote}>{tx.addQuote}</button>}>
        {project.quotes.length === 0 ? <Empty>{tx.noQuotes}</Empty> : (
          <ul className="mp-cards">
            {project.quotes.map(quote => (
              <li key={quote.id} className="mp-card">
                <div className="mp-card-head">
                  <div className="mp-row-main">
                    <strong>{quote.supplier_name}</strong>
                    <span className="text-muted">
                      {[quote.quote_number, day(quote.quote_date), quote.work_package_title].filter(Boolean).join(' · ')}
                    </span>
                  </div>
                  <Pill tone={QUOTE_TONE[quote.status]}>{tx[`quote_${quote.status}`]}</Pill>
                </div>
                <p className="mp-amounts">
                  <span>{tx.net} {money(quote.net_amount)}</span><strong>{tx.gross} {money(quote.gross_amount)}</strong>
                  {quote.valid_until && <span className="text-muted">{tx.validUntil} {day(quote.valid_until)}</span>}
                  {quote.expired && <Pill tone="red">{tx.expired}</Pill>}
                </p>
                {quote.decision_note && <p className="mp-meta">{quote.decision_note}</p>}
                <div className="mp-actions">
                  {quote.status === 'received' && can.decide_quotes && (
                    <>
                      <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => acceptQuote(quote)}>{tx.accept}</button>
                      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => rejectQuote(quote)}>{tx.reject}</button>
                    </>
                  )}
                  {quote.status === 'received' && can.record_quotes && (
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => editQuote(quote)}>{tx.edit}</button>
                  )}
                  {quote.status !== 'accepted' && can.record_quotes && (
                    <button type="button" className="btn btn-ghost btn-sm"
                      onClick={() => act(() => projectApi.deleteQuote(caseId, quote.id), null, tx.confirmDeleteQuote)}>{tx.delete}</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="mp-orders" title={tx.orders}>
        {project.orders.length === 0 ? <Empty>{tx.noOrders}</Empty> : (
          <ul className="mp-cards">
            {project.orders.map(order => (
              <li key={order.id} className="mp-card">
                <div className="mp-card-head">
                  <div className="mp-row-main">
                    <strong>{[order.order_number, order.supplier_name].filter(Boolean).join(' · ')}</strong>
                    <span className="text-muted">{tx.orderDate} {day(order.order_date)}</span>
                  </div>
                  <Pill tone={ORDER_TONE[order.status]}>{tx[`order_${order.status}`]}</Pill>
                </div>
                <dl className="mp-facts mp-facts-compact">
                  <Fact label={tx.gross}>{money(order.gross_amount)}</Fact>
                  <Fact label={tx.orderedTotal}>{money(orderCosts[order.id]?.ordered)}</Fact>
                  <Fact label={tx.invoiced}>{money(orderCosts[order.id]?.invoiced)}</Fact>
                  <Fact label={tx.paid}>{money(orderCosts[order.id]?.paid)}</Fact>
                </dl>
                {order.cancel_reason && <p className="mp-meta">{order.cancel_reason}</p>}
                <h3 className="mp-subhead">{tx.changeOrders}</h3>
                {order.change_orders.length === 0 ? <Empty>{tx.noChangeOrders}</Empty> : (
                  <ul className="mp-list">
                    {order.change_orders.map(change => (
                      <li key={change.id} className="mp-row">
                        <div className="mp-row-main">
                          <strong>{change.title} · {money(change.gross_amount)}</strong>
                          <span className="text-muted">{[change.reason, change.decision_note].filter(Boolean).join(' · ')}</span>
                        </div>
                        <Pill tone={CHANGE_TONE[change.status]}>{tx[`change_${change.status}`]}</Pill>
                        {change.status === 'proposed' && (
                          <div className="mp-actions">
                            {can.decide_change_orders && order.status !== 'cancelled' && (
                              <>
                                <button type="button" className="btn btn-primary btn-sm" onClick={() => decideChange(change, true)}>{tx.approve}</button>
                                <button type="button" className="btn btn-secondary btn-sm" onClick={() => decideChange(change, false)}>{tx.reject}</button>
                              </>
                            )}
                            {can.propose_change_orders && (
                              <button type="button" className="btn btn-ghost btn-sm"
                                onClick={() => act(() => projectApi.deleteChangeOrder(caseId, change.id), null, tx.confirmDeleteChange)}>{tx.delete}</button>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mp-actions">
                  {order.status !== 'cancelled' && can.propose_change_orders && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => addChange(order)}>{tx.addChangeOrder}</button>
                  )}
                  {order.status === 'active' && can.manage_orders && (
                    <>
                      <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                        onClick={() => act(() => projectApi.completeOrder(caseId, order.id), null, tx.confirmCompleteOrder)}>{tx.completeOrder}</button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => cancelOrder(order)}>{tx.cancelOrder}</button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

export function CostsTab({ ctx }) {
  const { project, caseId, tx, can, act, openForm } = ctx;
  const { costs } = project;
  const [picker, setPicker] = useState(null);
  const orders = project.orders.filter(order => order.status !== 'cancelled');
  const orderOptions = orders.map(order => ({ value: order.id, label: [order.order_number, order.supplier_name].filter(Boolean).join(' · ') }));
  const orderName = Object.fromEntries(project.orders.map(order => [order.id, [order.order_number, order.supplier_name].filter(Boolean).join(' · ')]));
  const loadInvoices = useCallback((params, options) => projectApi.invoiceCandidates(caseId, params, options), [caseId]);
  const invoiceId = picker?.kind === 'payment' ? picker.row.invoice.id : null;
  const loadBookings = useCallback((params, options) => projectApi.paymentCandidates(
    invoiceId, { q: params.q, skip: params.skip, limit: params.limit, all_properties: params.option || undefined }, options),
  [invoiceId]);

  const newInvoice = () => openForm({
    title: tx.addInvoice,
    initial: { order_id: orders.length === 1 ? orders[0].id : '', vat_rate: 19, invoice_date: new Date().toISOString().slice(0, 10) },
    fields: [
      { key: 'order_id', label: tx.order, type: 'select', required: true, options: orderOptions },
      { key: 'invoice_number', label: tx.invoiceNumber },
      { key: 'invoice_date', label: tx.invoiceDate, type: 'date', required: true },
      { key: 'due_date', label: tx.dueDate, type: 'date' },
      { key: 'net_amount', label: tx.net, type: 'number', required: true },
      { key: 'vat_rate', label: tx.vatRate, type: 'number' },
      { key: 'gross_amount', label: tx.gross, type: 'number', required: true },
      { key: 'payment_terms', label: tx.paymentTerms },
      { key: 'notes', label: tx.notes, type: 'textarea' },
    ],
    onSave: ({ order_id: orderId, ...invoice }) => projectApi.linkInvoice(caseId, orderId, {
      invoice: { ...invoice, vat_rate: invoice.vat_rate ?? 19 } }),
  });
  const pickedInvoice = invoice => {
    setPicker(null);
    openForm({
      title: `${tx.linkInvoice}: ${invoice.invoice_number || invoice.supplier}`,
      initial: { order_id: orders.length === 1 ? orders[0].id : '' },
      fields: [{ key: 'order_id', label: tx.order, type: 'select', required: true, options: orderOptions }],
      onSave: values => projectApi.linkInvoice(caseId, values.order_id, { invoice_id: invoice.id }),
    });
  };
  const pickedBooking = booking => {
    const row = picker.row;
    setPicker(null);
    const open = (cents(row.invoice.gross_amount) - row.payments.reduce((sum, p) => sum + cents(p.amount), 0)) / 100;
    openForm({
      title: `${tx.addPayment}: ${day(booking.booking_date)} · ${money(booking.amount)}`,
      initial: { amount: Math.max(0, Math.min(booking.free, open)) },
      fields: [{ key: 'amount', label: tx.amount, type: 'number', required: true }],
      onSave: values => projectApi.addPayment(row.invoice.id, { booking_id: booking.id, amount: values.amount }),
    });
  };

  return (
    <div className="mp-stack">
      <Section id="mp-costs" title={tx.costSummary}>
        <dl className="mp-facts">
          <Fact label={tx.budget}>{costs.budget == null ? '—' : money(costs.budget)}</Fact>
          <Fact label={tx.ordered}>{money(costs.ordered)}</Fact>
          <Fact label={tx.pendingChanges}>{money(costs.pending_change_orders)}</Fact>
          <Fact label={tx.invoiced}>{money(costs.invoiced)}</Fact>
          <Fact label={tx.paid}>{money(costs.paid)}</Fact>
          <Fact label={tx.openToInvoice}>{money(costs.open_to_invoice)}</Fact>
          <Fact label={tx.openToPay}>{money(costs.open_to_pay)}</Fact>
          <Fact label={tx.remainingBudget}>{costs.remaining_budget == null ? '—' : money(costs.remaining_budget)}</Fact>
        </dl>
        <p className="text-muted mp-rule">{tx.costRule}</p>
        {costs.orders.length > 0 && (
          <>
            <h3 className="mp-subhead">{tx.byOrder}</h3>
            <ul className="mp-list">
              {costs.orders.map(entry => (
                <li key={entry.order_id} className="mp-row">
                  <div className="mp-row-main">
                    <strong>{orderName[entry.order_id]}</strong>
                    <span className="text-muted">
                      {tx.ordered} {money(entry.ordered)} · {tx.invoiced} {money(entry.invoiced)} · {tx.paid} {money(entry.paid)}
                    </span>
                  </div>
                  <Pill tone={ORDER_TONE[entry.status]}>{tx[`order_${entry.status}`]}</Pill>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      <Section id="mp-invoices" title={tx.invoices} actions={orders.length > 0 && (
        <>
          {can.create_invoices && <button type="button" className="btn btn-primary btn-sm" onClick={newInvoice}>{tx.addInvoice}</button>}
          {can.link_invoices && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPicker({ kind: 'invoice' })}>{tx.linkInvoice}</button>}
        </>
      )}>
        {project.invoices.length === 0 ? <Empty>{tx.noInvoices}</Empty> : (
          <ul className="mp-cards">
            {project.invoices.map(row => (
              <li key={row.link_id} className="mp-card">
                <div className="mp-card-head">
                  <div className="mp-row-main">
                    <strong>{[row.invoice?.invoice_number, row.invoice?.supplier].filter(Boolean).join(' · ')}</strong>
                    <span className="text-muted">{day(row.invoice?.invoice_date)} · {tx.order} {orderName[row.order_id]}</span>
                  </div>
                  <Pill tone={row.invoice?.status === 'cancelled' ? 'gray' : 'blue'}>{tx[`invoice_${row.invoice?.status}`] || row.invoice?.status}</Pill>
                </div>
                <p className="mp-amounts">
                  <strong>{tx.gross} {money(row.invoice?.gross_amount)}</strong>
                  <span>{tx.paid} {money(row.paid)}</span>
                </p>
                <h3 className="mp-subhead">{tx.payments}</h3>
                {row.payments.length === 0 ? <Empty>{tx.noPayments}</Empty> : (
                  <ul className="mp-list">
                    {row.payments.map(payment => (
                      <li key={payment.id} className="mp-row">
                        <div className="mp-row-main">
                          <strong>{money(payment.amount)}</strong>
                          <span className="text-muted">
                            {[day(payment.booking?.booking_date), payment.booking?.payment_text].filter(Boolean).join(' · ')}
                          </span>
                        </div>
                        {can.allocate_payments && (
                          <button type="button" className="btn btn-ghost btn-sm"
                            onClick={() => act(() => projectApi.deletePayment(row.invoice.id, payment.id), null, tx.confirmRemovePayment)}>{tx.remove}</button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mp-actions">
                  {can.allocate_payments && row.invoice && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPicker({ kind: 'payment', row })}>{tx.addPayment}</button>
                  )}
                  {can.link_invoices && (
                    <button type="button" className="btn btn-ghost btn-sm"
                      onClick={() => act(() => projectApi.unlinkInvoice(caseId, row.link_id), null, tx.confirmUnlinkInvoice)}>{tx.unlink}</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {picker?.kind === 'invoice' && (
        <PickerDialog title={tx.linkInvoice} load={loadInvoices} onClose={() => setPicker(null)} onPick={pickedInvoice}
          renderItem={invoice => (
            <>
              <strong>{[invoice.invoice_number, invoice.supplier].filter(Boolean).join(' · ')}</strong>
              <span className="text-muted">{day(invoice.invoice_date)} · {money(invoice.gross_amount)}</span>
            </>
          )} />
      )}
      {picker?.kind === 'payment' && (
        <PickerDialog title={tx.addPayment} load={loadBookings} onClose={() => setPicker(null)} onPick={pickedBooking}
          extra={tx.allProperties}
          renderItem={booking => (
            <>
              <strong>{day(booking.booking_date)} · {money(booking.amount)}</strong>
              <span className="text-muted">{[booking.payment_text, `${tx.free} ${money(booking.free)}`].filter(Boolean).join(' · ')}</span>
            </>
          )} />
      )}
    </div>
  );
}

