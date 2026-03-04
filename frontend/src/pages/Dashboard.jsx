import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import {
  PortfolioIcon, PropertyIcon, UnitIcon, TenantIcon,
  ContractIcon, AccountIcon, MaintenanceIcon, ChartIcon,
  ArrowRightIcon,
} from '../components/Icons';

function StatCard({ icon, label, value, to, color }) {
  const Ico = icon;
  return (
    <Link to={to} className={`stat-card ${color || ''}`}>
      <div className="stat-icon">
        <Ico size={22} />
      </div>
      <div className="stat-info">
        <div className="stat-value">{value ?? '\u2014'}</div>
        <div className="stat-label">{label}</div>
      </div>
    </Link>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState({});
  const [tasks, setTasks] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get('/portfolios').catch(() => []),
      api.get('/properties').catch(() => []),
      api.get('/units').catch(() => []),
      api.get('/tenants').catch(() => []),
      api.get('/contracts').catch(() => []),
      api.get('/accounts').catch(() => []),
      api.get('/tasks?status=open&limit=5').catch(() => []),
      api.get('/maintenance?status=open&limit=5').catch(() => []),
      api.get('/notifications?status=unread&limit=5').catch(() => []),
    ]).then(([portfolios, properties, units, tenants, contracts, accounts, openTasks, maintenance, notifs]) => {
      setStats({
        portfolios: portfolios.length,
        properties: properties.length,
        units: units.length,
        unitsOccupied: units.filter(u => u.status === 'occupied').length,
        tenants: tenants.length,
        contracts: contracts.length,
        contractsActive: contracts.filter(c => c.status === 'active').length,
        accounts: accounts.length,
        openMaintenance: maintenance.length,
      });
      setTasks(openTasks);
      setNotifications(notifs);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Laden...</div>;

  const occupancyRate = stats.units > 0
    ? Math.round((stats.unitsOccupied / stats.units) * 100)
    : 0;

  return (
    <div className="page">
      <h1 className="page-title">Dashboard</h1>

      <div className="stats-grid">
        <StatCard icon={PortfolioIcon} label="Portfolios" value={stats.portfolios} to="/portfolios" />
        <StatCard icon={PropertyIcon} label="Immobilien" value={stats.properties} to="/properties" />
        <StatCard icon={UnitIcon} label="Einheiten" value={`${stats.unitsOccupied}/${stats.units}`} to="/units" color="stat-highlight" />
        <StatCard icon={TenantIcon} label="Mieter" value={stats.tenants} to="/tenants" />
        <StatCard icon={ContractIcon} label="Aktive Verträge" value={stats.contractsActive} to="/contracts" />
        <StatCard icon={AccountIcon} label="Konten" value={stats.accounts} to="/accounts" />
        <StatCard icon={MaintenanceIcon} label="Offene Wartung" value={stats.openMaintenance} to="/maintenance" color={stats.openMaintenance > 0 ? 'stat-warning' : ''} />
        <StatCard icon={ChartIcon} label="Auslastung" value={`${occupancyRate}%`} to="/units" color="stat-highlight" />
      </div>

      <div className="dashboard-panels">
        <div className="panel">
          <h3>Offene Aufgaben</h3>
          {tasks.length === 0 ? <p className="empty-text">Keine offenen Aufgaben</p> : (
            <ul className="activity-list">
              {tasks.map(t => (
                <li key={t.id}>
                  <span className="activity-title">{t.title}</span>
                  {t.due_date && <span className="activity-date">{t.due_date}</span>}
                  <StatusBadge status={t.priority} />
                </li>
              ))}
            </ul>
          )}
          <Link to="/tasks" className="panel-link">
            Alle Aufgaben <ArrowRightIcon size={14} />
          </Link>
        </div>

        <div className="panel">
          <h3>Benachrichtigungen</h3>
          {notifications.length === 0 ? <p className="empty-text">Keine neuen Benachrichtigungen</p> : (
            <ul className="activity-list">
              {notifications.map(n => (
                <li key={n.id}>
                  <span className="activity-title">{n.title}</span>
                  <StatusBadge status={n.severity} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
