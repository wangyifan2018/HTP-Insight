import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowDownToLine, ArrowRight, Box, ChevronDown, CircuitBoard, ClipboardList, Clock3, Cpu, FileJson, GitFork, House, Layers3, ScanLine, Search, Workflow } from 'lucide-react';
import type { Catalog, Evidence, EvidenceArtifact, Experiment, ExperimentPlan, Explanation, Graph, GuidedExample, Hotspot, Node, Profile, ProfileInfo, Tensor, TimeUnit, WorkspaceStatus } from './types';
import { Capabilities, WorkspaceHome, deviceName } from './workflow';
import type { Step } from './workflow';
import './style.css';

const views = { home: 'Workspace', graph: 'Graph Explorer', timeline: 'Profile Timeline', locate: 'Locate Hotspots', diagnosis: 'Diagnosis & Comparison', optimize: 'Notebook Adaptation', capabilities: 'System Status' } as const;
type View = keyof typeof views;
type Query = {view: View; model?: string; profile?: string; experiment?: string; node?: string; event?: string; hotspot?: string; level?: string; guide?: string};

function readQuery(): Query {
  const args = Object.fromEntries(new URLSearchParams(location.search));
  return { ...args, view: Object.hasOwn(views, args.view) ? args.view as View : 'home' };
}

async function api<T>(path: string, request?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, request);
  if (!response.ok) {
    const body = await response.json();
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
  }
  return response.json() as Promise<T>;
}

function useData<T>(path?: string) {
  const [state, setState] = useState<{path: string; value?: T; error?: string}>();
  useEffect(() => {
    if (!path) return;
    let active = true;
    api<T>(path).then(value => { if (active) setState({path, value}); })
      .catch(error => { if (active) setState({path, error: error.message}); });
    return () => { active = false; };
  }, [path]);
  return state?.path === path ? state : undefined;
}

const measure = (v?: number | null, unit: TimeUnit = 'us') => v == null ? 'Unavailable' : v.toLocaleString('en-US', {maximumFractionDigits: 2}) + (unit === 'cycles' ? ' cycles' : ' µs');
const us = (v?: number | null) => measure(v);
const hotspotCost = (row?: Hotspot) => row?.total_us ?? row?.total_cycles;

const percent = (v?: number | null) => v == null ? '—' : (v * 100).toFixed(1) + '%';
const moduleNames: Record<string, string> = {attention: 'Attention', mlp: 'MLP', input_projection: 'Input projection', output_projection: 'Output projection', residual_attn: 'Attention residual', residual_mlp: 'MLP residual', other: 'Other operators'};
function label(value: string) {
  const layer = value.match(/^layer\.(\d+)(?:\.(\w+))?$/);
  if (!layer) return moduleNames[value] ?? value;
  return `Layer ${layer[1]}` + (layer[2] ? ` · ${moduleNames[layer[2]] ?? layer[2]}` : '');
}
const short = (name: string) => name.split('/').filter(Boolean).slice(-2).join('/');
const tensorShape = (tensor: Tensor) => tensor.shape == null ? 'unknown shape' : tensor.shape.map(d => d ?? '?').join(' × ') || 'scalar';

function Panel({title, icon, actions, children, className = ''}: {title: string; icon?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string}) {
  return <section className={'panel ' + className}><div className="panel-head"><div>{icon}{title}</div>{actions}</div>{children}</section>;
}

function Stat({title, value, note}: {title: string; value: ReactNode; note?: string}) {
  return <div className="stat"><span>{title}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function GraphCanvas({nodes, selected, costs, select}: {nodes: Node[]; selected?: string; costs: Map<string, number>; select: (id: string) => void}) {
  const canvas = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const viewport = canvas.current;
    const target = viewport?.querySelector<HTMLButtonElement>('.graph-node.selected');
    if (!target || !viewport) return;
    const {offsetLeft, offsetTop, offsetWidth, offsetHeight} = target;
    if (offsetLeft < viewport.scrollLeft) viewport.scrollLeft = offsetLeft - 12;
    else if (offsetLeft + offsetWidth > viewport.scrollLeft + viewport.clientWidth)
      viewport.scrollLeft = offsetLeft + offsetWidth - viewport.clientWidth + 12;
    if (offsetTop < viewport.scrollTop) viewport.scrollTop = offsetTop - 12;
    else if (offsetTop + offsetHeight > viewport.scrollTop + viewport.clientHeight)
      viewport.scrollTop = offsetTop + offsetHeight - viewport.clientHeight + 12;
  }, [selected]);
  const positions = new Map<string, {x: number; y: number; col: number}>();
  const rowCount = new Map<number, number>();
  for (const node of nodes) {
    const prior = node.predecessors.map(id => positions.get(id)).filter(p => p !== undefined);
    const col = prior.length ? 1 + Math.max(...prior.map(p => p.col)) : 0;
    const row = rowCount.get(col) ?? 0;
    rowCount.set(col, row + 1);
    positions.set(node.id, {x: 24 + col * 150, y: 24 + row * 62, col});
  }
  const width = Math.max(0, ...[...positions.values()].map(p => p.x)) + 152;
  const height = Math.max(200, Math.max(0, ...[...positions.values()].map(p => p.y)) + 76);
  const peak = Math.max(1, ...costs.values());
  return <div className="canvas" ref={canvas} aria-label="ONNX dependency graph"><div className="canvas-inner" style={{width, height}}>
    <svg width={width} height={height} aria-hidden="true">
      {nodes.flatMap(node => node.predecessors.map(id => {
        const from = positions.get(id);
        const to = positions.get(node.id)!;
        if (!from) return null;
        const mid = (from.x + 122 + to.x) / 2;
        return <path key={id + ':' + node.id} className={selected === id || selected === node.id ? 'active-edge' : ''} d={`M ${from.x + 122},${from.y + 20} C ${mid},${from.y + 20} ${mid},${to.y + 20} ${to.x},${to.y + 20}`}/>;
      }))}
    </svg>
    {nodes.map(node => {
      const p = positions.get(node.id)!;
      return <button className={'graph-node ' + (selected === node.id ? 'selected' : '') + ((costs.get(node.id) ?? 0) > peak * .5 ? ' hot' : '')}
        data-node={node.id} key={node.id} style={{left:p.x, top:p.y}} onClick={() => select(node.id)}>
        <b>{node.op}</b><small>{node.id} · {short(node.name) || node.op}</small>
      </button>;
    })}
  </div></div>;
}

