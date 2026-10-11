import React, { useState, useEffect } from 'react';
import { 
  Play, 
  RefreshCw, 
  CheckCircle, 
  Clock, 
  AlertTriangle, 
  Terminal,
  Activity,
  Layers
} from 'lucide-react';

interface RunSummary {
  run_id: string;
  task: string;
  project: string;
  workflow_id: string;
  status: string;
  dry_run: boolean;
  total_cost_usd: number;
  total_tokens: number;
  created_at: string;
}

interface DashboardProps {
  onSelectRun: (runId: string) => void;
  onNewRun: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectRun, onNewRun }) => {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [runsRes, metricsRes] = await Promise.all([
        fetch('/api/runs?limit=20'),
        fetch('/api/models/metrics')
      ]);
      const runsData = await runsRes.json();
      const metricsData = await metricsRes.json();
      setRuns(runsData.runs || []);
      setMetrics(metricsData);
    } catch (e) {
      console.error('Error fetching dashboard data:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return <span style={{ color: 'var(--accent-green)', display: 'flex', alignItems: 'center', gap: 4 }}><CheckCircle size={14} /> Completed</span>;
      case 'running':
        return <span style={{ color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', gap: 4 }}><RefreshCw size={14} className="spin" /> Running</span>;
      case 'waiting_gate':
      case 'waiting_budget':
        return <span style={{ color: 'var(--accent-amber)', display: 'flex', alignItems: 'center', gap: 4 }}><AlertTriangle size={14} /> Approval Required</span>;
      default:
        return <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}><Clock size={14} /> {status}</span>;
    }
  };

  return (
    <div style={{ padding: 24, overflowY: 'auto', height: '100%' }}>
      {/* Top Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: '#f8fafc' }}>Enki Command Dashboard</h1>
          <p style={{ color: '#94a3b8', fontSize: 14 }}>Dual-Agent Multi-Model Orchestrator & Execution Hub</p>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button 
            onClick={fetchData} 
            style={{ 
              background: '#1e293b', 
              color: '#f8fafc', 
              border: '1px solid #334155', 
              padding: '8px 16px', 
              borderRadius: 6,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8
            }}>
            <RefreshCw size={16} /> Refresh
          </button>
          <button 
            onClick={onNewRun}
            style={{ 
              background: '#0284c7', 
              color: '#fff', 
              border: 'none', 
              padding: '8px 16px', 
              borderRadius: 6,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8
            }}>
            <Play size={16} /> Start New Run
          </button>
        </div>
      </div>

      {/* Metrics Cards */}
      {metrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          <div style={{ background: '#1e293b', padding: 16, borderRadius: 8, border: '1px solid #334155' }}>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 4 }}>Monthly Budget Usage</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#38bdf8' }}>
              ${metrics.current_month_spend_usd?.toFixed(4)} <span style={{ fontSize: 14, color: '#94a3b8' }}>/ ${metrics.monthly_budget_usd?.toFixed(2)}</span>
            </div>
            <div style={{ width: '100%', height: 6, background: '#334155', borderRadius: 3, marginTop: 8, overflow: 'hidden' }}>
              <div style={{ width: `${metrics.percent_budget_used}%`, height: '100%', background: metrics.percent_budget_used > 80 ? '#f43f5e' : '#38bdf8' }} />
            </div>
          </div>

          <div style={{ background: '#1e293b', padding: 16, borderRadius: 8, border: '1px solid #334155' }}>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 4 }}>Total API Calls (30d)</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#4ade80' }}>
              {metrics.total_calls || 0}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>Telemetry records in SQLite</div>
          </div>

          <div style={{ background: '#1e293b', padding: 16, borderRadius: 8, border: '1px solid #334155' }}>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 4 }}>Total Tokens (30d)</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#fbbf24' }}>
              {(metrics.total_tokens || 0).toLocaleString()}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>Prompt + Completion</div>
          </div>

          <div style={{ background: '#1e293b', padding: 16, borderRadius: 8, border: '1px solid #334155' }}>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 4 }}>Active Runs Monitored</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#f8fafc' }}>
              {runs.length}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>Isolated Git worktrees</div>
          </div>
        </div>
      )}

      {/* Dual Analytics Tables: Model Breakdown & Task Breakdown */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        {/* Model Breakdown */}
        <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', overflow: 'hidden' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid #334155', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8, color: '#38bdf8' }}>
            <Activity size={18} /> Usage by Individual Model
          </div>
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {(!metrics?.all_models_usage || metrics.all_models_usage.length === 0) ? (
              <div style={{ padding: 24, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>No model calls recorded yet.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#0f172a', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                    <th style={{ padding: '8px 12px' }}>Model</th>
                    <th style={{ padding: '8px 12px' }}>Calls</th>
                    <th style={{ padding: '8px 12px' }}>Prompt</th>
                    <th style={{ padding: '8px 12px' }}>Comp</th>
                    <th style={{ padding: '8px 12px' }}>Total Tok</th>
                    <th style={{ padding: '8px 12px' }}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.all_models_usage.map((m: any, idx: number) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #334155' }}>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: '#f8fafc', maxWidth: 160, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={m.model}>
                        {m.model}
                      </td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{m.total_calls}</td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{(m.prompt_tokens || 0).toLocaleString()}</td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{(m.completion_tokens || 0).toLocaleString()}</td>
                      <td style={{ padding: '8px 12px', color: '#fbbf24', fontWeight: 600 }}>{(m.total_tokens || 0).toLocaleString()}</td>
                      <td style={{ padding: '8px 12px', color: '#4ade80', fontWeight: 600 }}>${(m.total_cost_usd || 0).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Task Breakdown */}
        <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', overflow: 'hidden' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid #334155', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8, color: '#fbbf24' }}>
            <Layers size={18} /> Usage per Task / Run
          </div>
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {(!metrics?.task_usage_summary || metrics.task_usage_summary.length === 0) ? (
              <div style={{ padding: 24, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>No task usage recorded yet.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#0f172a', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                    <th style={{ padding: '8px 12px' }}>Task ID</th>
                    <th style={{ padding: '8px 12px' }}>Calls</th>
                    <th style={{ padding: '8px 12px' }}>Models</th>
                    <th style={{ padding: '8px 12px' }}>Total Tok</th>
                    <th style={{ padding: '8px 12px' }}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.task_usage_summary.map((t: any, idx: number) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #334155' }}>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: '#38bdf8', maxWidth: 140, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={t.task_id}>
                        {t.task_id}
                      </td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{t.total_calls}</td>
                      <td style={{ padding: '8px 12px', color: '#94a3b8', maxWidth: 120, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={t.models_used}>
                        {t.models_used || '-'}
                      </td>
                      <td style={{ padding: '8px 12px', color: '#fbbf24', fontWeight: 600 }}>{(t.total_tokens || 0).toLocaleString()}</td>
                      <td style={{ padding: '8px 12px', color: '#4ade80', fontWeight: 600 }}>${(t.total_cost_usd || 0).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Runs Table */}
      <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #334155', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Layers size={18} /> Active & Historical Runs
        </div>
        
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>Loading runs...</div>
        ) : runs.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>No runs executed yet. Click "Start New Run" to launch your first DAG.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 14 }}>
            <thead>
              <tr style={{ background: '#0f172a', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                <th style={{ padding: '12px 16px' }}>Run ID</th>
                <th style={{ padding: '12px 16px' }}>Task</th>
                <th style={{ padding: '12px 16px' }}>Workflow</th>
                <th style={{ padding: '12px 16px' }}>Status</th>
                <th style={{ padding: '12px 16px' }}>Cost</th>
                <th style={{ padding: '12px 16px' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} style={{ borderBottom: '1px solid #334155' }}>
                  <td style={{ padding: '12px 16px', fontFamily: 'monospace', color: '#38bdf8' }}>{r.run_id}</td>
                  <td style={{ padding: '12px 16px', maxWidth: 300, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.task}</td>
                  <td style={{ padding: '12px 16px', color: '#94a3b8' }}>{r.workflow_id}</td>
                  <td style={{ padding: '12px 16px' }}>{getStatusBadge(r.status)}</td>
                  <td style={{ padding: '12px 16px' }}>${(r.total_cost_usd || 0).toFixed(4)}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <button 
                      onClick={() => onSelectRun(r.run_id)}
                      style={{ 
                        background: '#334155', 
                        color: '#f8fafc', 
                        border: 'none', 
                        padding: '4px 12px', 
                        borderRadius: 4, 
                        cursor: 'pointer',
                        fontSize: 12
                      }}>
                      View Live
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
