/**
 * The words the interface uses for the API's codes.
 *
 * `humanise` turns `supplier_delay` into "Supplier delay", which is fine until
 * it meets an acronym: "Qc failure", "Po late". Anything an operator reads more
 * than once gets a deliberate label here; `humanise` is only the fallback.
 */
import { humanise } from "./format";

export const EXCEPTION_TYPE_LABEL: Record<string, string> = {
  ORDER_AT_RISK: "Order at risk",
  ORDER_LATE: "Order late",
  MATERIAL_SHORTAGE: "Material shortage",
  PO_LATE: "Purchase order overdue",
  SUPPLIER_DELAY: "Supplier delay",
  PRODUCTION_DELAY: "Production delay",
  QC_FAILURE: "QC failure",
  SHIPMENT_DELAY: "Shipment overdue",
  QUANTITY_MISMATCH: "Quantity mismatch",
  INVENTORY_ANOMALY: "Stock anomaly",
};

/** Short forms for tight places: chips, filters, table cells. */
export const EXCEPTION_TYPE_SHORT: Record<string, string> = {
  ORDER_AT_RISK: "Order risk",
  ORDER_LATE: "Order late",
  MATERIAL_SHORTAGE: "Shortage",
  PO_LATE: "PO overdue",
  SUPPLIER_DELAY: "Supplier delay",
  PRODUCTION_DELAY: "Production",
  QC_FAILURE: "QC failure",
  SHIPMENT_DELAY: "Shipment",
  QUANTITY_MISMATCH: "Quantity",
  INVENTORY_ANOMALY: "Stock",
};

export const ACTION_TYPE_LABEL: Record<string, string> = {
  contact_supplier: "Contact supplier",
  request_revised_eta: "Request a revised date",
  expedite_shipment: "Expedite shipment",
  schedule_replacement_batch: "Schedule replacement batch",
  request_qc_reinspection: "Request QC re-inspection",
  notify_customer: "Notify customer",
  change_production_priority: "Change production priority",
  reallocate_inventory: "Reallocate stock",
  raise_purchase_order: "Raise purchase order",
  acknowledge_only: "Acknowledge",
};

export const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  operations: "Operations",
  procurement: "Procurement",
  production: "Production",
  quality: "Quality",
  viewer: "Viewer",
};

const STATUS_LABEL: Record<string, string> = {
  pass: "Passed",
  reject: "Rejected",
  conditional_pass: "Conditional pass",
  not_inspected: "Not inspected",
  partially_inspected: "Partly inspected",
  not_applicable: "Not applicable",
  in_production: "In production",
  ready_to_ship: "Ready to ship",
  not_shipped: "Not shipped",
  nothing_to_ship: "Nothing to ship",
  in_transit: "In transit",
  pending_approval: "Awaiting approval",
  awaiting_external: "Awaiting send",
  action_proposed: "Action proposed",
  needs_review: "Needs review",
  materials_not_covered: "Materials not covered",
  nothing_planned: "Nothing planned",
  not_started: "Not started",
  in_progress: "In progress",
  partially_cancelled: "Part cancelled",
  quarantine: "Quarantined",
  qc_report: "QC report",
  delivery_challan: "Delivery challan",
  inventory_snapshot: "Stock statement",
  external_draft: "Draft for a person to send",
};

export function statusLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STATUS_LABEL[value] ?? humanise(value);
}

export function exceptionTypeLabel(value: string, short = false): string {
  return (short ? EXCEPTION_TYPE_SHORT[value] : EXCEPTION_TYPE_LABEL[value]) ?? humanise(value);
}

export function actionTypeLabel(value: string): string {
  return ACTION_TYPE_LABEL[value] ?? humanise(value);
}

export function roleLabel(value: string): string {
  return ROLE_LABEL[value] ?? humanise(value);
}