function GraphView({graph, query, profile, nodeRanks, moduleRanks, go}: {graph: Graph; query: Query; profile?: Profile; nodeRanks: Hotspot[]; moduleRanks: Hotspot[]; go: (q: Partial<Query>) => void}) {
  const [search, setSearch] = useState('');
  const [chosenModule, setModule] = useState<string>();
  const best = moduleRanks.find(item => graph.modules.some(mod => mod.id === item.id));
  const node = graph.nodes.find(n => n.id === query.node);
  const module = node?.module || (graph.modules.some(m => m.id === chosenModule) ? chosenModule : undefined) || best?.id || graph.modules[0]?.id;
  const local = graph.nodes.filter(n => n.module === module);
  const costs = new Map(nodeRanks.filter(row => row.node_ids.length === 1).flatMap(row => { const cost = hotspotCost(row); return cost == null ? [] : [[row.node_ids[0], cost] as const]; }));
  const picked = node || [...local].sort((a, b) => (costs.get(b.id) ?? -1) - (costs.get(a.id) ?? -1))[0];
  const match = nodeRanks.find(row => row.node_ids.length === 1 && row.node_ids[0] === picked?.id);
  const shared = nodeRanks.filter(row => row.node_ids.length > 1 && row.node_ids.includes(picked?.id ?? ''));
  const event = match?.evidence_ids[0] ?? shared[0]?.evidence_ids[0];
  const raw = useData<{raw: unknown}>(profile && event ? '/profiles/' + profile.id + '/events/' + event : undefined);
  const nodeIndex = new Map(graph.nodes.map(n => [n.id, n]));
  const groups = new Map<string, {id: string; nodeCount: number; shown: Node[]}[]>();
  const term = search.trim().toLowerCase();
  for (const mod of graph.modules) {
    const shown = mod.nodes.map(id => nodeIndex.get(id)!).filter(item => [mod.id, label(mod.id), item.id, item.op, item.name]
      .some(value => value.toLowerCase().includes(term)));
    if (!shown.length) continue;
    const entries = groups.get(mod.parent) ?? [];
    entries.push({id:mod.id, nodeCount:mod.nodes.length, shown});
    groups.set(mod.parent, entries);
  }
  const select = (id: string) => go({node: id});
  return <>
    <div className="stats">
      <Stat title="Graph nodes" value={graph.nodes.length} note={graph.architecture}/>
      <Stat title="Initializer elements" value={graph.initializer_elements.toLocaleString()} note={graph.inputs.map(t => graph.tensors[t].shape?.join(' × ') ?? t).join(' / ')}/>
      <Stat title="Quantization records" value={graph.quantization.length} note={graph.quantization.length ? [...new Set(graph.quantization.map(q => q.format))].join(', ') : 'No encodings attached'}/>
      <Stat title={profile?.provenance === "measured" ? "Top measured module" : "Top trace module"} value={best ? label(best.module) : 'Unavailable'} note={best && `${percent(best.share)} of operation duration`}/>
    </div>
    <div className="graph-source inline">
      <details><summary>Model inputs and outputs</summary><div className="inline">
        {([['Inputs', graph.inputs], ['Outputs', graph.outputs]] as const).map(([heading, names]) => <div className="model-io" key={heading}>
          <b>{heading}</b>{names.map(name => <p key={name}>{name} · {graph.tensors[name].dtype ?? 'Unknown'} · {tensorShape(graph.tensors[name])}</p>)}
        </div>)}
      </div></details>
      <button className="action" onClick={() => go({view:'timeline'})}>Profile this model <ArrowRight size={14}/></button>
    </div>
    <div className="graph-layout">
      <Panel title="Model hierarchy" icon={<Layers3 size={15}/>} className="tree">
        <label className="search"><Search size={15}/><input aria-label="Search modules or operators" placeholder="Find a module or operator" value={search} onChange={e => setSearch(e.target.value)}/></label>
        <div className="tree-root"><GitFork size={14}/>{graph.architecture}</div>
        <div className="tree-scroll">{!groups.size && <p className="detail quiet">No matching module or operator.</p>}
          {[...groups].map(([parent, entries]) => <div key={parent}>
            {parent !== graph.architecture && <div className="tree-layer">{label(parent)}</div>}
            {entries.map(mod => {
              const open = mod.id === module || Boolean(term);
              const hot = moduleRanks.find(item => item.id === mod.id);
              const name = parent === graph.architecture ? label(mod.id) : label(mod.id.split('.').at(-1) ?? mod.id);
              return <div key={mod.id}>
                <button className={mod.id === module ? 'module chosen' : 'module'} aria-expanded={open} onClick={() => {setModule(mod.id); go({node:undefined});}}>
                  <ChevronDown size={14} className={open ? '' : 'collapsed'}/><Box size={14}/><span>{name}</span><small>{hot ? percent(hot.share) : mod.nodeCount}</small>
                </button>
                {open && mod.shown.map(item => <button className={'tree-node ' + (picked?.id === item.id ? 'selected' : '')} key={item.id} onClick={() => select(item.id)}>
                  <span>{item.op}</span><small>{item.id}</small>
                </button>)}
              </div>;
            })}
          </div>)}
        </div>
      </Panel>
      <Panel title={label(module ?? 'Graph')} icon={<Workflow size={16}/>} className="workspace" actions={<span className="quiet">{local.length} operators</span>}>
        <GraphCanvas nodes={local} selected={picked?.id} costs={costs} select={select}/>
        <div className="panel-foot"><span><i className="legend blue"/> Operator</span><span><i className="legend gold"/> Higher trace duration</span></div>
      </Panel>
      <Panel title="Node inspector" icon={<ScanLine size={15}/>} className="inspector">
        {picked ? <div className="detail">
          <p className="tag">{picked.id} · {label(picked.module)}</p><h2>{picked.op}</h2><div className="code break">{picked.name || 'Unnamed node'}</div>
          <dl><dt>Operation duration</dt><dd>{measure(hotspotCost(match), match?.unit)}</dd><dt>Trace events</dt><dd>{match?.calls ?? 'Unavailable'}</dd></dl>
          {!!shared.length && <p className="quiet">Execution time shared across {shared.flatMap(item => item.node_ids).join(', ')}.</p>}
          <h3>Inputs and outputs</h3>
          {[...picked.inputs, ...picked.outputs].filter(Boolean).map((name, i) => {
            const t = graph.tensors[name];
            return <div className="tensor" key={name + i}><b title={name}>{short(name)}</b><span>{t.dtype ?? 'Unknown'} · {tensorShape(t)}</span></div>;
          })}
          {!!picked.predecessors.length && <div className="inline"><span className="quiet">Predecessors</span>{picked.predecessors.map(id => <button key={id} onClick={() => select(id)}>{id}</button>)}</div>}
          <h3>Quantization</h3>
          {picked.quantization.length ? picked.quantization.map(i => {
            const q = graph.quantization[i];
            return <div className="tensor" key={i}><b>{q.operation ?? q.format} · {q.dtype ?? 'Unknown dtype'}</b><span>{q.bitwidth ?? 'Unknown'} bits · {q.scale?.length ?? '—'} scale(s) · axis {q.axis ?? '—'}</span>
              {q.scale && <span>Scale {q.scale.slice(0, 3).map(v => v.toPrecision(4)).join(', ')}{q.scale.length > 3 ? ', …' : ''}</span>}
              {q.zero_point && <span>Zero point {q.zero_point.slice(0, 3).join(', ')}{q.zero_point.length > 3 ? ', …' : ''}</span>}</div>;
          }) : <p className="quiet">No encoding associated with this node.</p>}
          {event && <><button className="action wide" onClick={() => go({view:'timeline', node:picked.id, event})}>Locate in timeline <ArrowRight size={15}/></button>
            <details><summary>Original event</summary><code className="break">{event}</code><pre>{JSON.stringify(raw?.value?.raw, null, 2)}</pre></details></>}
        </div> : <p className="detail quiet">No graph node selected.</p>}
      </Panel>
    </div>
  </>;
}

