import { Activity, ArrowRight, CircuitBoard, ClipboardList, FilePlus2, ScanLine } from 'lucide-react';
import type { Artifact, GuidedExample, ProfileInfo, WorkspaceStatus } from './types';

const steps = [
  {name: 'Import', icon: FilePlus2, description: 'Register an ONNX model and optional quantization encodings.'},
  {name: 'Profile', icon: Activity, description: 'Run ORT CPU or open a QAIRT capture.'},
  {name: 'Locate', icon: ScanLine, description: 'Rank modules and drill into source operators.'},
  {name: 'Diagnose', icon: CircuitBoard, description: 'Inspect measured events, tensor shapes, and mapping.'},
  {name: 'Optimize', icon: ClipboardList, description: 'Generate a Notebook task or compare two runs.'},
] as const;

export type Step = typeof steps[number]['name'];

export function deviceName(device: ProfileInfo['device']) {
  return [device.model || device.cpu, device.soc, device.os_version ? [device.os, device.os_version].filter(Boolean).join(' ') : device.os, device.arch]
    .filter(Boolean).join(' · ') || 'Device unavailable';
}

export function WorkspaceHome({model, profile, status, statusError, hotspot, openStep, openExample}: {
  model?: Artifact; profile?: ProfileInfo; status?: WorkspaceStatus; statusError?: string; hotspot?: string;
  openStep: (step: Step) => void; openExample: (example: GuidedExample) => void;
}) {
  const ready = [!!model, !!profile, !!profile?.operation_event_count, !!hotspot, !!hotspot && profile?.provenance !== 'fixture'];
  return <div className="home">
    <p className="home-intro">Find which model modules cost the most, inspect their evidence, then hand a focused experiment to Claude Code.</p>
    <section aria-labelledby="flow-title">
      <h2 id="flow-title">Analysis workflow</h2>
      <ol className="workflow-grid">{steps.map(({name, icon: Icon, description}, index) =>
        <li key={name}><button onClick={() => openStep(name)}>
          <Icon size={19}/><b>{name}</b><span>{description}</span>
          <small>{ready[index] ? index < 2 ? 'Loaded' : 'Ready' : index === 0 ? 'Start here' : 'Needs evidence'}</small>
          <ArrowRight size={15} className="workflow-arrow"/>
        </button></li>)}</ol>
    </section>
    <div className="home-lower">
      <section className="panel workspace-summary" aria-labelledby="selection-title">
        <h2 id="selection-title">Current analysis</h2>
        {model ? <><b>{model.name}</b><p>{profile ? `${profile.backend ?? 'Backend unavailable'} · ${profile.source} · ${profile.provenance}` :
          model.format === 'HTP_CONTEXT' ? `HTP Context · ${model.target_device ?? 'Target unavailable'}. Import its source ONNX to rank operators.` : 'A profile is needed to rank this model.'}</p>
          {profile && <p>{deviceName(profile.device)}</p>}</> : <p>Import an ONNX file or open a recorded experiment.</p>}
      </section>
      <section className="panel workspace-summary" aria-labelledby="guide-title">
        <h2 id="guide-title">Guided analysis</h2>
        <p>Open a recorded experiment and follow its measured latency to the top modules, original evidence, and Notebook task.</p>
        {statusError ? <p className="error" role="alert">{statusError}</p> : !status ? <p role="status">Looking up measured experiments…</p> : status.examples.length ?
          <div className="guide-actions">{status.examples.map(example => <button className="action" key={example.experiment_id} onClick={() => openExample(example)}>
            {example.backend === 'QNN HTP' ? 'Explore Android HTP recording' : example.device.os === 'Darwin' ? 'Explore Mac ORT recording' : 'Explore ORT CPU recording'} <ArrowRight size={14}/>
          </button>)}</div> : <p>Run <code>make demo</code> to generate a measured Tiny Transformer example.</p>}
      </section>
    </div>
  </div>;
}

export function Capabilities({status, error, showProfile}: {
  status?: WorkspaceStatus; error?: string; showProfile: (id: string) => void;
}) {
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!status) return <p role="status">Checking workspace capabilities…</p>;
  const captures = status.measured_captures;
  const ort = captures.find(item => item.backend === 'CPUExecutionProvider');
  const htp = captures.find(item => item.adapter === 'qnn-optrace-chrome-v2.50' && item.backend === 'QNN HTP') ?? captures.find(item => item.backend === 'QNN HTP');
  const rows = [
    ['Graph and quantization', 'Available', 'Import ONNX and AIMET encodings, or read QDQ directly from the graph.', undefined],
    ['ORT CPU', status.ort_cpu_available ? 'Available locally' : 'Runtime unavailable', 'Run a CPU benchmark and collect a separate operation trace.', ort?.id],
    ['Android QAIRT', htp ? 'Measured capture in workspace' : 'Requires QAIRT and an ADB device', 'The local Android CLI runs Basic, Detailed, Linting and Optrace. The Web app opens or imports their results.', htp?.id],
    ['HTP mapping', 'Evidence-dependent', 'Framework traces can connect HTP operations to source ONNX. Unmapped work stays Unknown.', undefined],
    ['Claude Code MCP', 'Local stdio', 'The project MCP config exposes evidence and Notebook plans. Approve the project server in your MCP client.', undefined],
    ['Linux / SSH capture', 'Planned', 'Import compatible exports from an external Qualcomm environment.', undefined],
  ];
  return <section className="panel capability-list" aria-label="System capabilities">{rows.map(([title, availability, description, profileId]) =>
    <div key={title}><h2>{title}</h2><b>{availability}</b><p>{description}</p>
      {profileId && <button className="action" onClick={() => showProfile(profileId)}>Open capture <ArrowRight size={14}/></button>}</div>)}</section>;
}
