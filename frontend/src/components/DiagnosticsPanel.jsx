import { useState, useCallback } from 'react';
import { api } from '../api';

const SEVERITY_COLORS = {
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#06b6d4',
};

const SEVERITY_ICONS = {
  error: '✗',
  warning: '⚠',
  info: 'ℹ',
};

export default function DiagnosticsPanel({ onClose }) {
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  const runTests = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const data = await api.get('/diagnostics/run');
      setReport(data);
    } catch (err) {
      setError(err.message || 'Diagnostics failed');
    } finally {
      setRunning(false);
    }
  }, []);

  const handleDownload = useCallback(() => {
    if (!report) return;
    const lines = [
      `# ImmoManager Pro — Diagnostics Report`,
      `# ${report.timestamp}`,
      `# Tests: ${report.total_tests} | Passed: ${report.passed} | Failed: ${report.failed}`,
      `# Duration: ${report.duration_ms}ms`,
      '',
    ];
    for (const r of report.results) {
      lines.push(`## [${r.passed ? 'PASS' : 'FAIL'}] ${r.test} (${r.checked} checked, ${r.duration_ms}ms)`);
      for (const issue of r.issues) {
        lines.push(`   [${issue.severity.toUpperCase()}] ${issue.entity_type}: ${issue.message}`);
        if (issue.entity_id) lines.push(`          ID: ${issue.entity_id}`);
        if (issue.details) lines.push(`          ${JSON.stringify(issue.details)}`);
      }
      lines.push('');
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `diagnostics_${new Date().toISOString().slice(0, 10)}.log`;
    a.click();
    URL.revokeObjectURL(url);
  }, [report]);

  return (
    <div className="dev-panel dev-panel-diagnostics">
      <div className="dev-panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Data Consistency Diagnostics</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="dev-btn dev-btn-sm dev-btn-accent" onClick={runTests} disabled={running}>
            {running ? 'Running...' : 'Run Tests'}
          </button>
          {report && (
            <button className="dev-btn dev-btn-sm dev-btn-ghost" onClick={handleDownload}>Download</button>
          )}
          <button className="dev-btn dev-btn-sm dev-btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>

      {error && <div className="diag-error">{error}</div>}

      {report && (
        <>
          {/* Summary bar */}
          <div className="diag-summary">
            <span className="diag-stat diag-stat-total">{report.total_tests} tests</span>
            <span className="diag-stat diag-stat-pass">{report.passed} passed</span>
            {report.failed > 0 && <span className="diag-stat diag-stat-fail">{report.failed} failed</span>}
            {report.warnings > 0 && <span className="diag-stat diag-stat-warn">{report.warnings} warnings</span>}
            <span className="diag-stat">{report.total_issues} issues</span>
            <span className="diag-stat">{report.duration_ms}ms</span>
          </div>

          {/* Test results */}
          <div className="diag-results">
            {report.results.map((result, i) => (
              <DiagnosticTestResult key={i} result={result} />
            ))}
          </div>
        </>
      )}

      {!report && !running && (
        <div className="diag-empty">
          Click "Run Tests" to validate data consistency across all entities.
          Tests check FK references, orphaned records, duplicate keys, and data integrity.
        </div>
      )}
    </div>
  );
}

function DiagnosticTestResult({ result }) {
  const [expanded, setExpanded] = useState(!result.passed);
  const errorCount = result.issues.filter(i => i.severity === 'error').length;
  const warnCount = result.issues.filter(i => i.severity === 'warning').length;
  const infoCount = result.issues.filter(i => i.severity === 'info').length;

  return (
    <div className={`diag-test ${result.passed ? 'diag-test-pass' : 'diag-test-fail'}`}>
      <div className="diag-test-header" onClick={() => setExpanded(!expanded)}>
        <span className={`diag-test-status ${result.passed ? 'pass' : 'fail'}`}>
          {result.passed ? '✓' : '✗'}
        </span>
        <span className="diag-test-name">{result.test}</span>
        <span className="diag-test-meta">
          {result.checked} checked · {result.duration_ms}ms
          {errorCount > 0 && <span className="diag-badge-error">{errorCount} errors</span>}
          {warnCount > 0 && <span className="diag-badge-warn">{warnCount} warnings</span>}
          {infoCount > 0 && <span className="diag-badge-info">{infoCount} info</span>}
        </span>
        <span className="diag-expand">{expanded ? '▼' : '▶'}</span>
      </div>
      {expanded && result.issues.length > 0 && (
        <div className="diag-issues">
          {result.issues.map((issue, j) => (
            <div key={j} className="diag-issue" style={{ borderLeftColor: SEVERITY_COLORS[issue.severity] }}>
              <span className="diag-issue-icon" style={{ color: SEVERITY_COLORS[issue.severity] }}>
                {SEVERITY_ICONS[issue.severity]}
              </span>
              <div className="diag-issue-content">
                <span className="diag-issue-type">{issue.entity_type}</span>
                {issue.entity_id && <span className="diag-issue-id">{issue.entity_id.substring(0, 8)}...</span>}
                <span className="diag-issue-msg">{issue.message}</span>
                {issue.details && (
                  <pre className="diag-issue-details">{JSON.stringify(issue.details, null, 2)}</pre>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
