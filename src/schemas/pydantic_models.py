from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ObservableType(str, Enum):
    PHONE = "phone"
    EMAIL = "email"
    USERNAME = "username"
    DOMAIN = "domain"
    IP = "ip"
    URL = "url"


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class NodeType(str, Enum):
    INPUT = "input"
    CONNECTOR = "connector"
    PROCESSOR = "processor"
    OUTPUT = "output"


class NodeExecutionStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class EvidenceKind(str, Enum):
    RAW_RESPONSE = "raw_response"
    NORMALIZED_BUNDLE = "normalized_bundle"
    EXECUTION_LOG = "execution_log"
    HTML_REPORT = "html_report"
    PDF_REPORT = "pdf_report"
    CHECKSUM = "checksum"
    TIMESTAMP_PROOF = "timestamp_proof"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class ClaimLifecycleState(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    REJECTED = "rejected"


class QuotaWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(..., ge=0)
    remaining: int = Field(..., ge=0)
    refill_interval_seconds: int = Field(..., ge=1)
    safe_rps: float = Field(..., ge=0)


class VaultKeyLease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    alias: str | None = None
    leased_at: datetime
    expires_at: datetime
    status: Literal["healthy", "degraded", "revoked", "expired"]
    quota: QuotaWindow


class PortDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    direction: PortDirection
    observable_types: list[ObservableType] = Field(..., min_length=1)
    allows_many: bool = False
    required: bool = True
    contract_name: str = Field(..., min_length=1)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(3, ge=1)
    backoff_seconds: float = Field(1.0, ge=0)
    jitter_enabled: bool = True


class AdapterCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_name: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    input_types: list[ObservableType] = Field(..., min_length=1)
    output_contract: str = Field(..., min_length=1)
    auth_scheme: Literal["api_key", "oauth2", "cookie", "session", "none"]
    supports_dry_run: bool = False
    supports_batching: bool = False
    retry_policy: RetryPolicy
    quota_profile: QuotaWindow | None = None
    evidence_kinds: list[EvidenceKind] = Field(default_factory=list)


class NodePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class NodeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1)
    node_type: NodeType
    subtype: str = Field(..., min_length=1)
    position: NodePosition
    input_ports: list[PortDefinition] = Field(default_factory=list)
    output_ports: list[PortDefinition] = Field(default_factory=list)
    adapter: AdapterCapability | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    source_node_id: UUID
    source_port_id: str
    target_node_id: UUID
    target_port_id: str
    observable_type: ObservableType
    contract_name: str = Field(..., min_length=1)


class ObservableSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observable_type: ObservableType
    value: str = Field(..., min_length=1)
    masked_value: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class WorkflowContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    analyst_id: str = Field(..., min_length=1)
    run_id: UUID = Field(default_factory=uuid4)
    graph_version: str = Field(..., min_length=1)
    seeds: list[ObservableSeed] = Field(default_factory=list)


class RawEvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID = Field(default_factory=uuid4)
    node_id: UUID
    kind: EvidenceKind
    uri: str = Field(..., min_length=1)
    mime_type: str = Field(..., min_length=1)
    sha256: str = Field(..., min_length=64, max_length=64)
    created_at: datetime
    timestamp_proof_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StixMarkingDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    definition_type: str
    definition: dict[str, Any]


class StixExternalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str
    url: HttpUrl | None = None
    external_id: str | None = None


class StixObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    spec_version: Literal["2.1"] = "2.1"
    id: str
    created: datetime | None = None
    modified: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=0, le=100)
    external_references: list[StixExternalReference] = Field(default_factory=list)
    object_marking_refs: list[str] = Field(default_factory=list)


class StixRelationship(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["relationship"] = "relationship"
    spec_version: Literal["2.1"] = "2.1"
    id: str
    relationship_type: str
    source_ref: str
    target_ref: str
    created: datetime | None = None
    modified: datetime | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)


class NormalizedEntityBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    stix_version: Literal["2.1"] = "2.1"
    objects: list[StixObject] = Field(default_factory=list)
    relationships: list[StixRelationship] = Field(default_factory=list)
    marking_definitions: list[StixMarkingDefinition] = Field(default_factory=list)
    source_artifact_ids: list[UUID] = Field(default_factory=list)


class ScoreFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str = Field(..., min_length=1)
    weight: float = Field(..., ge=0)
    contribution: float = Field(..., ge=0)
    rationale: str = Field(..., min_length=1)


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: UUID
    formula_name: str = Field(..., min_length=1)
    confidence_score: float = Field(..., ge=0, le=1)
    confidence_level: ConfidenceLevel
    factors: list[ScoreFactor] = Field(default_factory=list)
    generated_at: datetime


class ClaimEntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    entity_value: str = Field(..., min_length=1)
    entity_id: UUID | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class IntelligenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    claim_type: str = Field(..., min_length=1)
    statement: str = Field(..., min_length=1)
    entities: list[ClaimEntityRef] = Field(..., min_length=1)
    evidence_artifact_ids: list[UUID] = Field(..., min_length=1)
    source_bundle_ids: list[str] = Field(default_factory=list)
    claim_value: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(..., ge=0, le=1)
    status: ClaimStatus
    lifecycle_state: ClaimLifecycleState
    observed_at: datetime | None = None
    trust_tier: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ClaimLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_id: UUID = Field(default_factory=uuid4)
    claim_id: UUID
    from_lifecycle_state: ClaimLifecycleState | None = None
    to_lifecycle_state: ClaimLifecycleState
    from_status: ClaimStatus | None = None
    to_status: ClaimStatus
    actor_id: str = Field(..., min_length=1)
    actor_type: Literal["analyst", "system", "worker", "adapter"]
    reason: str | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NodeRunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(..., min_length=1)
    run_id: UUID
    node_id: UUID
    status: NodeExecutionStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    message: str | None = None
    active_key_lease: VaultKeyLease | None = None
    emitted_artifact_ids: list[UUID] = Field(default_factory=list)


class CaseExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID = Field(default_factory=uuid4)
    workflow_id: str = Field(..., min_length=1)
    run_id: UUID
    export_format: Literal["html", "pdf", "json", "stix"]
    generated_at: datetime
    artifact_ids: list[UUID] = Field(default_factory=list)
    summary_uri: str = Field(..., min_length=1)


class InvestigationGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    nodes: list[NodeDefinition] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
