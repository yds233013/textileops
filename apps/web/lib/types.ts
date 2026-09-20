/** Types mirroring the API's response models. */

export type Severity = "critical" | "high" | "medium" | "low";
export type RiskLevel = "on_track" | "watch" | "at_risk" | "late";
export type ExceptionStatus =
  | "open"
  | "investigating"
  | "action_proposed"
  | "resolved"
  | "dismissed";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
}

export interface ImpactMetric {
  key: string;
  label: string;
  value: string | number | null;
  unit: string | null;
  basis: "calculated" | "partial" | "unavailable";
  note: string | null;
}

export interface AffectedOrder {
  sales_order_id: string;
  number: string;
  customer_id: string;
  customer_name: string;
  promised_date: string;
  outstanding_value: string | null;
  currency: string;
}

export interface Impact {
  headline: string;
  metrics: ImpactMetric[];
  affected_orders: AffectedOrder[];
  customers_affected: string[];
  financial: {
    revenue_exposure: string | null;
    currency: string | null;
    basis: string;
    note: string | null;
  };
  notes: string[];
  computed_at: string;
}

export interface AttentionCard {
  exception_id: string;
  code: string;
  exception_type: string;
  severity: Severity;
  status: ExceptionStatus;
  priority_score: number;
  what: string;
  why: string;
  impact_headline: string;
  impact_metrics: ImpactMetric[];
  recommended_action: string | null;
  customers_affected: string[];
  revenue_exposure: string | null;
  revenue_basis: string;
  revenue_note: string | null;
  currency: string | null;
  detected_at: string;
  age_hours: number;
  has_investigation: boolean;
  pending_proposal_count: number;
  links: Record<string, string | null>;
}

export interface MetricTile {
  key: string;
  label: string;
  value: number | string | null;
  unit: string | null;
  hint: string | null;
  tone: "neutral" | "good" | "warn" | "bad";
}

export interface Dashboard {
  greeting: string;
  as_of: string;
  attention_queue: AttentionCard[];
  metrics: MetricTile[];
  counts_by_severity: Record<string, number>;
  counts_by_type: Record<string, number>;
  ai_mode: "model" | "deterministic";
  ai_note: string;
}

export interface OrderSummary {
  id: string;
  number: string;
  customer_id: string;
  customer_name: string;
  status: string;
  order_date: string;
  promised_date: string;
  risk: RiskLevel;
  estimated_completion: string | null;
  days_ahead: number | null;
  /** Why there is no estimated completion. null means the order is finished. */
  completion_unknown_reason: string | null;
  material_readiness: string;
  production_status: string;
  qc_status: string;
  shipment_status: string;
  outstanding_value: string | null;
  value_basis: string;
  currency: string;
  open_exception_count: number;
}

export interface OrderLine {
  id: string;
  line_no: number;
  fabric_spec_id: string;
  fabric_code: string;
  fabric_name: string;
  quantity: string;
  unit: string;
  shipped_quantity: string;
  produced_quantity: string;
  outstanding_quantity: string;
  stock_available: string;
  to_produce: string;
  estimated_ready_date: string | null;
  promised_date: string;
  unit_price: string | null;
  outstanding_value: string | null;
  blocked_batch_codes: string[];
  batch_ids: string[];
}

export interface OrderDetail extends OrderSummary {
  lines: OrderLine[];
  blocked_reasons: string[];
  notes: string | null;
  customer_reference: string | null;
  open_exception_ids: string[];
}

export interface OrderList {
  items: OrderSummary[];
  total: number;
  counts_by_risk: Record<string, number>;
}

export interface TimelineEntry {
  at: string;
  kind: string;
  title: string;
  detail: string;
  entity_type: string | null;
  entity_id: string | null;
}

export interface Supplier {
  id: string;
  code: string;
  name: string;
  country: string;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  currency: string;
  default_lead_time_days: number;
  on_time_rate: string | null;
  is_active: boolean;
  open_po_count: number;
  late_po_count: number;
  open_exception_count: number;
}