function EvidenceFiles({items}: {items?: EvidenceArtifact[]}) {
  if (!items?.length) return null;
  return <div className="attached-evidence">{items.map(item => <div key={item.id} className="tensor">
    <a className="action" href={item.raw} title={item.filename}><ArrowDownToLine size={13}/>{item.artifact_type === 'HTP_GRAPH' ? 'HTP Graph JSON' : 'QHAS JSON'}</a>
    <span>{item.provenance}{item.summary.node_count != null && ` · ${item.summary.node_count} nodes · ${item.summary.tensor_count ?? '—'} tensors`}
      {item.summary.operation_count != null && ` · ${item.summary.operation_count} records`}</span>
    {item.summary.resources?.map((resource, index) => <span key={index}>
      {resource.type ?? 'Resource'} · {resource.utilization == null ? 'Utilization unavailable' : resource.utilization.toFixed(1) + '% utilization'}
    </span>)}
    {item.operation_records && <details><summary>Matched HTP operation</summary><pre>{JSON.stringify(item.operation_records, null, 2)}</pre></details>}
  </div>)}</div>;
}

function Timeline({profile, query, go}: {profile: Profile; query: Query; go: (q: Partial<Query>) => void}) {
  const [runId, setRun] = useState<string>();
  const timed = profile.events.filter((event): event is Evidence & {start:number; duration:number} =>
    event.start !== null && event.duration !== null);
  const runs = timed.filter(event => event.kind === 'inference');
  const selected = profile.events.find(event => event.id === query.event);
  const run = runs.find(row => row.id === (selected?.parent ?? runId)) ?? runs[0];
  const mappings = new Map<string, Set<string>>();
  for (const map of profile.mappings) {
    for (const op of map.operation_ids) {
      const ids = mappings.get(op) ?? new Set<string>();
      map.node_ids.forEach(id => ids.add(id));
      mappings.set(op, ids);
    }
  }
  const timelineEvents = timed.filter(row => row.kind !== 'inference');
  const events = timelineEvents.filter(row => !run || row.parent === run.id);
  const shown = events.length ? events : timelineEvents;
  const reference = selected ?? shown.find(row => mappings.get(row.operation ?? '')?.has(query.node ?? '')) ?? shown[0];
  const ids = [...(mappings.get(reference?.operation ?? '') ?? [])];
  const operation = reference?.operation;
  const proof = profile.mappings.find(mapping => mapping.evidence && operation
    && mapping.operation_ids.includes(operation))?.evidence;
  const min = run?.start ?? shown[0]?.start ?? 0;
  const max = run ? run.start + run.duration : Math.max(min + 1, ...shown.map(row => row.start + row.duration));
  const range = Math.max(1, max - min);
  const raw = useData<{raw: unknown; related_evidence: EvidenceArtifact[]}>(reference ? '/profiles/' + profile.id + '/events/' + reference.id : undefined);
  const tracks = new Map<string, typeof timed>();
  for (const row of shown) {
    const track = row.track || row.resource || 'Unspecified';
    const eventsOnTrack = tracks.get(track) ?? [];
    eventsOnTrack.push(row);
    tracks.set(track, eventsOnTrack);
  }
  return <>
    <div className="stats">
      {profile.unit === 'cycles' ? <>
        <Stat title={profile.source === 'Optrace' ? 'HTP operations' : 'Foreground operations'}
          value={shown.filter(row => row.kind === 'node').length}
          note={profile.source === 'Optrace' ? 'Unique measured events' : 'Viewer-averaged linting'}/>
        <Stat title="Reported resources" value={[...new Set(shown.flatMap(row => row.resource?.split(', ') ?? []))].join(' · ') || 'Unavailable'}/>
      </> : <>
        <Stat title="Latency p50" value={us(profile.latency_us?.p50)} note="Uninstrumented"/>
        <Stat title="Latency p95" value={us(profile.latency_us?.p95)} note="Uninstrumented"/>
      </>}
      <Stat title="Trace events" value={profile.event_count} note={profile.source + ' · ' + profile.provenance}/>
      <Stat title="Selected window" value={measure(range, profile.unit)} note={run ? 'Instrumented model_run' : profile.source === 'Optrace' && profile.unit === 'cycles' ? 'QAIRT Optrace' : profile.unit === 'cycles' ? 'QAIRT linting viewer' : 'Complete operation events'}/>
    </div>
    <div className="timeline-layout">
      <Panel title="Operation timeline" icon={<Activity size={16}/>} actions={<div className="inline">
        {!!runs.length && <select aria-label="Trace run" value={run?.id} onChange={e => {setRun(e.target.value); go({event:undefined, node:undefined});}}>
          {runs.map((row, i) => <option key={row.id} value={row.id}>Run {i+1}</option>)}
        </select>}<a className="action" href={profile.raw_trace}><ArrowDownToLine size={14}/> Raw trace</a></div>}>
        <div className="timeline-body">
          <div className="axis">{[0,.25,.5,.75,1].map(n => <span key={n}>{measure(n * range, profile.unit)}</span>)}</div>
          {[...tracks.entries()].map(([track, rows]) => <div className="track" key={track}>
            <div>{profile.source === 'ORT' ? 'CPU · ' : ''}{track}</div>
            <div className="track-bars">{rows.map(row => <button key={row.id} aria-label={row.name} data-event={row.id} title={row.name + ' · ' + measure(row.duration, row.unit)}
              className={row.id === reference?.id ? 'active' : ''} style={{left: Math.max(0, (row.start-min)/range*100) + '%', width: row.duration/range*100 + '%'}}
              onClick={() => go({event:row.id, node:[...(mappings.get(row.operation ?? '') ?? [])][0]})}/>)}</div>
          </div>)}
          <div className="event-list"><table><thead><tr><th>Operation order</th><th>Offset</th><th>Duration</th></tr></thead>
            <tbody>{shown.map(row => <tr key={row.id} className={row.id === reference?.id ? 'current' : ''}>
              <td><button aria-pressed={row.id === reference?.id} onClick={() => go({event:row.id, node:[...(mappings.get(row.operation ?? '') ?? [])][0]})}>{short(row.name.replace(/_kernel_time$/, ''))}</button></td>
              <td>{measure(row.start-min, row.unit)}</td><td>{measure(row.duration, row.unit)}</td>
            </tr>)}</tbody></table></div>
        </div>
      </Panel>
      <Panel title="Event inspector" icon={<Clock3 size={15}/>}>
        {reference && <div className="detail"><p className="tag">{profile.source} · {profile.provenance}</p>
          <h2>{short(reference.name).replace(/_kernel_time$/, '')}</h2>
          <dl><dt>Duration</dt><dd>{measure(reference.duration, reference.unit)}</dd>{reference.resource && <><dt>Resources</dt><dd>{reference.resource}</dd></>}<dt>Raw index</dt><dd>{reference.raw_index}</dd><dt>Mapped nodes</dt><dd>{ids.join(', ') || 'Unknown'}</dd></dl>
          {proof && <details open><summary>Compiler mapping evidence</summary><p>{proof.method}</p>
            <dl className="mapping-fields"><dt>QNN operation</dt><dd className="break">{proof.qnn_op_name}</dd>
              <dt>Source ONNX</dt><dd className="break">{proof.source_onnx_names.join(', ')}</dd>
              <dt>Framework CSV SHA-256</dt><dd className="break">{proof.framework_csv_sha256}</dd></dl></details>}
          {ids.map(id => <button className="action wide" key={id} onClick={() => go({view:'graph', node:id})}>Locate {id} in graph <ArrowRight size={15}/></button>)}
          <EvidenceFiles items={raw?.value?.related_evidence}/>
          <details><summary>Original event</summary><code className="break">{reference.id}</code><pre>{JSON.stringify(raw?.value?.raw, null, 2)}</pre></details>
        </div>}
      </Panel>
    </div>
    {!!profile.evidence?.length && <div className="profile-attachments"><Panel title="QAIRT artifacts" icon={<FileJson size={15}/>}>
      <div className="detail"><EvidenceFiles items={profile.evidence}/></div>
    </Panel></div>}
  </>;
}

