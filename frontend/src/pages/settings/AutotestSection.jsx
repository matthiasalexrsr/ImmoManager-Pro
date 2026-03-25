import { useState } from 'react';
import { api } from '../../api';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function AutotestSection() {
  const [autotestRunning, setAutotestRunning] = useState(false);
  const [autotestResult, setAutotestResult] = useState(null);
  const [autotestUploading, setAutotestUploading] = useState(false);
  const [autotestUploadResult, setAutotestUploadResult] = useState(null);

  const handleRunAutotest = async () => {
    setAutotestRunning(true);
    setAutotestResult(null);
    setAutotestUploadResult(null);
    try {
      const data = await api.post('/autotest/run');
      setAutotestResult(data);
    } catch (err) {
      setAutotestResult({ error: err.message || 'Autotest failed' });
    } finally {
      setAutotestRunning(false);
    }
  };

  const handleDownloadReport = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/autotest/report/markdown`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Status ${res.status}`);
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'AUTOTEST_REPORT.md';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('[Autotest] Download failed:', err);
    }
  };

  const handleUploadReport = async () => {
    setAutotestUploading(true);
    setAutotestUploadResult(null);
    try {
      const data = await api.post('/autotest/upload-report');
      setAutotestUploadResult(data);
    } catch (err) {
      setAutotestUploadResult({ error: err.message || 'Upload failed' });
    } finally {
      setAutotestUploading(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">Autotest — Self-Diagnostic Suite</div>
      <div className="panel-body settings-section">
        <div className="settings-row">
          <label>Run the full automated test suite against the application</label>
          <div className="settings-control">
            <button
              className="btn btn-sm btn-primary"
              onClick={handleRunAutotest}
              disabled={autotestRunning}
            >
              {autotestRunning ? 'Running Tests...' : 'Run Autotest'}
            </button>
          </div>
        </div>

        {autotestResult && !autotestResult.error && (
          <>
            <div className="settings-row">
              <label>Result</label>
              <div className="settings-control">
                <span style={{
                  color: autotestResult.summary?.failed > 0 ? 'var(--color-danger, #dc3545)' : 'var(--color-success, #28a745)',
                  fontWeight: 600,
                }}>
                  {autotestResult.summary?.passed}/{autotestResult.summary?.total} passed
                  {autotestResult.summary?.failed > 0 && ` — ${autotestResult.summary.failed} FAILED`}
                  {autotestResult.summary?.warnings > 0 && ` — ${autotestResult.summary.warnings} warnings`}
                </span>
              </div>
            </div>

            <div className="settings-row">
              <label>Duration</label>
              <div className="settings-control">
                <span className="text-muted">{Math.round(autotestResult.duration_ms || 0)}ms</span>
              </div>
            </div>

            {autotestResult.modules?.map((mod) => (
              <div key={mod.name} className="settings-row" style={{ borderLeft: mod.failed > 0 ? '3px solid var(--color-danger, #dc3545)' : '3px solid var(--color-success, #28a745)', paddingLeft: '8px' }}>
                <label style={{ fontFamily: 'monospace', fontSize: '0.85em' }}>{mod.name}</label>
                <div className="settings-control">
                  <span className="text-muted" style={{ fontSize: '0.85em' }}>
                    {mod.passed} passed, {mod.failed} failed
                    {mod.warnings > 0 && `, ${mod.warnings} warnings`}
                    {' '}({Math.round(mod.duration_ms)}ms)
                  </span>
                </div>
              </div>
            ))}

            <div className="settings-row">
              <label>Download Report</label>
              <div className="settings-control" style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-sm btn-secondary" onClick={handleDownloadReport}>
                  Download Markdown
                </button>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={handleUploadReport}
                  disabled={autotestUploading}
                >
                  {autotestUploading ? 'Uploading...' : 'Upload to GitHub'}
                </button>
              </div>
            </div>

            {autotestUploadResult && (
              <div className="settings-row">
                <label>Upload Status</label>
                <div className="settings-control">
                  {autotestUploadResult.error ? (
                    <span style={{ color: 'var(--color-danger, #dc3545)' }}>{autotestUploadResult.error}</span>
                  ) : (
                    <span style={{ color: 'var(--color-success, #28a745)' }}>
                      {autotestUploadResult.message}
                      {autotestUploadResult.html_url && (
                        <> — <a href={autotestUploadResult.html_url} target="_blank" rel="noopener noreferrer">View on GitHub</a></>
                      )}
                    </span>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {autotestResult?.error && (
          <div className="settings-row">
            <label>Error</label>
            <div className="settings-control">
              <span style={{ color: 'var(--color-danger, #dc3545)' }}>{autotestResult.error}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