export interface SupplierMessage {
  id: string;
  received_at: string;
  sender: string;
  subject: string | null;
  intent: string;
  body: string;
  is_duplicate: boolean;
}

export interface PurchaseOrder {
  id: string;
  number: string;
  supplier_id: string;
  supplier_name: string;
  status: string;
  order_date: string;
  expected_date: string;
  revised_expected_date: string | null;
  current_expected_date: string;
  days_late: number;
  currency: string;
  notes: string | null;
  total_ordered_lines: number;
  is_partially_received: boolean;
}

export interface Receipt {
  id: string;
  received_at: string;
  accepted_quantity: string;
  rejected_quantity: string;
  unit: string;
  supplier_document_ref: string | null;
  note: string | null;
}

export interface POLine {
  id: string;
  line_no: number;
  material_id: string;
  material_code: string;
  material_name: string;
  ordered_quantity: string;
  received_quantity: string;
  rejected_quantity: string;
  outstanding_quantity: string;
  unit: string;
  unit_price: string | null;
  expected_date: string | null;
  receipts: Receipt[];
}

export interface ETAProvenance {
  current_expected_date: string;
  original_expected_date: string;
  is_revised: boolean;
  reason: string | null;
  updated_at: string | null;
  source_message_id: string | null;
  source_message_excerpt: string | null;
  source_document_id: string | null;
}

export interface PurchaseOrderDetail extends PurchaseOrder {
  lines: POLine[];
  eta_provenance: ETAProvenance;
  open_exception_ids: string[];
}

export interface SupplierDetail {
  supplier: Supplier;
  purchase_orders: PurchaseOrder[];
  recent_messages: SupplierMessage[];
}

export interface Material {
  id: string;
  code: string;
  name: string;
  category: string;
  base_unit: string;
  composition: string | null;
  yarn_count_text: string | null;
  colour: string | null;
  shade_code: string | null;
  standard_cost: string | null;
  currency: string | null;
  reorder_point: string | null;
  is_active: boolean;
}

export interface FabricSpec {
  id: string;
  code: string;
  name: string;
  composition: string;
  construction: string | null;
  gsm: string;
  width_cm: string;
  colour: string | null;
  shade_code: string | null;
  finish: string;
  sale_unit: string;
  standard_lead_time_days: number;
}

export interface Position {
  material_id: string;
  material_code: string;
  material_name: string;
  category: string;
  unit: string;
  on_hand: string;
  quarantined: string;
  reserved: string;
  available: string;
  incoming: string;
  required: string;
  projected: string;
  over_committed_by: string;
  shortage: string;
  first_shortfall_date: string | null;
  reorder_point: string | null;
}

export interface Allocation {
  production_batch_id: string;
  production_batch_code: string;
  required_by: string;
  quantity: string;
  covered_quantity: string;
  shortfall_quantity: string;
  covered_by_date: string | null;
  /** Disambiguates a null covered_by_date, which means either
   *  "already in the building" or "nothing covers this at all". */
  coverage_source: "stock" | "incoming" | "uncovered";
  is_short: boolean;
  is_late: boolean;
  sales_order_id: string | null;
  sales_order_number: string | null;
  customer_name: string | null;
  promised_date: string | null;
}

export interface IncomingLine {
  purchase_order_id: string;
  purchase_order_number: string;
  supplier_name: string;
  quantity: string;
  unit: string;
  expected_date: string;
  is_revised: boolean;
}

export interface Coverage {
  position: Position;
  horizon: string;
  allocations: Allocation[];
  incoming: IncomingLine[];
  explanation: string;
}

export interface Lot {
  id: string;
  lot_code: string;
  material_name: string | null;
  fabric_name: string | null;
  quantity_on_hand: string;
  quantity_received: string;
  unit: string;
  status: string;
  location: string;
  received_at: string;
  gsm_actual: string | null;
  width_cm_actual: string | null;
  shade_code_actual: string | null;
}