function CsvProfile({profile, query, go}: {profile: Profile; query: Query; go: (q: Partial<Query>) => void}) {
  const hasInference = profile.events.some(row => row.kind === 'inference');
  const hasCycles = profile.events.some(row => row.kind === 'node');
  const [kind, setKind] = useState(hasInference ? 'inference' : 'node');
  const requested = profile.events.find(row => row.id === query.event);
  const recordKind = requested?.kind ?? kind;
  const visible = profile.events.filter(row => row.kind === recordKind);
  const selected = requested ?? visible[0];
  const raw = useData<{raw: unknown}>(selected ? '/profiles/' + profile.id + '/events/' + selected.id : undefined);
  const nodeIds = profile.mappings.filter(map => selected?.operation && map.operation_ids.includes(selected.operation))
    .flatMap(map => map.node_ids);
  return <>
    <div className="stats">
      <Stat title="NetRun graph p50" value={us(profile.latency_us?.p50)} note="QAIRT CSV"/>
      <Stat title="NetRun graph p95" value={us(profile.latency_us?.p95)} note="QAIRT CSV"/>
      <Stat title="Retained executions" value={String(profile.conditions.repeats ?? 'Unavailable')}/>
      <Stat title="QAIRT viewer" value={profile.profiler_version ?? 'Unavailable'}/>
    </div>
    <div className="timeline-layout">
      <Panel title="QAIRT Profile Records" icon={<Activity size={16}/>} actions={<div className="inline">
        <select aria-label="Record type" value={recordKind} onChange={e => {setKind(e.target.value); go({event:undefined});}}>
          {hasInference && <option value="inference">NetRun graph executions</option>}
          {hasCycles && <option value="node">HTP operation cycles</option>}
        </select>
        <a className="action" href={profile.raw_trace}><ArrowDownToLine size={14}/> Raw CSV</a></div>}>
        <div className="timeline-body">
          <p className="quiet">CSV message timestamps are shown as recorded. Operation start times are unavailable.</p>
          <div className="event-list"><table><thead><tr><th>Record</th><th>Message timestamp</th><th>Reported value</th></tr></thead>
            <tbody>{visible.map(row => <tr key={row.id} className={selected?.id === row.id ? 'current' : ''}>
              <td><button onClick={() => go({event:row.id})}>{row.name}</button></td>
              <td>{us(row.recorded_timestamp_us)}</td><td>{measure(row.duration, row.unit)}</td>
            </tr>)}</tbody></table></div>
        </div>
      </Panel>
      <Panel title="Raw CSV record" icon={<FileJson size={16}/>}>
        <div className="detail">
          {selected && <><code className="break">{selected.id}</code><pre>{JSON.stringify(raw?.value?.raw, null, 2)}</pre></>}
          {nodeIds.map(id => <button className="action wide" key={id} onClick={() => go({view:'graph',node:id})}>Locate {id} in graph <ArrowRight size={15}/></button>)}
        </div>
      </Panel>
    </div>
  </>;
}

function Comparison({exp}: {exp: Experiment}) {
  const p50 = exp.latency.p50.delta_pct;
  const p95 = exp.latency.p95.delta_pct;
  const verdict = p50 == null || p95 == null ? 'Latency change unavailable' : p50 < 0 && p95 < 0 ? 'Both latency percentiles decreased' :
    p50 > 0 && p95 > 0 ? 'Both latency percentiles increased' : p50 === 0 && p95 === 0 ? 'No change in either percentile' : 'The percentiles changed differently';
  return <Panel title="Baseline / Candidate" icon={<GitFork size={16}/>} actions={<div className="inline">
    <a className="action" href={'/api/experiments/' + exp.id + '?format=md'}><ArrowDownToLine size={13}/> Markdown</a>
    <a className="action" href={'/api/experiments/' + exp.id + '?format=json'}><FileJson size={13}/> JSON</a></div>}>
    <div className="detail"><p className="quiet">{exp.hypothesis || 'No hypothesis supplied.'}</p>
      <div className="comparison-metrics">{(['p50','p95'] as const).map(metric => {
        const m = exp.latency[metric];
        return <div key={metric}><small>{metric.toUpperCase()} · {exp.latency.label ?? 'UNINSTRUMENTED'}</small><h2>{us(m.baseline)} <span>→</span> {us(m.candidate)}</h2>
          {m.delta_pct != null && <b className={m.delta_pct > 0 ? 'slower' : 'faster'}>{m.delta_pct > 0 ? '+' : ''}{m.delta_pct.toFixed(2)}%</b>}</div>;
      })}</div>
      <p className="quiet" title="Observed direction for this capture. Use repeated paired runs to establish a stable performance change.">{verdict}</p>
      <dl><dt>Output validation</dt><dd>{exp.numeric ? exp.numeric.passed ? 'Passed' : 'Failed' : 'Unavailable'}</dd>
        <dt>Graph nodes</dt><dd>{exp.graph_diff.baseline_nodes} → {exp.graph_diff.candidate_nodes}</dd>
        {exp.graph_diff.edges_added && <><dt>Graph edges</dt><dd>+{exp.graph_diff.edges_added.length} / −{exp.graph_diff.edges_removed?.length ?? 0}</dd></>}
        {Object.entries(exp.numeric?.outputs ?? {}).map(([name, output]) => <div className="dl-row" key={name}><dt>{name} max |Δ|</dt><dd>{output.max_abs ?? 'Unavailable'}</dd></div>)}
      </dl>
      <p className="quiet">{exp.sources.baseline.filter(Boolean).join(' · ')} → {exp.sources.candidate.filter(Boolean).join(' · ')}</p>
      {exp.numeric?.error && <p className="error">{exp.numeric.error}</p>}
      {!exp.latency.comparable && <div className="quiet"><p>Matched latency change unavailable.</p>
        {!!exp.latency.comparison_issues?.length && <ul>{exp.latency.comparison_issues.map(issue =>
          <li key={issue.field}>{issue.field.replaceAll('_', ' ')} · {issue.problem}</li>)}</ul>}</div>}
      <details><summary>Module trace differences ({exp.trace_runs.baseline ?? '—'} / {exp.trace_runs.candidate ?? '—'} runs)</summary>
        <table><thead><tr><th>Module</th><th>Baseline</th><th>Candidate</th></tr></thead><tbody>{exp.module_costs.map(row =>
          <tr key={row.module}><td>{label(row.module)}</td><td>{row.baseline_cycles == null ? us(row.baseline_us) : measure(row.baseline_cycles, 'cycles')}</td>
          <td>{row.candidate_cycles == null ? us(row.candidate_us) : measure(row.candidate_cycles, 'cycles')}</td></tr>)}</tbody></table>
      </details>
      <details><summary>Operator count changes</summary>{exp.graph_diff.operator_changes.map(row =>
        <p className="quiet" key={row.module + row.domain + row.op}>{label(row.module)} · {row.op} · {row.baseline} → {row.candidate}</p>)}</details>
    </div>
  </Panel>;
}

