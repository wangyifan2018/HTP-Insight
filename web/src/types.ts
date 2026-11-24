export type TimeUnit = 'us' | 'cycles';
export interface Artifact { id: string; name: string; format: string; origin?: string; target_device?: string | null; source_model_id?: string | null; compatibility?: Record<string, unknown> }
export interface Tensor { name: string; shape: Array<number | string | null> | null; dtype: string | null }
export interface Node { id: string; name: string; op: string; module: string; inputs: string[]; outputs: string[]; predecessors: string[]; quantization: number[] }
export interface Module { id: string; parent: string; nodes: string[]; basis?: 'scope' | 'dataflow' | null }
export interface Quantization { format: string; tensor: string; operation: string | null; dtype: string | null; bitwidth: number | null; scale: number[] | null; axis: number | null; zero_point: number[] | null }
export interface Graph { artifact: Artifact; architecture: string; nodes: Node[]; tensors: Record<string, Tensor>; inputs: string[]; outputs: string[]; modules: Module[]; quantization: Quantization[]; initializer_elements: number }
export interface Evidence { id: string; name: string; start: number | null; duration: number | null; recorded_timestamp_us?: number | null; unit: TimeUnit; backend: string | null; track: string | null; resource: string | null; parent: string | null; operation: string | null; kind: string; raw_index: number }
export interface ProfileInfo { id: string; model_id: string; source: string; backend: string | null; provenance: string; unit: TimeUnit; raw_format?: "json" | "csv"; profiler_version: string | null; conditions: Record<string, unknown>; device: Record<string, string | null>; latency_us: {p50: number; p95: number; label?: string; scope?: string; count?: number} | null; raw_trace: string; event_count: number; operation_event_count: number }
export interface EvidenceArtifact {
  id: string; artifact_type: "HTP_GRAPH" | "QHAS"; filename: string; provenance: string; raw: string;
  summary: {
    node_count?: number; tensor_count?: number; operation_count?: number;
    resources?: {type: string | null; utilization: number | null; cycles_used: number | null}[];
  };
  operation_records?: Record<string, unknown>[];
}
export interface Profile extends ProfileInfo { evidence?: EvidenceArtifact[]; events: Evidence[]; mappings: {node_ids: string[]; operation_ids: string[]; method: string; evidence?: {method: string; qnn_op_name: string; source_onnx_names: string[]; framework_csv_sha256: string} | null}[] }
export interface Hotspot { id: string; module: string; label: string; node_ids: string[]; total_us: number | null; total_cycles: number | null; unit: TimeUnit; share: number | null; scope: string; calls: number; evidence_ids: string[] }
export interface ExplainedNode extends Node { input_tensors: Tensor[]; output_tensors: Tensor[]; quantization_details: Quantization[] }
export interface Explanation extends Hotspot { example_evidence: Evidence; raw_trace: string; nodes: ExplainedNode[]; mapping_methods: string[]; related_evidence: EvidenceArtifact[]; provenance: string; hypothesis: {mechanism: string; adaptation: string; risk: string; metrics: string[]}; experiment_hint?: {mechanism: string; change: string; risk: string} }
export interface ExperimentPlan { id: string; markdown: string; adaptation: {kind: string; change: string}; profile: ProfileInfo; hotspot: Hotspot }
interface Metric { baseline: number | null; candidate: number | null; delta_pct: number | null }
export interface Experiment {
  id: string; baseline: string; candidate: string; hypothesis: string | null; name?: string;
  latency: {p50: Metric; p95: Metric; comparable: boolean; unit: string; label?: string; comparison_issues?: {field: string; problem: string}[]};
  numeric: {passed: boolean; atol: number; rtol: number; error?: string; outputs?: Record<string, {max_abs: number | null; mean_abs: number | null}>} | null;
  graph_diff: {baseline_nodes: number; candidate_nodes: number; edges_added?: unknown[]; edges_removed?: unknown[]; operator_changes: {module: string; domain: string; op: string; baseline: number; candidate: number}[]};
  module_costs: {module: string; baseline_us: number | null; candidate_us: number | null; baseline_cycles?: number | null; candidate_cycles?: number | null}[];
  trace_runs: {baseline: number | null; candidate: number | null};
  sources: {baseline: (string | null)[]; candidate: (string | null)[]};
}
export interface Catalog { models: Artifact[]; profiles: ProfileInfo[]; experiments: Experiment[] }
export interface GuidedExample { model: string; model_id: string; profile_id: string; experiment_id: string; backend: string; device: ProfileInfo['device']; latency: Experiment['latency'] }
export interface WorkspaceStatus { ort_cpu_available: boolean; measured_captures: {id: string; backend: string; adapter: string | null; source: string}[]; examples: GuidedExample[] }
export interface AndroidStatus { ready: boolean; busy?: boolean; reason?: string; device?: {model?: string; soc?: string; hexagon?: string; sdk?: string} }

export interface HardwareLane { id: string; core: number; type: string; tid: number }
export interface HardwareEvent { event_id: string; operation_id: string; name: string; lane_id: string | null; assignment: string; flags: string[]; start: number; end: number; wait_kind: string | null; dominant_path_cycles: number | null; qhas_ids: string[] }
export interface Dependency { source: string; target: string; evidence: {kind: string; tensor?: string; flow_id?: number | string; artifact_id?: string; raw_indices?: number[]}[] }
export interface ParallelBlocker { source: string; target: string; overlap_cycles: number; idle_from: number; idle_to: number; producer_end: number; after_producer_cycles: number; status: 'possible'; deep_link: string }
export interface HardwareTimeline { lanes: HardwareLane[]; events: Record<string, HardwareEvent>; dependencies: Dependency[]; waits: {event: string; kind: string; cycles: number}[]; blockers: ParallelBlocker[]; unresolved_flow_count: number }
