import { ArrowRight, ArrowUpRight } from 'lucide-react';
import type { Dependency, HardwareLane, HardwareTimeline, ParallelBlocker } from './types';

export function laneName(lane: HardwareLane) {
  return `Core ${lane.core} · ${lane.type} · TID ${lane.tid}`;
}

const evidenceLabels: Record<string, string> = {
  trace_data: 'Recorded data flow', trace_sequencer: 'Recorded sequencer order',
  trace_input: 'Optrace input', compiled_tensor: 'Compiled tensor',
};
const waitLabel = (kind: string) => kind === 'dma_wait' ? 'DMA wait' : 'Synchronization';
const cycles = (n: number) => `${n.toLocaleString('en-US')} cycles`;

export function DependencyArrows({timeline, selected, blocker, tracks, min, range}: {
  timeline: HardwareTimeline; selected?: string; blocker?: ParallelBlocker;
  tracks: string[]; min: number; range: number;
}) {
  const laneIndex = new Map(tracks.map((id, index) => [id, index]));
  const edges = timeline.dependencies.filter(edge => edge.source === selected || edge.target === selected);
  return <svg className="hardware-arrows" width="100%" height={tracks.length * 60} viewBox={`0 0 1000 ${tracks.length * 60}`}
    preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <marker id="dependency-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6"/></marker>
      <marker id="blocker-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6"/></marker>
    </defs>
    {edges.map(edge => {
      const source = timeline.events[edge.source];
      const target = timeline.events[edge.target];
      const row1 = laneIndex.get(source.lane_id ?? 'unassigned');
      const row2 = laneIndex.get(target.lane_id ?? 'unassigned');
      if (row1 == null || row2 == null) return null;
      const x1 = (source.end - min) / range * 1000;
      const x2 = (target.start - min) / range * 1000;
      const y1 = row1 * 60 + 36;
      const y2 = row2 * 60 + 36;
      const middle = row1 === row2 ? y1 - 16 : (y1 + y2) / 2;
      const focus = blocker?.source === edge.source && blocker.target === edge.target;
      const sequencer = edge.evidence.every(row => row.kind === 'trace_sequencer');
      return <path data-dependency={`${edge.source}:${edge.target}`} key={`${edge.source}:${edge.target}`}
        className={focus ? 'blocker-arrow' : sequencer ? 'sequencer-arrow' : 'dependency-arrow'}
        d={`M ${x1} ${y1} C ${x1 + 12} ${middle}, ${x2 - 12} ${middle}, ${x2} ${y2}`}
        markerEnd={`url(#${focus ? 'blocker-arrow' : 'dependency-arrow'})`}/>;
    })}
  </svg>;
}

export function OperationDependencies({timeline, eventId, select}: {timeline: HardwareTimeline; eventId: string; select: (id: string) => void}) {
  const incoming = timeline.dependencies.filter(edge => edge.target === eventId);
  const outgoing = timeline.dependencies.filter(edge => edge.source === eventId);
  function dependencyList(edges: Dependency[], direction: 'incoming' | 'outgoing') {
    return edges.map(edge => {
      const peer = timeline.events[direction === 'incoming' ? edge.source : edge.target];
      return <li key={peer.event_id}>
        <button className="action" onClick={() => select(peer.event_id)} title={peer.operation_id}>{peer.name}<ArrowUpRight size={12}/></button>
        <small>{[...new Set(edge.evidence.map(record => evidenceLabels[record.kind] ?? record.kind))].join(' · ')}</small>
        {edge.evidence.some(record => record.raw_indices) && <small className="break">
          {edge.evidence.flatMap(record => record.raw_indices ? [`Flow ${record.flow_id}, raw rows ${record.raw_indices.join(' / ')}`] : []).join(' · ')}
        </small>}
        {edge.evidence.some(record => record.tensor) && <small className="break">{edge.evidence.flatMap(record => record.tensor ? [record.tensor] : []).join(', ')}</small>}
      </li>;
    });
  }
  return <details open><summary>Operation dependencies</summary>
    {!incoming.length && !outgoing.length ? <p className="quiet">No linked operation in the available evidence.</p> : <>
      {!!incoming.length && <><h3>Predecessors</h3><ul className="dependency-list">{dependencyList(incoming, 'incoming')}</ul></>}
      {!!outgoing.length && <><h3>Consumers</h3><ul className="dependency-list">{dependencyList(outgoing, 'outgoing')}</ul></>}
    </>}
  </details>;
}

export function Parallelism({timeline, selected, choose, select}: {
  timeline: HardwareTimeline; selected?: ParallelBlocker; choose: (row: ParallelBlocker) => void; select: (event: string) => void;
}) {
  const laneById = new Map(timeline.lanes.map(lane => [lane.id, lane]));
  function location(key: string) {
    const lane = laneById.get(timeline.events[key].lane_id ?? '');
    return lane ? laneName(lane) : 'Instance unavailable';
  }
  return <div className="detail parallelism">
    <p>Possible blockers have a recorded dependency and finish inside an observed gap on another lane. The overlap measures timing alignment. Scheduler readiness and causal stall duration remain unknown.</p>
    <h3>Possible cross-lane blockers ({timeline.blockers.length})</h3>
    {timeline.blockers.length ? <div className="parallel-rows">{timeline.blockers.map(row => <button className="parallel-row" key={`${row.source}:${row.target}`}
      aria-pressed={selected?.source === row.source && selected.target === row.target} onClick={() => choose(row)}>
      <span><b>{timeline.events[row.source].name}</b><small>{location(row.source)}</small></span>
      <ArrowRight size={16}/><span><b>{timeline.events[row.target].name}</b><small>{location(row.target)}</small></span>
      <small>{cycles(row.overlap_cycles)} overlap<br/>{cycles(row.after_producer_cycles)} to consumer start</small>
    </button>)}</div> : <p className="quiet">No candidate met the trace dependency and cross-lane timing checks.</p>}
    <details><summary>Recorded waits and synchronization ({timeline.waits.length})</summary>
      <p className="quiet">Durations come from marked trace events. The operation that released a wait is unknown unless the trace identifies it.</p>
      <ul className="dependency-list wait-list">{timeline.waits.map(row => <li key={row.event}>
        <button className="action" onClick={() => select(row.event)}>{waitLabel(row.kind)} · {cycles(row.cycles)} <ArrowUpRight size={12}/></button>
        <small>{location(row.event)} · {timeline.events[row.event].name}</small>
      </li>)}</ul>
    </details>
    {timeline.unresolved_flow_count > 0 && <p className="quiet">{timeline.unresolved_flow_count} flow pairs lack two unique measured operation endpoints.</p>}
  </div>;
}