function HotspotRanking({profile, hotspots, active, level, go}: {
  profile?: Profile; hotspots: Hotspot[]; active?: Hotspot; level: string; go: (query: Partial<Query>) => void;
}) {
  return <Panel title="Top hotspots" icon={<Activity size={15}/>} actions={<select aria-label="Hotspot level" value={level} onChange={e => go({level:e.target.value, hotspot:undefined})}>
    <option value="module">By module</option><option value="node">{profile?.unit === 'cycles' ? 'By operation' : 'By node'}</option></select>}>
    {hotspots.length ? <div className="ranking">{hotspots.map(row => <button key={row.id} className={active?.id === row.id ? 'active' : ''}
      aria-pressed={active?.id === row.id} onClick={() => go({hotspot:row.id})}>
      <span>{level === 'node' ? (profile?.unit === 'cycles' ? row.label : `${row.id} · ${row.label}`) : label(row.module)}</span>
      <span className="rankbar"><i style={{width:row.share == null ? '0%' : percent(row.share)}}/></span>
      <b>{measure(hotspotCost(row), row.unit)}</b><small>{percent(row.share)}</small>
    </button>)}<p className="quiet" title="Shares use this trace's operation-duration sum. Overlapping work and Unknown may contribute.">{hotspots[0].scope}</p></div> :
      <p className="detail quiet">{profile ? 'This profile has no operation events for ranking. Capture ORT Trace, QAIRT Detailed, Linting or Optrace.' : 'Select or import a profile.'}</p>}
  </Panel>;
}

function HotspotStructure({explain, go}: {explain: Explanation; go: (query: Partial<Query>) => void}) {
  function showNodes(nodes: Explanation['nodes']) {
    return nodes.map(node => <div className="tensor" key={node.id}>
      <b title={node.name}>{node.op} · {short(node.name)}</b>
      <span>{node.input_tensors.map(t => `${t.dtype ?? '?'} ${tensorShape(t)}`).join(' / ')} → {node.output_tensors.map(t => `${t.dtype ?? '?'} ${tensorShape(t)}`).join(' / ')}</span>
      <span>{[...new Set(node.quantization_details.map(q => `${q.format} ${q.bitwidth ?? '?'}-bit`))].join(', ') || 'Encoding unavailable'}</span>
      <button className="action self-start" onClick={() => go({view:'graph',node:node.id})}>Open {node.id} in graph <ArrowRight size={14}/></button>
    </div>);
  }
  return <div className="detail source-structure">
    <p><b>Inferred mapping</b> · {explain.mapping_methods.join(', ') || 'Unknown'}</p>
    {!explain.nodes.length && <p className="quiet">This event has no reliable source attribution. It remains in the trace totals.</p>}
    {showNodes(explain.nodes.slice(0, 5))}
    {explain.nodes.length > 5 && <details><summary>Show all {explain.nodes.length} mapped nodes</summary>{showNodes(explain.nodes.slice(5))}</details>}
  </div>;
}

function Diagnosis({profile, experiment, hotspots, query, go, compare}: {profile?: Profile; experiment?: Experiment; hotspots: Hotspot[]; query: Query; go:(q:Partial<Query>)=>void; compare: () => void}) {
  const active = query.hotspot ? hotspots.find(row => row.id === query.hotspot) : hotspots[0];
  const hotspotId = query.hotspot ?? active?.id;
  const level = query.level === 'node' ? 'node' : 'module';
  const detail = useData<Explanation>(profile && hotspotId ? '/profiles/' + profile.id + '/hotspots/' + encodeURIComponent(hotspotId) + '?level=' + level : undefined);
  const explain = detail?.value;
  const locate = query.view === 'locate';
  return <div className="diagnosis-layout">
    <div className="stack">
      <HotspotRanking profile={profile} hotspots={hotspots} active={active} level={level} go={go}/>
      {detail?.error && <p className="error" role="alert">{detail.error}</p>}
      {hotspotId && !detail && <p className="quiet" role="status">Loading hotspot evidence…</p>}
      {explain && !locate && <Panel title="Optimization hypothesis" icon={<CircuitBoard size={14}/>}>
        <div className="detail"><h2>{label(explain.module)}</h2><p className="tag">Hypothesis</p><p>{explain.experiment_hint?.mechanism ?? explain.hypothesis.mechanism}</p>
          <p>{explain.experiment_hint?.change ?? explain.hypothesis.adaptation}</p><h3>Verification</h3><ul>{explain.hypothesis.metrics.map(metric => <li key={metric}>{metric}</li>)}</ul>
          <p className="quiet">{explain.experiment_hint?.risk ?? explain.hypothesis.risk}</p>
          {profile?.provenance === 'fixture' ? <p className="quiet">Load a real capture to generate a Notebook task.</p> :
            <button className="action primary" onClick={() => go({view:'optimize',hotspot:explain.id,level})}>Generate Claude Code Experiment Plan <ArrowRight size={14}/></button>}
        </div>
      </Panel>}
    </div>
    <div className="stack">
      {explain && <Panel title={locate ? 'Source structure' : 'Evidence and source structure'} icon={<ScanLine size={15}/>}
        actions={locate && <button className="action" onClick={() => go({view:'diagnosis',hotspot:explain.id,level})}>Diagnose hotspot <ArrowRight size={14}/></button>}>
        {!locate && <div className="detail observed">
          <p className="tag">{explain.provenance === 'measured' ? 'Measured' : explain.provenance === 'fixture' ? 'Fixture' : 'Imported'} · {explain.calls} operation events</p>
          <p><b>{measure(hotspotCost(explain), explain.unit)}</b> · {percent(explain.share)} of the displayed operation scope</p>
          <p>{explain.example_evidence.name} · {measure(explain.example_evidence.duration, explain.example_evidence.unit)}{explain.example_evidence.resource && ` · ${explain.example_evidence.resource}`}</p>
          <button className="action" onClick={() => go({view:'timeline', event:explain.example_evidence.id, node:explain.node_ids[0]})}>Open trace evidence <ArrowRight size={14}/></button>
          <EvidenceFiles items={explain.related_evidence}/>
        </div>}
        <HotspotStructure explain={explain} go={go}/>
      </Panel>}
      {!locate && (experiment ? <Comparison exp={experiment}/> :
        <Panel title="Baseline / Candidate" icon={<GitFork size={15}/>} actions={profile && <button className="action" onClick={compare}>Create comparison</button>}>
          <p className="detail quiet">Select or create an experiment.</p></Panel>)}
    </div>
  </div>;
}

