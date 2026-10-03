import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid } from 'recharts';
import SourceState from './DashboardSourceState';
const colors = ['var(--chart-1, #28776f)', 'var(--chart-2, #365f87)', 'var(--chart-3, #8b611d)', 'var(--chart-4, #96758e)', 'var(--chart-5, #708478)', 'var(--chart-6, #b34746)'];
export function Metric({ icon, label, value, hint, to, action, pending }) {
  const Icon = icon;
  return <article className="dashboard-home-metric" aria-label={label} aria-busy={pending}><div className="dashboard-home-metric-label"><span>{label}</span><Icon size={19} aria-hidden="true" /></div><strong>{value ?? '—'}</strong><p>{hint}</p><Link to={to}>{action}<ArrowUpRight size={15} aria-hidden="true" /></Link></article>;
}

export function ValuesTable({ title, rows, headers, t }) {
  return <details className="dashboard-home-values"><summary>{t('dashboardHome.chartValues')}</summary><div className="dashboard-home-table-scroll" tabIndex={0} role="region" aria-label={`${title}: ${t('dashboardHome.chartValues')}`}><table><caption>{title}</caption><thead><tr>{headers.map(header => <th key={header} scope="col">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((value, cell) => cell === 0 ? <th key={cell} scope="row">{value}</th> : <td key={cell}>{value}</td>)}</tr>)}</tbody></table></div></details>;
}

function ReportChart({ kind, rows, format, series }) {
  if (kind === 'line') return <ResponsiveContainer width="100%" height={240}><LineChart data={rows}><CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip formatter={format} /><Legend />{series.map((name, index) => <Line key={name} dataKey={`values.${index}`} name={name} stroke={colors[index]} strokeWidth={index ? 1 : 2} dot={false} isAnimationActive={false} strokeDasharray={index ? '4 2' : undefined} />)}</LineChart></ResponsiveContainer>;
  const data = rows.map(row => ({ name: row.name, value: row.values[0] }));
  if (kind === 'pie') return <ResponsiveContainer width="100%" height={240}><PieChart><Pie data={data.filter(row => row.value > 0)} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} isAnimationActive={false}>{data.filter(row => row.value > 0).map((_, index) => <Cell key={index} fill={colors[index % colors.length]} />)}</Pie><Tooltip formatter={format} /><Legend /></PieChart></ResponsiveContainer>;
  const horizontal = kind === 'horizontal';
  return <ResponsiveContainer width="100%" height={240}><BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'}><CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" /><XAxis type={horizontal ? 'number' : 'category'} dataKey={horizontal ? undefined : 'name'} tick={{ fontSize: 11 }} /><YAxis type={horizontal ? 'category' : 'number'} dataKey={horizontal ? 'name' : undefined} width={horizontal ? 100 : 60} tick={{ fontSize: 11 }} /><Tooltip formatter={format} /><Bar dataKey="value" isAnimationActive={false} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}>{data.map((row, index) => <Cell key={index} fill={row.value < 0 ? colors[5] : colors[index % colors.length]} />)}</Bar></BarChart></ResponsiveContainer>;
}

export function Report({ title, hint, source, onRetry, rows, chartRows = rows, headers, kind, format, t, locale }) {
  return <section className="dashboard-home-panel dashboard-home-report" aria-label={title}><header><h2>{title}</h2><p>{hint}</p></header><SourceState source={source} name={title} onRetry={onRetry} t={t} locale={locale} />{source.data && (rows.length ? <><div className="dashboard-home-chart" aria-hidden="true">{chartRows.length ? <ReportChart rows={chartRows} kind={kind} format={format} series={headers.slice(1)} /> : <p className="dashboard-home-empty">{t('dashboardHome.noCategoryBalances')}</p>}</div><ValuesTable title={title} rows={rows.map(row => [row.name, ...row.values.map(format)])} headers={headers} t={t} /></> : source.status === 'ready' && <p className="dashboard-home-empty">{t('dashboardHome.noReportRows')}</p>)}</section>;
}

