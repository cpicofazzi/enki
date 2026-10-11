import React, { useState, useEffect } from 'react';
import { 
  Play, 
  Layers, 
  Cpu, 
  FileText,
  DollarSign
} from 'lucide-react';

interface StartRunModalProps {
  onClose: () => void;
  onRunCreated: (runId: string) => void;
}

export const StartRunModal: React.FC<StartRunModalProps> = ({ onClose, onRunCreated }) => {
  const [task, setTask] = useState('');
  const [project, setProject] = useState('General');
  const [workflowId, setWorkflowId] = useState('four_step_pipeline');
  const [dryRun, setDryRun] = useState(true);
  const [gateway, setGateway] = useState('openrouter');
  const [modelOverride, setModelOverride] = useState('');
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Fetch available workflows
    fetch('/api/workflows')
      .then((r) => r.json())
      .then((d) => setWorkflows(d.workflows || []))
      .catch((e) => console.error(e));

    // Fetch models
    fetch('/api/models')
      .then((r) => r.json())
      .then((d) => setModels(d.models || []))
      .catch((e) => console.error(e));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!task.trim()) return;

    setSubmitting(true);
    try {
      const res = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: task,
          project: project,
          workflow_id: workflowId,
          dry_run: dryRun,
          gateway: gateway,
          model_override: modelOverride || undefined,
          start_immediately: true
        })
      });
      const data = await res.json();
      if (data.success && data.run) {
        onRunCreated(data.run.run_id);
      }
    } catch (err) {
      console.error('Run creation error:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, width: 560, maxWidth: '90%', padding: 24, boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)' }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', marginBottom: 16 }}>Start New Enki Workflow Run</h2>
        
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Task Description *</label>
            <textarea 
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="e.g. Implement order recipe normalization in Dinner Service Optimizer..."
              rows={3}
              required
              style={{ width: '100%', padding: 10, borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#fff', fontSize: 14 }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Target Project</label>
              <select 
                value={project}
                onChange={(e) => setProject(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#fff' }}>
                <option value="General">General / Scratch</option>
                <option value="Dinner Service Optimizer">Dinner Service Optimizer</option>
                <option value="Math Package">Math Package</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>DAG Workflow Template</label>
              <select 
                value={workflowId}
                onChange={(e) => setWorkflowId(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#fff' }}>
                {workflows.map((wf) => (
                  <option key={wf.id} value={wf.id}>{wf.name || wf.id}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Gateway</label>
              <select 
                value={gateway}
                onChange={(e) => setGateway(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#fff' }}>
                <option value="openrouter">OpenRouter (Multi-Provider)</option>
                <option value="opencode_zen">OpenCode Zen (Coding SOTA)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>Model Override (Optional)</label>
              <select 
                value={modelOverride}
                onChange={(e) => setModelOverride(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#fff' }}>
                <option value="">(Auto-route according to DAG tier)</option>
                {models.slice(0, 15).map((m) => (
                  <option key={m.id} value={m.id}>{m.name || m.id}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Dry Run Checkbox */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', background: '#0f172a', borderRadius: 6, border: '1px solid #334155' }}>
            <input 
              type="checkbox" 
              id="dryRunToggle"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              style={{ width: 16, height: 16 }}
            />
            <label htmlFor="dryRunToggle" style={{ fontSize: 13, color: '#f8fafc', cursor: 'pointer' }}>
              <strong>Dry-Run Simulation Mode ($0.00 spend)</strong>
              <div style={{ color: '#94a3b8', fontSize: 12 }}>Validates execution, gates, and worktrees without calling paid model APIs.</div>
            </label>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 8 }}>
            <button 
              type="button" 
              onClick={onClose}
              style={{ padding: '8px 16px', borderRadius: 6, background: '#334155', color: '#fff', border: 'none', cursor: 'pointer' }}>
              Cancel
            </button>
            <button 
              type="submit" 
              disabled={submitting || !task.trim()}
              style={{ padding: '8px 20px', borderRadius: 6, background: '#0284c7', color: '#fff', border: 'none', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Play size={16} /> {submitting ? 'Launching...' : 'Launch Workflow'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
