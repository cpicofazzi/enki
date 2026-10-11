import React, { useState, useEffect } from 'react';
import { 
  GitFork, 
  Save, 
  Plus, 
  Layers, 
  Check, 
  AlertCircle 
} from 'lucide-react';

export const WorkflowEditor: React.FC = () => {
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [selectedWf, setSelectedWf] = useState<any>(null);
  const [yamlContent, setYamlContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/workflows')
      .then((r) => r.json())
      .then((d) => {
        setWorkflows(d.workflows || []);
        if (d.workflows && d.workflows.length > 0) {
          loadWorkflow(d.workflows[0].id);
        }
      })
      .catch((e) => console.error(e));
  }, []);

  const loadWorkflow = async (id: string) => {
    try {
      const res = await fetch(`/api/workflows/${id}`);
      const data = await res.json();
      setSelectedWf(data);
      setYamlContent(data.yaml || '');
      setSaveStatus(null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSave = async () => {
    if (!selectedWf) return;
    setSaving(true);
    setSaveStatus(null);
    try {
      const res = await fetch('/api/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: selectedWf.filename || `${selectedWf.id}.yaml`,
          yaml_content: yamlContent
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setSaveStatus('Workflow saved and validated successfully!');
      } else {
        setSaveStatus(`Validation error: ${data.detail || 'Invalid schema'}`);
      }
    } catch (err: any) {
      setSaveStatus(`Save error: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100%', background: '#0f172a' }}>
      {/* Sidebar: workflow selector */}
      <div style={{ width: 280, background: '#1e293b', borderRight: '1px solid #334155', padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#f8fafc', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Layers size={18} /> Templates ({workflows.length})
        </div>
        {workflows.map((wf) => (
          <button
            key={wf.id}
            onClick={() => loadWorkflow(wf.id)}
            style={{
              padding: '10px 14px',
              borderRadius: 6,
              background: selectedWf?.id === wf.id ? '#0284c7' : '#0f172a',
              color: '#f8fafc',
              border: '1px solid #334155',
              cursor: 'pointer',
              textAlign: 'left',
              display: 'flex',
              flexDirection: 'column',
              gap: 4
            }}>
            <div style={{ fontWeight: 600 }}>{wf.name || wf.id}</div>
            <div style={{ fontSize: 12, color: '#94a3b8' }}>{wf.step_count} DAG steps</div>
          </button>
        ))}
      </div>

      {/* Editor Main Canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* Top toolbar */}
        <div style={{ padding: '12px 24px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16, color: '#f8fafc' }}>
              {selectedWf?.definition?.name || selectedWf?.id}
            </div>
            <div style={{ fontSize: 13, color: '#94a3b8' }}>
              Execution Order: {selectedWf?.execution_order?.join(' → ')}
            </div>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              background: '#16a34a',
              color: '#fff',
              border: 'none',
              padding: '8px 16px',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}>
            <Save size={16} /> {saving ? 'Saving...' : 'Save & Validate YAML'}
          </button>
        </div>

        {saveStatus && (
          <div style={{ padding: '8px 24px', background: saveStatus.includes('error') ? '#7f1d1d' : '#14532d', color: '#fff', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
            {saveStatus.includes('error') ? <AlertCircle size={16} /> : <Check size={16} />}
            {saveStatus}
          </div>
        )}

        {/* YAML Textarea with Round-trip Schema Persistence */}
        <div style={{ flex: 1, padding: 16 }}>
          <textarea
            value={yamlContent}
            onChange={(e) => setYamlContent(e.target.value)}
            style={{
              width: '100%',
              height: '100%',
              background: '#020617',
              border: '1px solid #334155',
              borderRadius: 8,
              color: '#38bdf8',
              fontFamily: 'monospace',
              fontSize: 14,
              padding: 16,
              lineHeight: 1.5,
              resize: 'none'
            }}
          />
        </div>
      </div>
    </div>
  );
};
