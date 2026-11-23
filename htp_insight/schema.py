from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["ORT", "QNN", "Optrace", "QHAS"]
TimeUnit = Literal["us", "cycles"]


class TensorInfo(BaseModel):
    name: str
    shape: list[int | str | None] | None = None
    dtype: str | None = None
    initializer_elements: int | None = None


class QuantizationInfo(BaseModel):
    format: Literal["QDQ", "AIMET"]
    tensor: str
    operation: str | None = None
    scale_tensor: str | None = None
    zero_point_tensor: str | None = None
    scale: list[float] | None = None
    zero_point: list[int | float] | None = None
    axis: int | None = None
    dtype: str | None = None
    bitwidth: int | None = None
    encoding: dict | list | None = None


class GraphNode(BaseModel):
    id: str
    name: str
    op: str
    domain: str
    module: str
    inputs: list[str]
    outputs: list[str]
    predecessors: list[str]
    quantization: list[int]


class SemanticModule(BaseModel):
    id: str
    kind: str
    parent: str
    nodes: list[str]


class ModelArtifact(BaseModel):
    id: str
    sha256: str
    name: str
    format: Literal["ONNX", "HTP_CONTEXT"]
    origin: str | None = None
    target_device: str | None = None
    compatibility: dict = Field(default_factory=dict)


class Graph(BaseModel):
    artifact: ModelArtifact
    architecture: str
    nodes: list[GraphNode]
    modules: list[SemanticModule]
    tensors: dict[str, TensorInfo]
    inputs: list[str]
    outputs: list[str]
    initializer_elements: int
    quantization: list[QuantizationInfo]
    shape_inference_issue: str | None = None


class ProfileEvent(BaseModel):
    id: str
    source: Source
    backend: str | None = None
    profiler_version: str | None = None
    device: dict = Field(default_factory=dict)
    operation: str | None = None
    name: str
    kind: str
    start: float | None = None
    duration: float | None = None
    unit: TimeUnit = "us"
    parent: str | None = None
    track: str | None = None
    resource: str | None = None
    raw_index: int


class NodeMapping(BaseModel):
    operation_ids: list[str]
    node_ids: list[str]
    method: Literal["exact-name-op", "provided", "unknown"]
    evidence: dict | None = None


class ProfileSession(BaseModel):
    id: str
    model_id: str
    source: Source
    provenance: Literal["measured", "imported", "fixture"]
    backend: str | None = None
    profiler_version: str | None = None
    device: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    events: list[ProfileEvent]
    mappings: list[NodeMapping]
    unit: TimeUnit = "us"
    latency_us: dict | None = None


class Hotspot(BaseModel):
    id: str
    label: str
    module: str
    node_ids: list[str]
    total_us: float | None = None
    total_cycles: float | None = None
    unit: TimeUnit = "us"
    share: float | None
    scope: str
    calls: int
    evidence_ids: list[str]


class OptimizationHypothesis(BaseModel):
    kind: Literal["hypothesis"] = "hypothesis"
    mechanism: str
    adaptation: str
    metrics: list[str]
    risk: str


class ExperimentResult(BaseModel):
    id: str
    baseline: str
    candidate: str
    hypothesis: str | None = None
    numeric: dict | None = None
    latency: dict
    graph_diff: dict
    module_costs: list[dict]
