import { Link } from 'react-router-dom';
import { projectApi } from './projectApi';
import { choices, day, money } from './projectFormat';
import { Empty, Fact, Pill, Section } from './ProjectUi';
import { fill } from './text';

const WP_TONE = { planned: 'gray', in_progress: 'blue', done: 'green', cancelled: 'gray' };

export function OverviewTab({ ctx }) {
  const { project, caseId, tx, can, act, openForm, contactOptions } = ctx;
  const record = project.case;
  const statusLabel = value => (value ? tx[`status_${value}`] || value : '—');

  const editCase = () => openForm({
    title: tx.editCase,
    initial: record,
    fields: [
      { key: 'title', label: tx.title, required: true },
      { key: 'category', label: tx.category },
      { key: 'priority', label: tx.priority, type: 'select', options: choices(tx, 'priority_', ['low', 'medium', 'high', 'urgent']) },
      { key: 'reported_by', label: tx.reportedBy },
      { key: 'assignee', label: tx.assignee },
      { key: 'due_date', label: tx.dueDate, type: 'date' },
      { key: 'estimated_cost', label: tx.budget, type: 'number' },
      { key: 'description', label: tx.description, type: 'textarea' },
    ],
    onSave: values => projectApi.updateCase(caseId, values),
  });
  const addParticipant = () => openForm({
    title: tx.addCraftsman,
    fields: [
      { key: 'contact_id', label: tx.contact, type: 'select', required: true, options: contactOptions },
      { key: 'role', label: tx.role, type: 'select', default: 'contractor', required: true,
        options: choices(tx, 'role_', ['contractor', 'expert', 'other']) },
      { key: 'trade', label: tx.trade },
      { key: 'notes', label: tx.notes, type: 'textarea' },
    ],
    onSave: values => projectApi.addParticipant(caseId, values),
  });

  return (
    <div className="mp-grid">
      <Section id="mp-facts" title={tx.facts}
        actions={can.edit_case && <button type="button" className="btn btn-secondary btn-sm" onClick={editCase}>{tx.edit}</button>}>
        <dl className="mp-facts">
          <Fact label={tx.property}>{record.property_name}</Fact>
          <Fact label={tx.unit}>{record.unit_label}</Fact>
          <Fact label={tx.category}>{record.category}</Fact>
          <Fact label={tx.priority}>{tx[`priority_${record.priority}`] || record.priority}</Fact>
          <Fact label={tx.reportedBy}>{record.reported_by}</Fact>
          <Fact label={tx.assignee}>{record.assignee}</Fact>
          <Fact label={tx.dueDate}>{day(record.due_date)}</Fact>
          <Fact label={tx.budget}>{record.estimated_cost == null ? '—' : money(record.estimated_cost)}</Fact>
          {record.contractor && <Fact label={tx.legacyContractor}>{record.contractor}</Fact>}
          {record.appointment_at && <Fact label={tx.legacyAppointment}>{day(record.appointment_at)}</Fact>}
        </dl>
        {record.description && <p className="mp-description">{record.description}</p>}
      </Section>

      <Section id="mp-craftsmen" title={tx.craftsmen}
        actions={can.participants && <button type="button" className="btn btn-secondary btn-sm" onClick={addParticipant}>{tx.addCraftsman}</button>}>
        {project.participants.length === 0 ? <Empty>{tx.noCraftsmen}</Empty> : (
          <ul className="mp-list">
            {project.participants.map(participant => (
              <li key={participant.id} className="mp-row">
                <div className="mp-row-main">
                  <strong>{participant.contact?.name || tx.contactMissing}</strong>
                  <span className="text-muted">
                    {[tx[`role_${participant.role}`], participant.trade, participant.contact?.phone, participant.contact?.email]
                      .filter(Boolean).join(' · ')}
                  </span>
                </div>
                {can.participants && (
                  <button type="button" className="btn btn-ghost btn-sm"
                    onClick={() => act(() => projectApi.deleteParticipant(caseId, participant.id))}>{tx.remove}</button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="mp-history" title={tx.history}>
        {project.history.length === 0 ? <Empty>{tx.noHistory}</Empty> : (
          <ol className="mp-timeline">
            {project.history.map(entry => (
              <li key={entry.id}>
                <span className="mp-time">{day(entry.changed_at)}</span>
                <span>
                  {entry.old_value ? `${statusLabel(entry.old_value)} → ` : `${tx.created}: `}<strong>{statusLabel(entry.new_value)}</strong>
                  {entry.changed_by_name && <span className="text-muted"> {tx.changedBy} {entry.changed_by_name}</span>}
                  {entry.reason && <span className="mp-reason"> – {entry.reason}</span>}
                </span>
              </li>
            ))}
          </ol>
        )}
      </Section>
    </div>
  );
}

function packageFields(tx, contactOptions) {
  return [
    { key: 'title', label: tx.title, required: true },
    { key: 'kind', label: tx.kind, type: 'select', default: 'work', required: true, options: choices(tx, 'kind_', ['work', 'milestone']) },
    { key: 'phase', label: tx.phase },
    { key: 'planned_start', label: tx.plannedStart, type: 'date' },
    { key: 'planned_end', label: tx.plannedEnd, type: 'date' },
    { key: 'contact_id', label: tx.contact, type: 'select', options: contactOptions },
    { key: 'sort_order', label: tx.sortOrder, type: 'number', default: 0 },
    { key: 'description', label: tx.description, type: 'textarea' },
  ];
}

const NEXT = {
  planned: [['in_progress', 'start'], ['done', 'finish'], ['cancelled', 'drop']],
  in_progress: [['done', 'finish'], ['cancelled', 'drop']],
  done: [['in_progress', 'reopen']],
  cancelled: [['planned', 'replan']],
};

export function WorkTab({ ctx }) {
  const { project, caseId, tx, can, act, openForm, contactOptions, busy } = ctx;
  const packages = project.work_packages;
  const titles = Object.fromEntries(packages.map(wp => [wp.id, wp.title]));
  const dependencyOf = (before, after) => project.dependencies.find(d => d.predecessor_id === before && d.successor_id === after);
  const packageOptions = packages.map(wp => ({ value: wp.id, label: wp.title }));

  const addPackage = () => openForm({
    title: tx.addPackage, fields: packageFields(tx, contactOptions),
    onSave: values => projectApi.addPackage(caseId, { ...values, kind: values.kind || 'work', sort_order: values.sort_order ?? 0 }),
  });
  const editPackage = wp => openForm({
    title: tx.editPackage, initial: wp, fields: packageFields(tx, contactOptions).filter(f => f.key !== 'kind'),
    onSave: values => projectApi.updatePackage(caseId, wp.id, { ...values, sort_order: values.sort_order ?? 0 }),
  });
  const addDependency = () => openForm({
    title: tx.addDependency,
    fields: [
      { key: 'predecessor_id', label: tx.predecessor, type: 'select', required: true, options: packageOptions, hint: tx.dependencyHint },
      { key: 'successor_id', label: tx.successor, type: 'select', required: true, options: packageOptions },
    ],
    onSave: values => projectApi.addDependency(caseId, values),
  });

  return (
    <Section id="mp-work" title={tx.tabWork} actions={can.plan && (
      <>
        <button type="button" className="btn btn-primary btn-sm" onClick={addPackage}>{tx.addPackage}</button>
        {packages.length > 1 && <button type="button" className="btn btn-secondary btn-sm" onClick={addDependency}>{tx.addDependency}</button>}
      </>
    )}>
      {project.schedule_conflicts.length > 0 && (
        <div className="alert alert-warning mp-conflicts" role="note">
          <strong>{tx.scheduleConflicts}</strong>
          <ul>{project.schedule_conflicts.map(c => <li key={`${c.predecessor_id}:${c.successor_id}`}>{c.message}</li>)}</ul>
        </div>
      )}
      {packages.length === 0 ? <Empty>{tx.noPackages}</Empty> : (
        <ol className="mp-cards">
          {packages.map(wp => (
            <li key={wp.id} className="mp-card">
              <div className="mp-card-head">
                <div className="mp-row-main">
                  <strong>{wp.title}</strong>
                  <span className="text-muted">
                    {[tx[`kind_${wp.kind}`], wp.phase, wp.contact?.name].filter(Boolean).join(' · ')}
                  </span>
                </div>
                <Pill tone={WP_TONE[wp.status]}>{tx[`wp_${wp.status}`]}</Pill>
              </div>
              {(wp.planned_start || wp.planned_end) && (
                <p className="mp-meta">{day(wp.planned_start)} – {day(wp.planned_end)}</p>
              )}
              {wp.predecessors.length > 0 && (
                <p className="mp-meta">
                  {tx.after}:{' '}
                  {wp.predecessors.map(id => {
                    const dependency = dependencyOf(id, wp.id);
                    return (
                      <span key={id} className="mp-chip">
                        {titles[id]}
                        {can.plan && dependency && (
                          <button type="button" className="mp-chip-remove" aria-label={`${tx.removeDependency}: ${titles[id]}`}
                            onClick={() => act(() => projectApi.deleteDependency(caseId, dependency.id))}>×</button>
                        )}
                      </span>
                    );
                  })}
                </p>
              )}
              {wp.blocked_by.length > 0 && wp.status === 'planned' && (
                <p className="mp-meta mp-waiting">{tx.waitsFor}: {wp.blocked_by.map(id => titles[id]).join(', ')}</p>
              )}
              {can.plan && (
                <div className="mp-actions">
                  {(NEXT[wp.status] || []).filter(([status]) => !(wp.kind === 'milestone' && status === 'in_progress')).map(([status, label]) => (
                    <button key={status} type="button" className="btn btn-secondary btn-sm" disabled={busy}
                      onClick={() => act(() => projectApi.updatePackage(caseId, wp.id, { status }))}>{tx[label]}</button>
                  ))}
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => editPackage(wp)}>{tx.edit}</button>
                  <button type="button" className="btn btn-ghost btn-sm"
                    onClick={() => act(() => projectApi.deletePackage(caseId, wp.id), null, fill(tx.confirmDeletePackage, { title: wp.title }))}>
                    {tx.delete}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

export function AppointmentsTab({ ctx }) {
  const { project, caseId, tx, can, act, openForm, contactOptions } = ctx;
  const packageOptions = project.work_packages.map(wp => ({ value: wp.id, label: wp.title }));
  const fields = [
    { key: 'title', label: tx.title, required: true },
    { key: 'event_date', label: tx.date, type: 'date', required: true },
    { key: 'event_time', label: tx.time, type: 'time' },
    { key: 'kind', label: tx.kind, type: 'select', default: 'other', required: true,
      options: choices(tx, 'appt_', ['inspection', 'execution', 'acceptance', 'other']) },
    { key: 'location', label: tx.location },
    { key: 'work_package_id', label: tx.workPackage, type: 'select', options: packageOptions },
    { key: 'contact_id', label: tx.contact, type: 'select', options: contactOptions },
    { key: 'description', label: tx.description, type: 'textarea' },
  ];
  const add = () => openForm({ title: tx.addAppointment, fields, onSave: values => projectApi.addAppointment(caseId, values) });
  const edit = appointment => openForm({
    title: tx.editAppointment, fields,
    initial: { ...appointment.event, kind: appointment.kind, work_package_id: appointment.work_package_id,
               contact_id: appointment.contact_id },
    onSave: values => projectApi.updateAppointment(caseId, appointment.id, values),
  });
  return (
    <Section id="mp-appointments" title={tx.tabAppointments} actions={(
      <>
        {can.appointments && <button type="button" className="btn btn-primary btn-sm" onClick={add}>{tx.addAppointment}</button>}
        <Link className="btn btn-secondary btn-sm" to="/calendar">{tx.inCalendar}</Link>
      </>
    )}>
      {project.appointments.length === 0 ? <Empty>{tx.noAppointments}</Empty> : (
        <ul className="mp-list">
          {project.appointments.map(appointment => (
            <li key={appointment.id} className="mp-row">
              <div className="mp-row-main">
                <strong>{day(appointment.event?.event_date)}{appointment.event?.event_time ? `, ${appointment.event.event_time}` : ''} · {appointment.event?.title}</strong>
                <span className="text-muted">
                  {[tx[`appt_${appointment.kind}`], appointment.event?.location, appointment.contact?.name,
                    appointment.work_package_title].filter(Boolean).join(' · ')}
                </span>
              </div>
              {can.appointments && (
                <div className="mp-actions">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => edit(appointment)}>{tx.edit}</button>
                  <button type="button" className="btn btn-ghost btn-sm"
                    onClick={() => act(() => projectApi.deleteAppointment(caseId, appointment.id), null, tx.confirmDeleteAppointment)}>
                    {tx.delete}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
