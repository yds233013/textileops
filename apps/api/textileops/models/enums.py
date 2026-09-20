"""Domain enumerations.

Every enum here is materialised as a native PostgreSQL enum type so the
database — not application code — is the last line of defence on state values.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# --- People -------------------------------------------------------------------
class UserRole(StrEnum):
    OWNER = "owner"
    OPERATIONS = "operations"
    PROCUREMENT = "procurement"
    PRODUCTION = "production"
    QUALITY = "quality"
    VIEWER = "viewer"


# --- Catalogue ----------------------------------------------------------------
class MaterialCategory(StrEnum):
    YARN = "yarn"
    GREIGE_FABRIC = "greige_fabric"
    PROCESSED_FABRIC = "processed_fabric"
    DYE_CHEMICAL = "dye_chemical"
    TRIM = "trim"
    PACKAGING = "packaging"


class FabricFinish(StrEnum):
    NONE = "none"
    MERCERISED = "mercerised"
    PEACH = "peach"
    CALENDERED = "calendered"
    ENZYME_WASH = "enzyme_wash"
    WATER_REPELLENT = "water_repellent"
    ANTI_MICROBIAL = "anti_microbial"


# --- Sales --------------------------------------------------------------------
class SalesOrderStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    IN_PRODUCTION = "in_production"
    READY_TO_SHIP = "ready_to_ship"
    PARTIALLY_SHIPPED = "partially_shipped"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CLOSED = "closed"
    CANCELLED = "cancelled"


OPEN_SALES_ORDER_STATUSES = (
    SalesOrderStatus.CONFIRMED,
    SalesOrderStatus.IN_PRODUCTION,
    SalesOrderStatus.READY_TO_SHIP,
    SalesOrderStatus.PARTIALLY_SHIPPED,
)


class RiskLevel(StrEnum):
    ON_TRACK = "on_track"
    WATCH = "watch"
    AT_RISK = "at_risk"
    LATE = "late"


# --- Procurement --------------------------------------------------------------
class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


OPEN_PO_STATUSES = (
    PurchaseOrderStatus.SENT,
    PurchaseOrderStatus.ACKNOWLEDGED,
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
)


class Currency(StrEnum):
    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


# --- Inventory ----------------------------------------------------------------
class LotStatus(StrEnum):
    AVAILABLE = "available"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    IN_TRANSIT = "in_transit"


class MovementType(StrEnum):
    RECEIPT = "receipt"
    ISSUE = "issue"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    WASTAGE = "wastage"
    PRODUCTION_OUTPUT = "production_output"
    SHIPMENT = "shipment"
    SCRAP = "scrap"
    TRANSFER = "transfer"


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    RELEASED = "released"


# --- Production ---------------------------------------------------------------
class ProductionStage(StrEnum):
    KNITTING = "knitting"
    WEAVING = "weaving"
    DYEING = "dyeing"
    PRINTING = "printing"
    FINISHING = "finishing"
    CUTTING = "cutting"
    PACKING = "packing"


class ProductionStatus(StrEnum):
    PLANNED = "planned"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    REWORK = "rework"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ProductionEventType(StrEnum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    STARTED = "started"
    PAUSED = "paused"
    RESUMED = "resumed"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    OUTPUT_RECORDED = "output_recorded"
    COMPLETED = "completed"
    REWORK_STARTED = "rework_started"
    REJECTED = "rejected"
    NOTE = "note"


# --- Quality ------------------------------------------------------------------
class QCOutcome(StrEnum):
    PASS = "pass"
    CONDITIONAL_PASS = "conditional_pass"
    REWORK = "rework"
    REJECT = "reject"
    PENDING = "pending"


class QCMeasurementKind(StrEnum):
    GSM = "gsm"
    WIDTH_CM = "width_cm"
    SHADE = "shade"
    SHRINKAGE_PCT = "shrinkage_pct"
    DEFECT_POINTS = "defect_points"
    COLOUR_FASTNESS = "colour_fastness"
    PH = "ph"
    TENSILE_STRENGTH = "tensile_strength"
    OTHER = "other"


class MeasurementResult(StrEnum):
    WITHIN_TOLERANCE = "within_tolerance"
    OUT_OF_TOLERANCE = "out_of_tolerance"
    NOT_ASSESSED = "not_assessed"


# --- Logistics ----------------------------------------------------------------
class ShipmentStatus(StrEnum):
    PLANNED = "planned"
    PACKED = "packed"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    CANCELLED = "cancelled"


# --- Intake -------------------------------------------------------------------
class SourceChannel(StrEnum):
    UPLOAD = "upload"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    MANUAL = "manual"
    API = "api"
    SIMULATION = "simulation"


class DocumentKind(StrEnum):
    UNKNOWN = "unknown"
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    INVOICE = "invoice"
    PACKING_LIST = "packing_list"
    DELIVERY_CHALLAN = "delivery_challan"
    QC_REPORT = "qc_report"
    INVENTORY_SNAPSHOT = "inventory_snapshot"
    SUPPLIER_MESSAGE = "supplier_message"
    CUSTOMER_MESSAGE = "customer_message"
    PRODUCTION_LOG = "production_log"
    OTHER = "other"


class DocumentStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    APPLIED = "applied"
    FAILED = "failed"
    REJECTED = "rejected"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageIntent(StrEnum):
    UNKNOWN = "unknown"
    SUPPLIER_DELAY = "supplier_delay"
    SUPPLIER_DISPATCH = "supplier_dispatch"
    SUPPLIER_QUOTE = "supplier_quote"
    ORDER_CHANGE = "order_change"
    ORDER_ENQUIRY = "order_enquiry"
    QUALITY_COMPLAINT = "quality_complaint"
    PAYMENT = "payment"
    LOGISTICS = "logistics"
    GENERAL = "general"


class FactStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    NEEDS_REVIEW = "needs_review"


class ReconciliationStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


# --- Exceptions ---------------------------------------------------------------
class ExceptionType(StrEnum):
    ORDER_AT_RISK = "ORDER_AT_RISK"
    ORDER_LATE = "ORDER_LATE"
    MATERIAL_SHORTAGE = "MATERIAL_SHORTAGE"
    PO_LATE = "PO_LATE"
    SUPPLIER_DELAY = "SUPPLIER_DELAY"
    PRODUCTION_DELAY = "PRODUCTION_DELAY"
    QC_FAILURE = "QC_FAILURE"
    SHIPMENT_DELAY = "SHIPMENT_DELAY"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    INVENTORY_ANOMALY = "INVENTORY_ANOMALY"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


class ExceptionStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    ACTION_PROPOSED = "action_proposed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


ACTIVE_EXCEPTION_STATUSES = (
    ExceptionStatus.OPEN,
    ExceptionStatus.INVESTIGATING,
    ExceptionStatus.ACTION_PROPOSED,
)


class EvidenceKind(StrEnum):
    CALCULATION = "calculation"
    RECORD = "record"
    MESSAGE = "message"
    DOCUMENT = "document"
    TIMELINE = "timeline"
    AI_HYPOTHESIS = "ai_hypothesis"


class EntityType(StrEnum):
    SALES_ORDER = "sales_order"
    SALES_ORDER_LINE = "sales_order_line"
    PURCHASE_ORDER = "purchase_order"
    PURCHASE_ORDER_LINE = "purchase_order_line"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    MATERIAL = "material"
    FABRIC_SPEC = "fabric_spec"
    INVENTORY_LOT = "inventory_lot"
    PRODUCTION_BATCH = "production_batch"
    QC_INSPECTION = "qc_inspection"
    SHIPMENT = "shipment"
    SOURCE_DOCUMENT = "source_document"
    MESSAGE = "message"
    EXCEPTION = "exception"
    ACTION_PROPOSAL = "action_proposal"
    USER = "user"


# --- Actions ------------------------------------------------------------------
class ActionType(StrEnum):
    CONTACT_SUPPLIER = "contact_supplier"
    REQUEST_REVISED_ETA = "request_revised_eta"
    EXPEDITE_SHIPMENT = "expedite_shipment"
    SCHEDULE_REPLACEMENT_BATCH = "schedule_replacement_batch"
    REQUEST_QC_REINSPECTION = "request_qc_reinspection"
    NOTIFY_CUSTOMER = "notify_customer"
    CHANGE_PRODUCTION_PRIORITY = "change_production_priority"
    REALLOCATE_INVENTORY = "reallocate_inventory"
    RAISE_PURCHASE_ORDER = "raise_purchase_order"
    ACKNOWLEDGE_ONLY = "acknowledge_only"


class ExecutionMode(StrEnum):
    """How an approved action is carried out.

    ``INTERNAL`` actions are executed deterministically by TextileOps.
    ``EXTERNAL_DRAFT`` actions require a real integration that does not exist
    yet; TextileOps produces a human-copyable draft and never pretends to send.
    """

    INTERNAL = "internal"
    EXTERNAL_DRAFT = "external_draft"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    AWAITING_EXTERNAL = "awaiting_external"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_EXTERNAL = "awaiting_external"


class ProposalOrigin(StrEnum):
    AI_INVESTIGATION = "ai_investigation"
    RULE_ENGINE = "rule_engine"
    HUMAN = "human"


# --- Platform -----------------------------------------------------------------
class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"
    SKIPPED = "skipped"


class AICallStatus(StrEnum):
    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"
    PROVIDER_ERROR = "provider_error"
    STUBBED = "stubbed"


class BusinessEventType(StrEnum):
    DOCUMENT_RECEIVED = "document_received"
    DOCUMENT_PROCESSED = "document_processed"
    EXTRACTION_COMPLETED = "extraction_completed"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    RECONCILIATION_RESOLVED = "reconciliation_resolved"
    EXCEPTION_DETECTED = "exception_detected"
    EXCEPTION_VIEWED = "exception_viewed"
    EXCEPTION_INVESTIGATED = "exception_investigated"
    EXCEPTION_RESOLVED = "exception_resolved"
    EXCEPTION_DISMISSED = "exception_dismissed"
    PROPOSAL_CREATED = "proposal_created"
    PROPOSAL_APPROVED = "proposal_approved"
    PROPOSAL_REJECTED = "proposal_rejected"
    PROPOSAL_DRAFT_EDITED = "proposal_draft_edited"
    ACTION_EXECUTED = "action_executed"
    SIMULATION_EVENT = "simulation_event"
