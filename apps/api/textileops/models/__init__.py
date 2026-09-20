"""SQLAlchemy models. Importing this package registers every table."""

from textileops.models.actions import ActionProposal, Approval, Execution
from textileops.models.base import Base
from textileops.models.catalog import FabricSpec, FabricSpecComponent, Material
from textileops.models.exceptions import (
    ExceptionEvidence,
    Investigation,
    OperationalException,
)
from textileops.models.intake import (
    ExtractedFact,
    Message,
    ReconciliationItem,
    SourceDocument,
)
from textileops.models.inventory import (
    InventoryLot,
    InventoryMovement,
    InventoryReservation,
)
from textileops.models.logistics import Shipment, ShipmentLine
from textileops.models.org import Customer, Supplier, User
from textileops.models.platform import AICallLog, AuditEvent, BusinessMetricEvent, Job
from textileops.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
)
from textileops.models.production import (
    ProductionBatch,
    ProductionEvent,
    ProductionMaterialRequirement,
)
from textileops.models.quality import QCInspection, QCMeasurement
from textileops.models.sales import SalesOrder, SalesOrderLine

__all__ = [
    "AICallLog",
    "ActionProposal",
    "Approval",
    "AuditEvent",
    "Base",
    "BusinessMetricEvent",
    "Customer",
    "ExceptionEvidence",
    "Execution",
    "ExtractedFact",
    "FabricSpec",
    "FabricSpecComponent",
    "InventoryLot",
    "InventoryMovement",
    "InventoryReservation",
    "Investigation",
    "Job",
    "Material",
    "Message",
    "OperationalException",
    "ProductionBatch",
    "ProductionEvent",
    "ProductionMaterialRequirement",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "PurchaseOrderReceipt",
    "QCInspection",
    "QCMeasurement",
    "ReconciliationItem",
    "SalesOrder",
    "SalesOrderLine",
    "Shipment",
    "ShipmentLine",
    "SourceDocument",
    "Supplier",
    "User",
]
