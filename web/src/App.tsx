import React, { useState } from 'react';
import { 
  Home, 
  Play, 
  GitBranch, 
  Database, 
  Terminal, 
  Cpu, 
  Layers,
  Settings
} from 'lucide-react';
import { Dashboard } from './components/Dashboard.tsx';
import { LiveRunView } from './components/LiveRunView.tsx';
import { WorkflowEditor } from './components/WorkflowEditor.tsx';
import { StartRunModal } from './components/StartRunModal.tsx';

export default function App() {
  const [currentView, setCurrentView] = useState<'dashboard' | 'live' | 'workflows'>('dashboard');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [showStartModal, setShowStartModal] = useState<boolean>(false);

  const handleSelectRun = (runId: string) => {
    setActiveRunId(runId);
    setCurrentView('live');
  };

  const handleRunCreated = (runId: string) => {
    setShowStartModal(false);
    setActiveRunId(runId);
    setCurrentView('live');
  };

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', background: '#0f172a', color: '#f8fafc' }}>
      {/* Left Navigation Bar */}
      <div style={{ width: 68, background: '#020617', borderRight: '1px solid #1e293b', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '16px 0', gap: 20 }}>
        <div style={{ fontWeight: 800, fontSize: 18, color: '#38bdf8', letterSpacing: 1 }}>
          ENKI
        </div>

        <button 
          onClick={() => setCurrentView('dashboard')}
          title="Dashboard"
          style={{ 
            background: currentView === 'dashboard' ? '#1e293b' : 'none', 
            color: currentView === 'dashboard' ? '#38bdf8' : '#94a3b8', 
            border: 'none', 
            padding: 12, 
            borderRadius: 8, 
            cursor: 'pointer' 
          }}>
          <Home size={22} />
        </button>

        <button 
          onClick={() => setCurrentView('workflows')}
          title="Workflows & DAGs"
          style={{ 
            background: currentView === 'workflows' ? '#1e293b' : 'none', 
            color: currentView === 'workflows' ? '#38bdf8' : '#94a3b8', 
            border: 'none', 
            padding: 12, 
            borderRadius: 8, 
            cursor: 'pointer' 
          }}>
          <Layers size={22} />
        </button>

        {activeRunId && (
          <button 
            onClick={() => setCurrentView('live')}
            title="Active Run View"
            style={{ 
              background: currentView === 'live' ? '#1e293b' : 'none', 
              color: currentView === 'live' ? '#38bdf8' : '#94a3b8', 
              border: 'none', 
              padding: 12, 
              borderRadius: 8, 
              cursor: 'pointer' 
            }}>
            <Terminal size={22} />
          </button>
        )}

        <div style={{ flex: 1 }} />

        <button 
          onClick={() => setShowStartModal(true)}
          title="Start New Run"
          style={{ 
            background: '#0284c7', 
            color: '#fff', 
            border: 'none', 
            padding: 12, 
            borderRadius: 8, 
            cursor: 'pointer' 
          }}>
          <Play size={22} />
        </button>
      </div>

      {/* Main View Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {currentView === 'dashboard' && (
          <Dashboard 
            onSelectRun={handleSelectRun} 
            onNewRun={() => setShowStartModal(true)} 
          />
        )}

        {currentView === 'live' && activeRunId && (
          <LiveRunView 
            runId={activeRunId} 
            onBack={() => setCurrentView('dashboard')} 
          />
        )}

        {currentView === 'workflows' && (
          <WorkflowEditor />
        )}
      </div>

      {/* Start Run Modal */}
      {showStartModal && (
        <StartRunModal 
          onClose={() => setShowStartModal(false)}
          onRunCreated={handleRunCreated}
        />
      )}
    </div>
  );
}