function CaptureSummary({profile, canRun, run, importTrace, locate}: {profile?: ProfileInfo; canRun: boolean; run: () => void; importTrace: () => void; locate: () => void}) {
  const latency = profile?.latency_us;
  const settings = profile?.conditions;
  const count = settings?.repeats ?? latency?.count;
  const setting = (value: unknown) => typeof value === 'number' || typeof value === 'string' ? String(value) : 'Unavailable';
  return <section className="panel capture-summary" aria-label="Profile measurement summary">
    <div className="capture-header"><div><h2>Performance capture</h2>
      {profile ? <p>{profile.backend ?? 'Backend unavailable'} · {deviceName(profile.device)} · {profile.provenance}</p> : <p>Select a source model or import a compatible capture.</p>}
      </div><div className="inline">
        <button className="action" disabled={!canRun} onClick={run} title={canRun ? undefined : 'Select an ONNX model and make sure the local ORT runtime is available.'}>Run ORT CPU Profile</button>
        <button className="action" onClick={importTrace}>Import QNN Profile</button>
        {!!profile?.operation_event_count && <button className="action primary" onClick={locate}>Locate hotspots <ArrowRight size={14}/></button>}
      </div></div>
    {profile && <div className="capture-metrics">
      <div><small>Graph p50</small><strong>{us(latency?.p50)}</strong></div>
      <div><small>Graph p95</small><strong>{us(latency?.p95)}</strong></div>
      <div><small>Retained timing samples</small><strong>{setting(count)}</strong></div>
      <div><small>Warmup</small><strong>{setting(settings?.warmup)}</strong></div>
    </div>}
    {profile && <p className="quiet">{profile.source} · {profile.profiler_version ?? 'Profiler version unavailable'} · {latency?.label ?? latency?.scope ?? 'Graph timing unavailable for this capture'}</p>}
    {profile?.operation_event_count === 0 && <p className="quiet">This capture has graph timing only. Import a capture with operation events to rank hotspots.</p>}
    <details><summary>Profiling overhead and HTP terminology</summary><p className="quiet">
      {profile?.backend === 'QNN HTP' ? 'A Basic capture measures NetRun graph execution. Linting or Optrace exposes operation work and optional HMX, HVX, and DMA tracks. HMX handles matrix operations, HVX handles vector operations, and DMA moves data. VTCM is on-chip memory. Compare the same profiling mode and keep overlapping work, waits, and critical-path metrics separate.' :
        'ORT CPU latency is sampled without tracing. The separate instrumented trace describes operator execution, including any overlap. Its operation sum has a different scope from a session.run latency sample.'}
    </p></details>
    {profile?.backend === 'QNN HTP' && !!profile.operation_event_count && <details><summary>Matrix shape and hardware layout</summary>
      <p className="quiet">GEMV multiplies a matrix by a vector. GEMM multiplies two matrices. Tensor shape and tiling affect how work is arranged on the device. A source MatMul can include compiled layout work. Check the mapped hardware operations before assigning a cause.</p></details>}
    <details><summary>Run a capture on Android HTP</summary><p className="quiet">Use the local Android runner with a compatible QAIRT SDK, authorized ADB device, DLC or Context and raw inputs.</p>
      <code>.venv/bin/python -m scripts.run_android_qnn --help</code></details>
  </section>;
}

function NotebookPlan({profile, hotspotId, level, back}: {profile: ProfileInfo; hotspotId: string; level: string; back: () => void}) {
  const download = `/profiles/${profile.id}/hotspots/${encodeURIComponent(hotspotId)}/plan?level=${level}`;
  const request = useData<ExperimentPlan>(profile.provenance !== 'fixture' ? download : undefined);
  const [copyStatus, setCopyStatus] = useState('');
  const plan = request?.value;
  async function copy() {
    if (!plan) return;
    try {
      await navigator.clipboard.writeText(plan.markdown);
      setCopyStatus('Markdown copied.');
    } catch {
      setCopyStatus('Clipboard access unavailable. Download Markdown below.');
    }
  }
  return <Panel title="Claude Code Experiment Plan" icon={<ClipboardList size={16}/>} actions={<button className="action" onClick={back}>Back to diagnosis</button>}>
    <div className="detail plan-body">
      {profile.provenance === 'fixture' ? <p>Load a real capture to generate a Notebook task.</p> : request?.error ?
        <p className="error" role="alert">{request.error}</p> : !plan ? <p role="status">Generating task from selected evidence…</p> : <>
          <p className="tag">{profile.provenance === 'measured' ? 'Measured source' : 'Imported source'} · {label(plan.hotspot.module)}</p>
          <p>{plan.adaptation.change}</p>
          <div className="inline plan-actions">
            <button className="action primary" onClick={copy}>Copy Markdown</button>
            <a className="action" href={'/api' + download + '&format=md'}><ArrowDownToLine size={14}/> Markdown</a>
            <a className="action" href={'/api' + download + '&format=json'}><ArrowDownToLine size={14}/> JSON</a>
            <span className="quiet" role="status">{copyStatus}</span>
          </div>
          <pre tabIndex={0} className="plan-text" aria-label="Notebook task Markdown">{plan.markdown}</pre>
        </>}
    </div>
  </Panel>;
}

type Action = 'import_model' | 'import_profile' | 'import_evidence' | 'run_ort_profile' | 'compare_experiments';
type DialogOptions = {action: Action; traceFormat?: string};

