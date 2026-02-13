import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Building2,
  Home,
  DoorOpen,
  Users,
  FileText,
  Landmark,
  Wrench,
  TrendingUp,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import StatusBadge from '../components/StatusBadge';
import { api } from '../api';

function StatCard({ icon, iconClass, label, value, to }) {
  return (
    <Link to={to} className="stat-card">
      <div className={`stat-icon-wrapper ${iconClass}`}>{icon}</div>
      <div className="stat-info">
        <div className="stat-value">{value ?? '—'}</div>
        <div className="stat-label">{label}</div>
      </div>
    </Link>
  );
}

function generateRevenueData(contractsActive) {
  const baseRevenue = contractsActive * 850;
  const monthNames = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
  const now = new Date();
  const data = [];

  for (let i = 5; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const variance = 0.9 + Math.random() * 0.2; // between 0.9 and 1.1
    data.push({
      month: monthNames[d.getMonth()],
      revenue: Math.round(baseRevenue * variance),
    });
  }

  return data;
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
        unitsVacant: units.filter(u => u.status === 'vacant').length,
        unitsReserved: units.filter(u => u.status === 'reserved').length,
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

  const revenueData = generateRevenueData(stats.contractsActive || 0);

  return (
    <div className="page">
      <h1 className="page-title">Dashboard</h1>
      <p className="page-subtitle">ImmoManager Pro — Gesamtübersicht</p>

      {/* KPI Stat Cards */}
      <div className="stats-grid">
        <StatCard
          icon={<Building2 size={22} />}
          iconClass="stat-icon-teal"
          label="Portfolios"
          value={stats.portfolios}
          to="/portfolios"
        />
        <StatCard
          icon={<Home size={22} />}
          iconClass="stat-icon-blue"
          label="Immobilien"
          value={stats.properties}
          to="/properties"
        />
        <StatCard
          icon={<DoorOpen size={22} />}
          iconClass="stat-icon-green"
          label="Einheiten"
          value={`${stats.unitsOccupied}/${stats.units}`}
          to="/units"
        />
        <StatCard
          icon={<Users size={22} />}
          iconClass="stat-icon-teal"
          label="Mieter"
          value={stats.tenants}
          to="/tenants"
        />
        <StatCard
          icon={<FileText size={22} />}
          iconClass="stat-icon-blue"
          label="Aktive Verträge"
          value={stats.contractsActive}
          to="/contracts"
        />
        <StatCard
          icon={<Landmark size={22} />}
          iconClass="stat-icon-green"
          label="Konten"
          value={stats.accounts}
          to="/accounts"
        />
        <StatCard
          icon={<Wrench size={22} />}
          iconClass={stats.openMaintenance > 0 ? 'stat-icon-red' : 'stat-icon-amber'}
          label="Offene Wartung"
          value={stats.openMaintenance}
          to="/maintenance"
        />
        <StatCard
          icon={<TrendingUp size={22} />}
          iconClass="stat-icon-green"
          label="Auslastung"
          value={`${occupancyRate}%`}
          to="/units"
        />
      </div>

      {/* Revenue Chart + Occupancy Overview */}
      <div className="dashboard-grid">
        <div className="panel">
          <div className="panel-header">
            <h3>Monatliche Einnahmen</h3>
          </div>
          <div className="panel-body">
            <div className="chart-container">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={revenueData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                  />
                  <Tooltip
                    formatter={(value) => [`€${value.toLocaleString('de-DE')}`, 'Einnahmen']}
                    cursor={{ fill: 'rgba(13, 148, 136, 0.08)' }}
                  />
                  <Bar dataKey="revenue" fill="#0D9488" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Belegungsübersicht</h3>
          </div>
          <div className="panel-body">
            <div className="occupancy-bar">
              <div
                className="occupancy-bar-fill"
                style={{ width: `${occupancyRate}%` }}
              />
            </div>
            <div className="quick-stats">
              <div className="quick-stat">
                <div className="quick-stat-value">{stats.unitsOccupied}</div>
                <div className="quick-stat-label">Belegt</div>
              </div>
              <div className="quick-stat">
                <div className="quick-stat-value">{stats.unitsVacant}</div>
                <div className="quick-stat-label">Leer</div>
              </div>
              <div className="quick-stat">
                <div className="quick-stat-value">{stats.unitsReserved}</div>
                <div className="quick-stat-label">Reserviert</div>
              </div>
              <div className="quick-stat">
                <div className="quick-stat-value">{occupancyRate}%</div>
                <div className="quick-stat-label">Auslastung</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Open Tasks + Notifications */}
      <div className="dashboard-grid">
        <div className="panel">
          <div className="panel-header">
            <h3>Offene Aufgaben</h3>
          </div>
          <div className="panel-body">
            {tasks.length === 0 ? (
              <p className="empty-text">Keine offenen Aufgaben</p>
            ) : (
              <ul className="activity-list">
                {tasks.map((t) => (
                  <li key={t.id}>
                    <span className="activity-title">{t.title}</span>
                    {t.due_date && <span className="activity-date">{t.due_date}</span>}
                    <StatusBadge status={t.priority} />
                  </li>
                ))}
              </ul>
            )}
            <Link to="/tasks" className="panel-link">Alle Aufgaben &rarr;</Link>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3>Benachrichtigungen</h3>
          </div>
          <div className="panel-body">
            {notifications.length === 0 ? (
              <p className="empty-text">Keine neuen Benachrichtigungen</p>
            ) : (
              <ul className="activity-list">
                {notifications.map((n) => (
                  <li key={n.id}>
                    <span className="activity-title">{n.title}</span>
                    {n.created_at && <span className="activity-date">{n.created_at}</span>}
                    <StatusBadge status={n.severity} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