export interface Batch {
  id: string;
  code: string;
  fabric_spec_id: string;
  fabric_name: string;
  stage: string;
  status: string;
  planned_quantity: string;
  output_quantity: string;
  wastage_quantity: string;
  rejected_quantity: string;
  unit: string;
  planned_start: string;
  planned_completion: string;
  estimated_completion: string | null;
  actual_completion: string | null;
  delay_days: number;
  yield_pct: string | null;
  priority: number;
  blocked_reason: string | null;
  sales_order_id: string | null;
  sales_order_number: string | null;
  customer_name: string | null;
}

export interface BatchDetail extends Batch {
  requirements: {
    material_id: string;
    material_code: string;
    material_name: string;
    required_quantity: string;
    issued_quantity: string;
    outstanding_quantity: string;
    unit: string;
    required_by: string;
  }[];
  events: {
    id: string;
    occurred_at: string;
    event_type: string;
    quantity: string | null;
    unit: string | null;
    note: string | null;
  }[];
  material_ready_date: string | null;
  notes: string | null;
}

export interface Measurement {
  kind: string;
  label: string | null;
  observed_value: string | null;
  observed_text: string | null;
  target_value: string | null;
  tolerance_low: string | null;
  tolerance_high: string | null;
  unit_text: string | null;
  result: string;
}

export interface Inspection {
  id: string;
  code: string;
  production_batch_id: string | null;
  batch_code: string | null;
  inventory_lot_id: string | null;
  inspected_at: string;
  outcome: string;
  inspected_quantity: string;
  accepted_quantity: string;
  rejected_quantity: string;
  unit: string;
  notes: string | null;
  reinspection_of_id: string | null;
  measurements: Measurement[];
}

export interface Shipment {
  id: string;
  number: string;
  customer_id: string;
  customer_name: string;
  status: string;
  carrier: string | null;
  tracking_reference: string | null;
  dispatch_date: string | null;
  expected_delivery_date: string | null;
  actual_delivery_date: string | null;
  days_late: number;
  /** True when the goods arrived late, as opposed to not having arrived yet. */
  delivered_late: boolean;
  notes: string | null;
  lines: {
    id: string;
    sales_order_line_id: string;
    sales_order_number: string | null;
    quantity: string;
    unit: string;
  }[];
}

export interface Evidence {
  id: string;
  kind: string;
  label: string;
  detail: string;
  data: Record<string, unknown> | null;
  entity_type: string | null;
  entity_id: string | null;
  message_id: string | null;
  source_document_id: string | null;
  recorded_at: string;
}

export interface InvestigationFindings {
  what_happened: string;
  evidence: { label: string; detail: string; source: string }[];
  root_cause: { statement: string; kind: string; supporting_evidence: string[] };
  operational_impact: string;
  financial_impact: string;
  options: { title: string; description: string; trade_off: string }[];
  recommended_action: {
    action_type: string;
    title: string;
    rationale: string;
    draft_subject: string | null;
    draft_body: string | null;
  } | null;
  missing_information: string[];
  confidence: number;
  provider?: string;
  stubbed?: boolean;
  /** Recommendations the deterministic gate refused, and why. Present only
   *  when something was actually turned away. */
  discarded_recommendations?: {
    action_type: string;
    title: string | null;
    reason: string;
  }[];
}

export interface Investigation {
  id: string;
  started_at: string;
  completed_at: string | null;
  provider: string;
  model: string | null;
  findings: InvestigationFindings | null;
  tool_calls: { name: string; ok: boolean; summary: string; at: string }[] | null;
  error: string | null;
  is_stubbed: boolean;
}

export interface OperationalException {
  id: string;
  code: string;
  exception_type: string;
  severity: Severity;
  status: ExceptionStatus;
  title: string;
  summary: string;
  recommended_action: string | null;
  detected_at: string;
  first_detected_at: string;
  last_evaluated_at: string;
  resolved_at: string | null;
  investigated_at: string | null;
  priority_score: number;
  occurrence_count: number;
  auto_resolved: boolean;
  entity_type: string;
  entity_id: string;
  customer_id: string | null;
  supplier_id: string | null;
  sales_order_id: string | null;
  purchase_order_id: string | null;
  production_batch_id: string | null;
  material_id: string | null;
  shipment_id: string | null;
  impact: Impact | null;
  detection_metrics: Record<string, unknown> | null;
  owner_user_id: string | null;
  resolution_note: string | null;
}

