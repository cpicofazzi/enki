import React, { useState, useEffect } from 'react';
import { 
  CheckCircle, 
  RefreshCw, 
  AlertTriangle, 
  Clock, 
  Terminal as TerminalIcon, 
  GitCommit, 
  GitPullRequest,
  Check,
  X,
  ShieldAlert,
  BookOpen,
  Code,
  Database,
  Layers,
  ArrowRight,
  Eye,
  FileText,
  ShieldCheck,
  Compass,
  Trash2
} from 'lucide-react';

interface LiveRunViewProps {
  runId: string;
  onBack: () => void;
}

export const LiveRunView: React.FC<LiveRunViewProps> = ({ runId, onBack }) => {
  const [run, setRun] = useState<any>(null);
  const [flowData, setFlowData] = useState<any>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [diff, setDiff] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'flow' | 'notes' | 'code' | 'dag' | 'logs' | 'diff'>('flow');
  const [gateFeedback, setGateFeedback] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [selectedNotePreview, setSelectedNotePreview] = useState<any>(null);

  // Fetch Run state
  const fetchRun = async () => {
    try {
      const res = await fetch(`/api/runs/${runId}`);
      if (res.ok) {
        const data = await res.json();
        setRun(data);
        if (data.subagents_flow_data) {
          setFlowData(data.subagents_flow_data);
        }
      }
    } catch (e) {
      console.error('Error fetching run:', e);
    }
  };

  // Fetch Flow & Artifacts specifically
  const fetchFlow = async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/subagents-flow`);
      if (res.ok) {
        const data = await res.json();
        setFlowData(data);
      }
    } catch (e) {
      console.error('Error fetching flow:', e);
    }
  };

  // Fetch Diff
  const fetchDiff = async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/diff`);
      if (res.ok) {
        const data = await res.json();
        setDiff(data.diff || '(No uncommitted changes in worktree)');
      }
    } catch (e) {
      console.error('Error fetching diff:', e);
    }
  };

  useEffect(() => {
    fetchRun();
    fetchFlow();
    fetchDiff();

    // Setup SSE connection
    const eventSource = new EventSource(`/api/runs/${runId}/stream`);

    eventSource.onmessage = () => {
      fetchRun();
      fetchFlow();
    };

    eventSource.addEventListener('log_chunk', (e: any) => {
      try {
        const data = JSON.parse(e.data);
        const chunk = data.payload?.chunk || data.chunk || '';
        if (chunk) {
          setLogs((prev) => [...prev, chunk]);
        }
      } catch (err) {}
    });

    eventSource.addEventListener('gate_waiting', () => {
      fetchRun();
      fetchFlow();
    });

    eventSource.addEventListener('budget_stop', () => {
      fetchRun();
      fetchFlow();
    });

    eventSource.addEventListener('step_completed', () => {
      fetchRun();
      fetchFlow();
      fetchDiff();
    });

    eventSource.addEventListener('run_completed', () => {
      fetchRun();
      fetchFlow();
      fetchDiff();
    });

    return () => {
      eventSource.close();
    };
  }, [runId]);

  const handleResolveGate = async (action: string) => {
    setActionLoading(true);
    try {
      await fetch(`/api/runs/${runId}/gate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gate_id: run?.gate_state?.gate_id || 'approval_gate',
          action: action,
          feedback: gateFeedback
        })
      });
      fetchRun();
      fetchFlow();
    } catch (e) {
      console.error('Gate resolve error:', e);
    } finally {
      setActionLoading(false);
    }
  };

  const handleResolveBudget = async (decision: string, cheaperModel?: string) => {
    setActionLoading(true);
    try {
      await fetch(`/api/runs/${runId}/budget`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: decision,
          cheaper_model: cheaperModel
        })
      });
      fetchRun();
      fetchFlow();
    } catch (e) {
      console.error('Budget resolve error:', e);
    } finally {
      setActionLoading(false);
    }
  };

  const handleWorktreeAction = async (action: 'merge' | 'keep' | 'discard') => {
    setActionLoading(true);
    try {
      await fetch(`/api/runs/${runId}/worktree`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action, target_branch: 'main' })
      });
      fetchRun();
      fetchFlow();
      alert(`Worktree successfully actioned: ${action}`);
    } catch (e) {
      console.error('Worktree action error:', e);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteRun = async () => {
    if (!window.confirm(`Permanently delete run ${runId}?\n\nThis will remove all artifacts, logs, and state files.`)) {
      return;
    }
    setActionLoading(true);
    try {
      const res = await fetch(`/api/runs/${runId}`, { method: 'DELETE' });
      if (res.ok) {
        onBack();
      } else {
        alert(`Failed to delete run ${runId}`);
      }
    } catch (e) {
      console.error('Delete run error:', e);
    } finally {
      setActionLoading(false);
    }
  };

  const getSubagentIcon = (id: string) => {
    switch (id) {
      case 'hermes':
        return <BookOpen size={16} />;
      case 'omp':
        return <Code size={16} />;
      case 'reviewer':
        return <ShieldCheck size={16} />;
      case 'supervisor':
        return <CheckCircle size={16} />;
      default:
        return <Layers size={16} />;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0f172a' }}>
      {/* Header Banner */}
      <div style={{ padding: '16px 24px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button onClick={onBack} style={{ background: '#334155', color: '#fff', border: 'none', padding: '6px 12px', borderRadius: 4, cursor: 'pointer' }}>
            ← Back
          </button>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#f8fafc' }}>{run?.task || 'Loading run...'}</div>
            <div style={{ fontSize: 13, color: '#94a3b8', display: 'flex', gap: 12 }}>
              <span>ID: <code style={{ color: '#38bdf8' }}>{runId}</code></span>
              <span>Workflow: <code>{run?.workflow_id}</code></span>
              <span>Status: <strong style={{ color: run?.status === 'completed' ? '#4ade80' : run?.status === 'running' ? '#38bdf8' : '#fbbf24' }}>{run?.status}</strong></span>
              <span>Cost: <strong>${(run?.telemetry?.total_cost_usd || 0).toFixed(4)}</strong></span>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Worktree Teardown Controls for completed runs */}
          {run?.status === 'completed' && (
            <>
              <button onClick={() => handleWorktreeAction('merge')} disabled={actionLoading} style={{ background: '#16a34a', color: '#fff', border: 'none', padding: '6px 12px', borderRadius: 4, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                <GitPullRequest size={14} /> Merge
              </button>
              <button onClick={() => handleWorktreeAction('keep')} disabled={actionLoading} style={{ background: '#0284c7', color: '#fff', border: 'none', padding: '6px 12px', borderRadius: 4, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                <GitCommit size={14} /> Keep Branch
              </button>
              <button onClick={() => handleWorktreeAction('discard')} disabled={actionLoading} style={{ background: '#e11d48', color: '#fff', border: 'none', padding: '6px 12px', borderRadius: 4, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                <X size={14} /> Discard
              </button>
            </>
          )}

          <button 
            onClick={handleDeleteRun} 
            disabled={actionLoading} 
            title="Permanently Delete Run"
            style={{ 
              background: '#450a0a', 
              color: '#fca5a5', 
              border: '1px solid #7f1d1d', 
              padding: '6px 12px', 
              borderRadius: 4, 
              cursor: 'pointer', 
              display: 'flex', 
              alignItems: 'center', 
              gap: 6,
              fontSize: 13,
              fontWeight: 600
            }}>
            <Trash2 size={14} /> Delete Run
          </button>
        </div>
      </div>

      {/* Visual Subagents Flow Pipeline Ribbon */}
      <div style={{ background: '#020617', borderBottom: '1px solid #1e293b', padding: '14px 24px' }}>
        <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#94a3b8', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Layers size={14} style={{ color: '#38bdf8' }} /> Subagent Execution Flow & Handoff Pipeline
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, overflowX: 'auto', paddingBottom: 4 }}>
          {flowData?.subagents_flow?.map((stage: any, idx: number) => {
            const isCompleted = stage.status === 'completed';
            const isRunning = stage.status === 'running';
            const isWaiting = stage.status.includes('gate');
            const borderColor = isCompleted ? '#22c55e' : isRunning ? '#38bdf8' : isWaiting ? '#eab308' : '#334155';
            const bgColor = isCompleted ? '#064e3b' : isRunning ? '#0c4a6e' : isWaiting ? '#713f12' : '#1e293b';

            return (
              <React.Fragment key={stage.step_id}>
                <div 
                  onClick={() => setActiveTab('flow')}
                  style={{ 
                    background: bgColor, 
                    border: `1px solid ${borderColor}`, 
                    borderRadius: 8, 
                    padding: '8px 14px', 
                    minWidth: 200,
                    cursor: 'pointer',
                    transition: 'transform 0.15s ease'
                  }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: stage.color || '#38bdf8', display: 'flex', alignItems: 'center', gap: 6 }}>
                      {getSubagentIcon(stage.subagent_id)} {stage.subagent_name}
                    </span>
                    <span style={{ 
                      fontSize: 10, 
                      fontWeight: 700, 
                      padding: '2px 6px', 
                      borderRadius: 4, 
                      background: isCompleted ? '#15803d' : isRunning ? '#0369a1' : '#334155',
                      color: '#fff'
                    }}>
                      {stage.status.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {stage.step_name}
                  </div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2, display: 'flex', justifyContent: 'space-between' }}>
                    <span>{stage.model?.split('/')[1] || stage.model || 'auto'}</span>
                    <span>{stage.duration_seconds ? `${stage.duration_seconds}s` : ''}</span>
                  </div>
                </div>
                {idx < (flowData?.subagents_flow?.length - 1) && (
                  <ArrowRight size={18} style={{ color: '#475569', flexShrink: 0 }} />
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* Gate Overlay Banner if waiting */}
      {run?.status === 'waiting_gate' && (
        <div style={{ background: '#854d0e', padding: 16, borderBottom: '1px solid #ca8a04', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 700, color: '#fef08a', display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertTriangle size={18} /> Human Approval Gate Triggered ({run?.gate_state?.gate_id})
            </div>
            <div style={{ fontSize: 14, color: '#fef9c3', marginTop: 4 }}>
              Hermes extracted constraints and is awaiting approval before OMP coding.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input 
              type="text" 
              placeholder="Feedback (optional)..." 
              value={gateFeedback} 
              onChange={(e) => setGateFeedback(e.target.value)} 
              style={{ padding: '6px 12px', borderRadius: 4, border: '1px solid #ca8a04', background: '#422006', color: '#fff' }}
            />
            <button onClick={() => handleResolveGate('approve')} style={{ background: '#16a34a', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}>
              Approve
            </button>
            <button onClick={() => handleResolveGate('reject')} style={{ background: '#e11d48', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}>
              Reject
            </button>
          </div>
        </div>
      )}

      {/* Budget Intercept Banner */}
      {run?.status === 'waiting_budget' && (
        <div style={{ background: '#7f1d1d', padding: 16, borderBottom: '1px solid #dc2626', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 700, color: '#fca5a5', display: 'flex', alignItems: 'center', gap: 8 }}>
              <ShieldAlert size={18} /> Monthly Budget Limit Reached ($25.00)
            </div>
            <div style={{ fontSize: 14, color: '#fee2e2', marginTop: 4 }}>
              Execution halted before model call to prevent unexpected charges.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => handleResolveBudget('continue')} style={{ background: '#0284c7', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}>
              Continue Spend
            </button>
            <button onClick={() => handleResolveBudget('switch_cheaper', 'deepseek/deepseek-chat')} style={{ background: '#16a34a', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}>
              Switch to DeepSeek ($0.14/M)
            </button>
            <button onClick={() => handleResolveBudget('pause')} style={{ background: '#64748b', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}>
              Pause Run
            </button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', background: '#1e293b', borderBottom: '1px solid #334155', padding: '0 24px' }}>
        <button 
          onClick={() => setActiveTab('flow')}
          style={{ 
            background: 'none', 
            border: 'none', 
            borderBottom: activeTab === 'flow' ? '2px solid #38bdf8' : 'none', 
            color: activeTab === 'flow' ? '#38bdf8' : '#94a3b8', 
            padding: '12px 16px', 
            cursor: 'pointer',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 8
          }}>
          <Layers size={16} /> Subagent Flow & Overview
        </button>
        <button 
          onClick={() => setActiveTab('notes')}
          style={{ 
            background: 'none', 
            border: 'none', 
            borderBottom: activeTab === 'notes' ? '2px solid #38bdf8' : 'none', 
            color: activeTab === 'notes' ? '#38bdf8' : '#94a3b8', 
            padding: '12px 16px', 
            cursor: 'pointer',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 8
          }}>
          <BookOpen size={16} /> Notes Processed ({flowData?.processed_notes?.notes_read_count || 0})
        </button>
        <button 
          onClick={() => setActiveTab('code')}
          style={{ 
            background: 'none', 
            border: 'none', 
            borderBottom: activeTab === 'code' ? '2px solid #38bdf8' : 'none', 
            color: activeTab === 'code' ? '#38bdf8' : '#94a3b8', 
            padding: '12px 16px', 
            cursor: 'pointer',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 8
          }}>
          <Code size={16} /> Code Processed ({flowData?.processed_code?.stat?.total_files || 0} files)
        </button>
        <button 
          onClick={() => setActiveTab('dag')}
          style={{ 
            background: 'none', 
            border: 'none', 
            borderBottom: activeTab === 'dag' ? '2px solid #38bdf8' : 'none', 
            color: activeTab === 'dag' ? '#38bdf8' : '#94a3b8', 
            padding: '12px 16px', 
            cursor: 'pointer',
            fontWeight: 600
          }}>
          DAG Steps
        </button>
        <button 
          onClick={() => setActiveTab('logs')}
          style={{ 
            background: 'none', 
            border: 'none', 
            borderBottom: activeTab === 'logs' ? '2px solid #38bdf8' : 'none', 
            color: activeTab === 'logs' ? '#38bdf8' : '#94a3b8', 
            padding: '12px 16px', 
            cursor: 'pointer',
            fontWeight: 600
          }}>
          Live Logs ({logs.length})
        </button>
        <button 
          onClick={() => setActiveTab('diff')}
          style={{ 
            background: 'none', 
            border: 'none', 
            borderBottom: activeTab === 'diff' ? '2px solid #38bdf8' : 'none', 
            color: activeTab === 'diff' ? '#38bdf8' : '#94a3b8', 
            padding: '12px 16px', 
            cursor: 'pointer',
            fontWeight: 600
          }}>
          Git Worktree Diff
        </button>
      </div>

      {/* Tab Contents */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        
        {/* TAB 1: Subagents Flow & Artifacts Overview */}
        {activeTab === 'flow' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            {/* Summary Highlights */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
              <div style={{ background: '#1e293b', padding: 18, borderRadius: 8, border: '1px solid #38bdf8' }}>
                <div style={{ fontSize: 13, color: '#38bdf8', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <BookOpen size={16} /> Hermes Knowledge Subagent
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', marginTop: 8 }}>
                  {flowData?.processed_notes?.notes_read_count || 0} Notes Consulted
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                  Vault: <code>pico-vault</code> | Synced to Activity Log
                </div>
              </div>

              <div style={{ background: '#1e293b', padding: 18, borderRadius: 8, border: '1px solid #a855f7' }}>
                <div style={{ fontSize: 13, color: '#a855f7', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Code size={16} /> Oh My Pi (OMP) Coding Subagent
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', marginTop: 8 }}>
                  {flowData?.processed_code?.stat?.total_files || 0} Files Modified
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                  Branch: <code>{flowData?.processed_code?.branch_name || 'enki/run/...'}</code>
                </div>
              </div>

              <div style={{ background: '#1e293b', padding: 18, borderRadius: 8, border: '1px solid #10b981' }}>
                <div style={{ fontSize: 13, color: '#10b981', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <CheckCircle size={16} /> Verification & Safety Gates
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', marginTop: 8 }}>
                  {flowData?.processed_code?.verification?.status || 'PENDING'}
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                  Command: <code>py -m pytest -q</code>
                </div>
              </div>
            </div>

            {/* Subagent Stages Detailed Cards */}
            <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', padding: 20 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#f8fafc', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Layers size={18} style={{ color: '#38bdf8' }} /> Execution Stage Details
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {flowData?.subagents_flow?.map((stage: any) => (
                  <div 
                    key={stage.step_id} 
                    style={{ 
                      background: '#0f172a', 
                      borderRadius: 8, 
                      border: '1px solid #334155', 
                      padding: 16,
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center'
                    }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ 
                          background: stage.color || '#38bdf8', 
                          color: '#0f172a', 
                          fontWeight: 800, 
                          fontSize: 11, 
                          padding: '2px 8px', 
                          borderRadius: 4 
                        }}>
                          {stage.subagent_name}
                        </span>
                        <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: 15 }}>
                          {stage.step_name}
                        </span>
                        <span style={{ color: '#64748b', fontSize: 12 }}>
                          ({stage.subagent_role})
                        </span>
                      </div>
                      <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 6 }}>
                        Boundary: <code style={{ color: '#fcd34d' }}>{stage.boundary}</code> | Model: <code style={{ color: '#38bdf8' }}>{stage.model}</code>
                        {stage.artifacts_summary && (
                          <span style={{ marginLeft: 12, color: '#e2e8f0', fontStyle: 'italic' }}>
                            • {stage.artifacts_summary}
                          </span>
                        )}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ 
                        fontWeight: 700, 
                        fontSize: 13,
                        color: stage.status === 'completed' ? '#4ade80' : stage.status === 'running' ? '#38bdf8' : '#fbbf24' 
                      }}>
                        {stage.status.toUpperCase()}
                      </div>
                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                        Duration: {stage.duration_seconds ? `${stage.duration_seconds}s` : '-'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Vault Boundary Guard Banner */}
            <div style={{ background: '#020617', border: '1px solid #1e293b', borderRadius: 8, padding: 16, display: 'flex', alignItems: 'center', gap: 14 }}>
              <ShieldCheck size={28} style={{ color: '#38bdf8', flexShrink: 0 }} />
              <div>
                <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 14 }}>
                  Architectural Safety Boundary Active
                </div>
                <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 2 }}>
                  {flowData?.processed_notes?.boundary_rule || 'Hermes exclusively reads and logs to Obsidian vault notes. Oh My Pi (OMP) is strictly confined to git worktree repository code.'}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: Notes Processed (Hermes) */}
        {activeTab === 'notes' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Vault Location Info */}
            <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>Active Obsidian Vault Location</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: '#38bdf8', fontFamily: 'monospace', marginTop: 4 }}>
                  {flowData?.processed_notes?.vault_path || 'pico-vault'}
                </div>
              </div>
              <span style={{ background: '#065f46', color: '#a7f3d0', padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>
                ✓ Vault Boundary Verified
              </span>
            </div>

            {/* Notes Read Table */}
            <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', overflow: 'hidden' }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid #334155', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: 8 }}>
                <BookOpen size={18} style={{ color: '#38bdf8' }} /> Vault Notes Read & Indexed for Technical Context ({flowData?.processed_notes?.notes_read?.length || 0})
              </div>
              {(!flowData?.processed_notes?.notes_read || flowData.processed_notes.notes_read.length === 0) ? (
                <div style={{ padding: 32, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
                  No vault notes were matched for this task.
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#0f172a', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                      <th style={{ padding: '10px 14px' }}>Match Score</th>
                      <th style={{ padding: '10px 14px' }}>Vault Note Path</th>
                      <th style={{ padding: '10px 14px' }}>Title</th>
                      <th style={{ padding: '10px 14px' }}>Content Excerpt</th>
                      <th style={{ padding: '10px 14px' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flowData.processed_notes.notes_read.map((note: any, idx: number) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #334155' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 700, color: '#38bdf8' }}>{note.score || '-'}</td>
                        <td style={{ padding: '10px 14px', fontFamily: 'monospace', color: '#f8fafc' }}>{note.path}</td>
                        <td style={{ padding: '10px 14px', fontWeight: 600, color: '#cbd5e1' }}>{note.title}</td>
                        <td style={{ padding: '10px 14px', color: '#94a3b8', maxWidth: 350, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {note.excerpt}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <button 
                            onClick={() => setSelectedNotePreview(note)}
                            style={{ background: '#334155', color: '#fff', border: 'none', padding: '4px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                            <Eye size={12} /> Preview
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Notes Written / Synced Table */}
            <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', overflow: 'hidden' }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid #334155', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Database size={18} style={{ color: '#10b981' }} /> Notes Written & Synced to Vault ({flowData?.processed_notes?.notes_written?.length || 0})
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#0f172a', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                    <th style={{ padding: '10px 14px' }}>Subagent</th>
                    <th style={{ padding: '10px 14px' }}>Target Note</th>
                    <th style={{ padding: '10px 14px' }}>Action Performed</th>
                    <th style={{ padding: '10px 14px' }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {flowData?.processed_notes?.notes_written?.map((nw: any, idx: number) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #334155' }}>
                      <td style={{ padding: '10px 14px', color: '#38bdf8', fontWeight: 600 }}>{nw.subagent || 'Hermes'}</td>
                      <td style={{ padding: '10px 14px', fontFamily: 'monospace', color: '#f8fafc' }}>{nw.path}</td>
                      <td style={{ padding: '10px 14px', color: '#cbd5e1' }}>{nw.action}</td>
                      <td style={{ padding: '10px 14px' }}>
                        <span style={{ 
                          color: nw.status === 'synced' ? '#4ade80' : '#fbbf24', 
                          fontWeight: 700 
                        }}>
                          {nw.status?.toUpperCase()}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Note Excerpt Modal */}
            {selectedNotePreview && (
              <div style={{ 
                position: 'fixed', 
                top: 0, 
                left: 0, 
                right: 0, 
                bottom: 0, 
                background: 'rgba(0,0,0,0.7)', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center', 
                zIndex: 100 
              }}>
                <div style={{ background: '#1e293b', width: 650, maxHeight: '80vh', borderRadius: 8, padding: 24, border: '1px solid #38bdf8', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <h3 style={{ margin: 0, color: '#38bdf8', fontSize: 18 }}>{selectedNotePreview.title}</h3>
                    <button onClick={() => setSelectedNotePreview(null)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 18 }}>✕</button>
                  </div>
                  <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 12, fontFamily: 'monospace' }}>
                    {selectedNotePreview.path} (Relevance Score: {selectedNotePreview.score})
                  </div>
                  <div style={{ background: '#020617', padding: 16, borderRadius: 6, color: '#f8fafc', fontSize: 13, overflowY: 'auto', flex: 1, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {selectedNotePreview.excerpt}
                  </div>
                  <button onClick={() => setSelectedNotePreview(null)} style={{ marginTop: 16, alignSelf: 'flex-end', background: '#0284c7', color: '#fff', border: 'none', padding: '6px 16px', borderRadius: 4, cursor: 'pointer' }}>
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: Code Processed (Oh My Pi) */}
        {activeTab === 'code' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Location & Worktree Banner */}
            <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>Git Worktree & Repository Isolation</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: '#a855f7', fontFamily: 'monospace', marginTop: 4 }}>
                  Branch: <strong style={{ color: '#f8fafc' }}>{flowData?.processed_code?.branch_name || 'enki/run/...'}</strong>
                </div>
                <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 2 }}>
                  Path: <code>{flowData?.processed_code?.worktree_path || '.worktrees/...'}</code>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 13, color: '#4ade80', fontWeight: 600 }}>
                  +{flowData?.processed_code?.stat?.total_additions || 0} additions
                </span>
                <span style={{ fontSize: 13, color: '#f43f5e', fontWeight: 600, marginLeft: 12 }}>
                  -{flowData?.processed_code?.stat?.total_deletions || 0} deletions
                </span>
              </div>
            </div>

            {/* Files Touched Table */}
            <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', overflow: 'hidden' }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid #334155', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Code size={18} style={{ color: '#a855f7' }} /> Repository Code Files Touched ({flowData?.processed_code?.stat?.files?.length || 0})
              </div>
              {(!flowData?.processed_code?.stat?.files || flowData.processed_code.stat.files.length === 0) ? (
                <div style={{ padding: 32, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
                  No repository files modified in worktree (or dry-run simulation mode).
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#0f172a', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                      <th style={{ padding: '10px 14px' }}>Status</th>
                      <th style={{ padding: '10px 14px' }}>File Path</th>
                      <th style={{ padding: '10px 14px' }}>Additions (+)</th>
                      <th style={{ padding: '10px 14px' }}>Deletions (-)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flowData.processed_code.stat.files.map((file: any, idx: number) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #334155' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 700, color: '#a855f7' }}>{file.status}</td>
                        <td style={{ padding: '10px 14px', fontFamily: 'monospace', color: '#f8fafc' }}>{file.path}</td>
                        <td style={{ padding: '10px 14px', color: '#4ade80', fontWeight: 600 }}>+{file.additions}</td>
                        <td style={{ padding: '10px 14px', color: '#f43f5e', fontWeight: 600 }}>-{file.deletions}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Test Suite Verification Card */}
            <div style={{ background: '#1e293b', borderRadius: 8, border: '1px solid #334155', padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <CheckCircle size={18} style={{ color: '#10b981' }} /> Verification Suite Results
                </div>
                <span style={{ 
                  background: flowData?.processed_code?.verification?.status === 'PASSED' ? '#065f46' : '#713f12', 
                  color: flowData?.processed_code?.verification?.status === 'PASSED' ? '#a7f3d0' : '#fef08a', 
                  padding: '4px 10px', 
                  borderRadius: 6, 
                  fontSize: 12, 
                  fontWeight: 700 
                }}>
                  {flowData?.processed_code?.verification?.status || 'PENDING'}
                </span>
              </div>
              <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 12 }}>
                Executed Test Commands: <code>{flowData?.processed_code?.verification?.test_commands?.join(', ') || 'py -m pytest -q'}</code>
              </div>
              {flowData?.processed_code?.verification?.results?.length > 0 && (
                <div style={{ background: '#020617', padding: 14, borderRadius: 6, fontFamily: 'monospace', fontSize: 12, color: '#cbd5e1', maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
                  {flowData.processed_code.verification.results[0]?.stdout || 'Test run completed.'}
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 4: DAG Steps */}
        {activeTab === 'dag' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {run?.steps?.map((step: any, idx: number) => (
              <div 
                key={step.step_id} 
                style={{ 
                  background: '#1e293b', 
                  border: '1px solid #334155', 
                  borderRadius: 8, 
                  padding: 16,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                <div>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 16 }}>
                    {idx + 1}. {step.name || step.step_id}
                  </div>
                  <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 4 }}>
                    Type: <code style={{ color: '#38bdf8' }}>{step.step_type}</code> | Model: <code>{step.model || 'auto-route'}</code>
                  </div>
                </div>
                <div>
                  {step.status === 'completed' && <span style={{ color: '#4ade80', fontWeight: 600 }}>✓ COMPLETED</span>}
                  {step.status === 'running' && <span style={{ color: '#38bdf8', fontWeight: 600 }}>⚡ RUNNING</span>}
                  {step.status === 'waiting_gate' && <span style={{ color: '#fbbf24', fontWeight: 600 }}>⏳ APPROVAL GATE</span>}
                  {step.status === 'pending' && <span style={{ color: '#94a3b8' }}>PENDING</span>}
                  {step.status === 'failed' && <span style={{ color: '#f43f5e', fontWeight: 600 }}>✗ FAILED</span>}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* TAB 5: Live Logs */}
        {activeTab === 'logs' && (
          <div style={{ background: '#020617', padding: 16, borderRadius: 8, fontFamily: 'monospace', fontSize: 13, color: '#f1f5f9', height: '100%', overflowY: 'auto' }}>
            {logs.length === 0 ? (
              <div style={{ color: '#64748b' }}>Waiting for stdout / test log chunks from EventBus...</div>
            ) : (
              logs.map((log, idx) => <div key={idx} style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{log}</div>)
            )}
          </div>
        )}

        {/* TAB 6: Git Diff */}
        {activeTab === 'diff' && (
          <div style={{ background: '#020617', padding: 16, borderRadius: 8, fontFamily: 'monospace', fontSize: 13, color: '#38bdf8', height: '100%', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
            {diff || 'No changes generated.'}
          </div>
        )}
      </div>
    </div>
  );
};