function ImportDialog({catalog, modelId, profileId, options, close, done}: {catalog: Catalog; modelId?: string; profileId?: string; options: DialogOptions; close:()=>void; done:(q:Partial<Query>)=>void}) {
  const [action, setAction] = useState<Action>(options.action);
  const [traceFormat, setTraceFormat] = useState(options.traceFormat ?? 'ort-chrome-v1');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fields = new FormData(e.currentTarget);
    const args = Object.fromEntries([...fields].filter(([,value]) => value !== ''));
    const body: Record<string, unknown> = {...args};
    if (args.fixture) body.fixture = true;
    setBusy(true);
    setStatus('');
    try {
      for (const field of ['warmup', 'repeats', 'trace_runs']) if (args[field] !== undefined) body[field] = Number(args[field]);
      for (const field of ['device', 'conditions', 'compatibility']) if (typeof args[field] === 'string') body[field] = JSON.parse(args[field]);
      const result = await api<{id?:string; profile_id?:string; model_id?:string; artifact?:{id:string; format:string}}>('/tools/' + action, {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
      });
      if (action === 'import_model') done({view:result.artifact?.format === 'HTP_CONTEXT' ? 'home' : 'graph', model:result.artifact?.id, profile:undefined});
      else if (action === 'import_evidence') done({view:'timeline', profile:result.profile_id, model:undefined});
      else if (action === 'compare_experiments') done({view:'diagnosis', experiment:result.id, profile:String(args.baseline), model:undefined});
      else done({view:'timeline', profile:result.id, model:result.model_id});
      close();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  const optionLabel = (id: string) => catalog.models.find(model => model.id === id)?.name ?? id;
  return <div className="overlay"><div className="dialog" role="dialog" aria-modal="true" aria-label="Manage local evidence" onKeyDown={e => {if (e.key === 'Escape') close();}}>
    <div className="panel-head"><div><FileJson size={16}/> Manage local evidence</div><button className="action" onClick={close}>Close</button></div>
    <form className="detail" onSubmit={submit}>
      <label>Action<select autoFocus value={action} onChange={e => {setAction(e.target.value as Action); setStatus('');}}>
        <option value="import_profile">Import a profile trace</option><option value="import_evidence">Attach QHAS or HTP Graph</option><option value="import_model">Register ONNX or HTP Context</option>
        <option value="run_ort_profile">Run ORT CPU profiling</option><option value="compare_experiments">Compare two profiles</option>
      </select></label>
      {(action === 'import_profile' || action === 'run_ort_profile') && <label>Model<select required name="model_id" defaultValue={modelId}>
        {catalog.models.filter(x => x.format === 'ONNX').map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
      </select></label>}
      {(action === 'import_model' || action === 'import_profile' || action === 'import_evidence') && <label>Path relative to runs/inbox<input key={action} name="filename" required placeholder={action === 'import_model' ? 'model.onnx' : traceFormat === 'qnn-viewer-csv-v2.50' ? 'profile.csv' : 'profile.json'}/></label>}
      {action === 'import_model' && <>
        <label>Display name (optional)<input name="name" placeholder="Model name"/></label>
        <label>AIMET encodings for ONNX (optional)<input name="encodings" placeholder="model.encodings"/></label>
        <details><summary>HTP Context compatibility</summary><div className="input-fields">
          <p className="quiet">Register a .bin to record its identity and target. Import its source ONNX separately to browse graph nodes.</p>
          <label>Target device (optional)<input name="target_device" placeholder="SM6650"/></label>
          <label>Compatibility JSON (optional)<input name="compatibility" placeholder={'{"hexagon":"V73"}'}/></label>
        </div></details>
      </>}
      {action === 'import_profile' && <>
        <label>Trace format<select name="format" value={traceFormat} onChange={e => setTraceFormat(e.target.value)}><option value="ort-chrome-v1">ORT Chrome Trace</option><option value="qnn-viewer-csv-v2.50">QAIRT 2.50 Basic / Detailed CSV</option><option value="optrace-chrome-v1">Optrace converted Chrome Trace</option><option value="qnn-linting-chrome-v2.50">QAIRT 2.50 HTP Linting Trace</option><option value="qnn-optrace-chrome-v2.50">QAIRT 2.50 HTP Optrace</option></select></label>
        {traceFormat === 'qnn-optrace-chrome-v2.50' ?
          <label>DLC framework trace CSV (optional)<input name="framework_csv" placeholder="compiled-graph.csv"/></label> :
          <label>Operation mapping path (optional)<input name="mapping_file" placeholder="mapping.json"/></label>}
        <label className="checkbox"><input type="checkbox" name="fixture"/> Fixture data</label>
        <details><summary>Capture metadata</summary><div className="input-fields">
          <label>Backend (optional)<input name="backend" placeholder="QNN HTP"/></label>
          <label>Profiler version (optional)<input name="profiler_version" placeholder="QAIRT runtime build"/></label>
          <label>Device JSON (optional)<input name="device" placeholder={'{"soc":"SM6650"}'}/></label>
          <label>Conditions JSON (optional)<input name="conditions" placeholder={'{"warmup":10}'}/></label>
        </div></details>
      </>}
      {action === 'import_evidence' && <>
        <label>Profile<select name="profile_id" required defaultValue={profileId}>
          {catalog.profiles.map(p => <option key={p.id} value={p.id}>{optionLabel(p.model_id)} · {p.id.slice(-8)}</option>)}
        </select></label>
        <label>Artifact format<select name="format"><option value="qhas-v1.0">QAIRT QHAS 1.0</option>
          <option value="htp-graph-v1.0">QAIRT HTP Graph 1.0</option></select></label>
        <label>Provenance<select name="provenance"><option value="imported">Imported</option>
          <option value="estimated">Estimated</option><option value="fixture">Fixture</option></select></label>
      </>}
      {action === 'run_ort_profile' && <>
        <label>Input NPZ path relative to runs/inbox<input name="inputs" required placeholder="inputs.npz"/></label>
        <details><summary>ORT sampling settings</summary><div className="input-fields count-fields">
          <label>Warmup<input name="warmup" type="number" defaultValue={30} min={1} max={100} required/></label>
          <label>Timing samples<input name="repeats" type="number" defaultValue={200} min={2} max={1000} required/></label>
          <label>Trace runs<input name="trace_runs" type="number" defaultValue={5} min={1} max={20} required/></label>
        </div></details>
      </>}
      {action === 'compare_experiments' && <>
        {(['baseline','candidate'] as const).map(key => <label key={key}>{key === 'baseline' ? 'Baseline' : 'Candidate'}<select name={key} required defaultValue={key === 'baseline' ? profileId : undefined}>
          {catalog.profiles.map(p => <option key={p.id} value={p.id}>{optionLabel(p.model_id)} · {p.id.slice(-8)}</option>)}
        </select></label>)}
        <label>Hypothesis (optional)<input name="hypothesis"/></label>
      </>}
      {status && <p role="alert" className="error">{status}</p>}
      <button className="action primary" type="submit" disabled={busy}>{busy ? 'Working…' : 'Run action'}<ArrowRight size={15}/></button>
    </form>
  </div></div>;
}

const navigation = [
  ['home', House], ['graph', Workflow], ['timeline', Activity], ['locate', ScanLine],
  ['diagnosis', GitFork], ['optimize', ClipboardList], ['capabilities', Cpu],
] as const;

function App() {
  const [query, setQuery] = useState(readQuery);
  const [revision, setRevision] = useState(0);
  const [dialog, setDialog] = useState<DialogOptions>();
  useEffect(() => {
    const handler = () => setQuery(readQuery());
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, []);
  function go(update: Partial<Query>) {
    const next = {...query, ...update};
    const params = new URLSearchParams();
    Object.entries(next).forEach(([key,value]) => {if (value) params.set(key, value);});
    history.pushState({}, '', '/?' + params);
    setQuery(next);
  }
  const catalogRequest = useData<Catalog>('/catalog?revision=' + revision);
  const catalog = catalogRequest?.value;
  const home = query.view === 'home';
  const capabilities = query.view === 'capabilities';
  const expert = !home && !capabilities;
  const statusRequest = useData<WorkspaceStatus>(expert && query.view !== 'timeline' ? undefined : '/capabilities?revision=' + revision);
  const experiment = catalog?.experiments.find(e => e.id === query.experiment);
  const defaultProfile = expert ? catalog?.profiles.find(p => p.id === (experiment ?? catalog.experiments[0])?.baseline) ?? catalog?.profiles[0] : undefined;
  const chosenProfile = query.profile ? catalog?.profiles.find(p => p.id === query.profile) :
    query.model ? catalog?.profiles.find(p => p.model_id === query.model) : defaultProfile;
  const modelId = chosenProfile?.model_id ?? query.model ?? (expert ? catalog?.models.find(m => m.format === 'ONNX')?.id : undefined);
  const profileId = query.profile ?? chosenProfile?.id;
  const model = catalog?.models.find(m => m.id === modelId);
  const comparison = query.experiment ? experiment : catalog?.experiments.find(row => row.baseline === profileId || row.candidate === profileId);
  const hasRank = query.view === 'locate' || query.view === 'diagnosis' || query.view === 'optimize';
  const level = query.level === 'node' ? 'node' : 'module';
  const graphRequest = useData<Graph>(modelId && model?.format === 'ONNX' && query.view === 'graph' ? '/models/' + modelId + '/graph' : undefined);
  const profileRequest = useData<Profile>(profileId && expert && query.view !== 'optimize' ? '/profiles/' + profileId : undefined);
  const nodeRequest = useData<{hotspots:Hotspot[]}>(profileId && (query.view === 'graph' || (hasRank && level === 'node')) ? '/profiles/' + profileId + '/hotspots?level=node&limit=' + (query.view === 'graph' ? '10000' : '10') : undefined);
  const moduleRequest = useData<{hotspots:Hotspot[]}>(profileId && (query.view === 'graph' || (hasRank && level === 'module')) ? '/profiles/' + profileId + '/hotspots?level=module&limit=10' : undefined);
  const rankingRequest = level === 'node' ? nodeRequest : moduleRequest;
  const hotspots = rankingRequest?.value?.hotspots ?? [];
  const selectedId = query.hotspot ?? hotspots[0]?.id;
  const graph = graphRequest?.value;
  const profile = profileRequest?.value;
  const modelChoices = useMemo(() => catalog?.models.filter(item => item.format === 'ONNX') ?? [], [catalog]);
  const error = catalogRequest?.error || graphRequest?.error || profileRequest?.error || nodeRequest?.error || moduleRequest?.error;

  function openStep(step: Step) {
    if (step === 'Import') setDialog({action:'import_model'});
    else go({view:{Profile:'timeline', Locate:'locate', Diagnose:'diagnosis', Optimize:'optimize'}[step] as View});
  }

  function openExample(example: GuidedExample) {
    go({view:'timeline',model:example.model_id,profile:example.profile_id,experiment:example.experiment_id,
      node:undefined,event:undefined,hotspot:undefined,level:'module',guide:'true'});
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div><CircuitBoard size={23}/></div><span>HTP Insight<small>Runtime diagnostics</small></span></div>
      <nav aria-label="Analysis views">
        {navigation.map(([view, Icon]) => <button key={view} aria-current={query.view === view ? 'page' : undefined} onClick={() => go({view})}>
          <Icon size={16}/>{views[view]}</button>)}
      </nav>
      <div className="sidebar-foot"><Cpu size={17}/><span>Local workspace{chosenProfile?.backend && <small>{chosenProfile.backend}</small>}</span></div>
    </aside>
    <main>
      <header className="top"><div>{!home && <span className="crumb">Workspace <span>/</span> {views[query.view]}</span>}<h1>{views[query.view]}</h1></div>
        <button className="action import" disabled={!catalog} onClick={() => setDialog({action:'import_profile'})}><FileJson size={15}/> Manage evidence</button></header>
      {expert && <div className="context">
        {query.view === 'diagnosis' && !!catalog?.experiments.length && <label>Experiment<select value={comparison?.id ?? ''} onChange={e => {
          const selected = catalog.experiments.find(item => item.id === e.target.value);
          if (selected) go({experiment:selected.id, profile:selected.baseline, model:undefined, hotspot:undefined, node:undefined, event:undefined, guide:undefined});
        }}>
          {!comparison && <option value="" disabled>Select an experiment</option>}
          {catalog.experiments.map(e => <option key={e.id} value={e.id}>{e.id.slice(-8)} · {catalog.models.find(m => m.id === catalog.profiles.find(p => p.id === e.baseline)?.model_id)?.name ?? 'Experiment'}</option>)}
        </select></label>}
        {!!modelChoices.length && <label>Model<select value={model?.id ?? ''} onChange={e => go({model:e.target.value,profile:undefined,experiment:undefined,node:undefined,event:undefined,hotspot:undefined,guide:undefined})}>
          {model?.format === 'HTP_CONTEXT' && <option value={model.id}>{model.name} (HTP Context)</option>}
          {modelChoices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>}
        {!!catalog?.profiles.length && <label>Profile<select value={profileId ?? ''} onChange={e => go({profile:e.target.value || undefined, model:undefined, experiment:undefined,node:undefined,event:undefined,hotspot:undefined,guide:undefined})}>
          {!profileId && <option value="">No profile</option>}
          {catalog.profiles.filter(item => query.view !== 'graph' || item.model_id === modelId).map(item => <option key={item.id} value={item.id}>
            {query.view !== 'graph' && (catalog.models.find(m => m.id === item.model_id)?.name + ' · ')}{item.source} · {item.id.slice(-8)}
          </option>)}
        </select></label>}
        {chosenProfile && <span className={'status ' + (chosenProfile.provenance === 'fixture' ? 'fixture' : '')}><i/>{chosenProfile.source} · {chosenProfile.backend ?? 'Backend unknown'} · {chosenProfile.provenance}</span>}
      </div>}
      {error && <p className="error" role="alert">{error}</p>}
      {home && <WorkspaceHome model={model} profile={chosenProfile} hotspot={query.hotspot} status={statusRequest?.value}
        statusError={statusRequest?.error} openStep={openStep} openExample={openExample}/>}
      {capabilities && <Capabilities status={statusRequest?.value} error={statusRequest?.error}
        showProfile={id => go({view:'timeline',profile:id,model:undefined,experiment:undefined,hotspot:undefined,node:undefined,event:undefined,guide:undefined})}/>}
      {query.guide && expert && <p className="guide-context"><b>Guided analysis</b> · {model?.name} · {chosenProfile?.backend ?? 'Loading measured capture'}</p>}
      {query.view === 'graph' && graph && <GraphView key={graph.artifact.id} graph={graph} profile={profile} query={query} go={go}
        nodeRanks={nodeRequest?.value?.hotspots ?? []} moduleRanks={moduleRequest?.value?.hotspots ?? []}/>}
      {query.view === 'timeline' && <CaptureSummary profile={chosenProfile} canRun={model?.format === 'ONNX' && statusRequest?.value?.ort_cpu_available === true}
        run={() => setDialog({action:'run_ort_profile'})} importTrace={() => setDialog({action:'import_profile',traceFormat:'qnn-viewer-csv-v2.50'})}
        locate={() => go({view:'locate',level:'module',hotspot:undefined})}/>}
      {query.view === 'timeline' && profile && (profile.raw_format === 'csv' ?
        <CsvProfile key={profile.id} profile={profile} query={query} go={go}/> :
        <Timeline key={profile.id} profile={profile} query={query} go={go}/>)}
      {(query.view === 'diagnosis' || query.view === 'locate') && catalog && <Diagnosis profile={profile} query={query} experiment={comparison} go={go}
        compare={() => setDialog({action:'compare_experiments'})} hotspots={hotspots}/>}
      {query.view === 'optimize' && (chosenProfile && selectedId ? <NotebookPlan key={`${profileId}-${level}-${selectedId}`} profile={chosenProfile}
        hotspotId={selectedId} level={level} back={() => go({view:'diagnosis',hotspot:selectedId,level})}/> : !error &&
        <Panel title="Claude Code Experiment Plan"><div className="detail"><p>{profileId && !rankingRequest ? 'Loading selected hotspot…' : 'Select a hotspot with operation evidence to generate a task.'}</p>
          <button className="action" onClick={() => go({view:'locate',level:'module'})}>Locate hotspots <ArrowRight size={14}/></button></div></Panel>)}
      {!error && (query.view === 'graph' && !graph || query.view === 'timeline' && !profile) &&
        <Panel title="Evidence"><p className="detail quiet">{query.view === 'graph' && model?.format === 'HTP_CONTEXT' ? 'Import the source ONNX to open a graph for this HTP Context.' :
          !catalog || (query.view === 'graph' ? modelId : profileId) ? 'Loading evidence…' : 'Run make demo or import evidence to begin.'}</p></Panel>}
    </main>
    {dialog && catalog && <ImportDialog options={dialog} catalog={catalog} modelId={modelId} profileId={profileId} close={() => setDialog(undefined)}
      done={update => {setRevision(value => value + 1); go({node:undefined, event:undefined, hotspot:undefined, experiment:undefined, guide:undefined, ...update});}}/>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