export interface ExceptionDetail extends OperationalException {
  evidence: Evidence[];
  investigations: Investigation[];
  proposal_ids: string[];
}

export interface ExceptionList {
  items: OperationalException[];
  total: number;
  counts_by_severity: Record<string, number>;
  counts_by_type: Record<string, number>;
}

export interface Proposal {
  id: string;
  code: string;
  exception_id: string | null;
  action_type: string;
  execution_mode: "internal" | "external_draft";
  status: string;
  origin: string;
  title: string;
  rationale: string;
  payload: Record<string, unknown>;
  draft_subject: string | null;
  draft_body: string | null;
  draft_edited: boolean;
  model: string | null;
  created_at: string;
  expires_at: string | null;
  effect_description: string;
  approvals: {
    id: string;
    decision: string;
    decided_by_user_id: string;
    decided_at: string;
    note: string | null;
  }[];
  executions: {
    id: string;
    mode: string;
    status: string;
    attempted_at: string;
    completed_at: string | null;
    result: Record<string, unknown> | null;
    error: string | null;
  }[];
}

export interface SourceDocument {
  id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  channel: string;
  kind: string;
  status: string;
  classification_confidence: number | null;
  received_at: string;
  processed_at: string | null;
  page_count: number | null;
  error: string | null;
  is_duplicate: boolean;
  warnings: string[];
  fact_count: number;
}

export interface ExtractedFact {
  id: string;
  fact_type: string;
  field_path: string | null;
  raw_value: string | null;
  normalized_value: Record<string, unknown> | null;
  unit: string | null;
  confidence: number | null;
  status: string;
  entity_type: string | null;
  entity_id: string | null;
  model: string | null;
  applied_at: string | null;
  review_reason: string | null;
}

export interface ReconciliationItem {
  id: string;
  kind: string;
  question: string;
  candidates: { id: string; label: string; score: number }[] | null;
  status: string;
  created_at: string;
  resolved_at: string | null;
  resolution: Record<string, unknown> | null;
  source_document_id: string | null;
  message_id: string | null;
  extracted_fact_id: string | null;
  fact_raw_value: string | null;
}

export interface DocumentDetail extends SourceDocument {
  extracted_text_excerpt: string | null;
  facts: ExtractedFact[];
  reconciliation_items: ReconciliationItem[];
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_user_id: string | null;
  actor_label: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  summary: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  exception_id: string | null;
  action_proposal_id: string | null;
}

export interface SearchHit {
  entity_type: string;
  entity_id: string;
  label: string;
  sublabel: string;
  href: string;
  score: number;
}

export interface ProductMetrics {
  window_days: number;
  counters: Record<string, number>;
  durations: {
    label: string;
    unit: string;
    count: number;
    median: number | null;
    p90: number | null;
    note: string | null;
  }[];
  ai: {
    calls: number;
    by_status: Record<string, number>;
    by_workflow: Record<string, number>;
    median_latency_ms: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    stubbed_share_pct: number;
  };
  caveat: string;
  exception_breakdown: {
    by_type: Record<string, number>;
    by_severity: Record<string, number>;
  };
}

export interface Integration {
  key: string;
  name: string;
  configured: boolean;
  status: string;
  detail: string;
}

export interface Settings {
  environment: string;
  /** True while TextileOps is deliberately not changing anything by itself. */
  pilot_mode: boolean;
  pilot_mode_note: string;
  simulation_enabled: boolean;
  ai_enabled: boolean;
  ai_model: string | null;
  order_at_risk_buffer_days: number;
  supplier_delay_warn_days: number;
  shipment_delay_grace_days: number;
  max_upload_mb: number;
  allowed_upload_extensions: string[];
  integrations: Integration[];
  worker_tasks: string[];
}

export interface SimulationResult {
  event: string;
  summary: string;
  details: Record<string, unknown>;
  engine: Record<string, number>;
}
