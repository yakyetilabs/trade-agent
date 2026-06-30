"""Tool 2: lookup_shipment_manifest (vendor-scoped).

The only authority for which shipments this tool returns is the ``vendor_id`` in
the runtime context — the model-facing schema has no vendor argument, so a
prompt-injection payload cannot redirect the lookup.

Scope-violation audit in a single read: because shipments are keyed by their
globally unique id with ``vendor_id`` as a field, a by-id lookup fetches the
document once and compares the owner. A foreign shipment returns an empty result
*and* records ``scope_violation=true`` + ``attempted_vendor_id`` on the trace —
the audit signal the AgentOps surface expects to stay at zero.

Each returned manifest line is enriched by joining its declared ``hts_code`` to
the in-process HTS catalog (the deterministic, authoritative restriction path —
distinct from the semantic Pinecone retrieval in retrieve_tariff_regulation).
"""

import logging
from typing import Literal

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from src import repository
from src.data.hts_catalog import get_hts_clause
from src.models import Shipment
from src.tools.vendor_context import VendorContext
from src.tracing.trace_context import record_tool_call

_logger = logging.getLogger(__name__)

_StatusFilter = Literal["in_transit", "held", "flagged", "cleared"]


def _enrich(shipment: Shipment) -> dict[str, object]:
    """Render a shipment to a dict, joining each line's HTS restriction details."""
    data: dict[str, object] = shipment.model_dump(mode="json")
    enriched_lines: list[dict[str, object]] = []
    for line in shipment.manifest:
        line_data: dict[str, object] = line.model_dump(mode="json")
        clause = get_hts_clause(line.hts_code)
        if clause is not None:
            line_data["restriction"] = clause.restriction.value
            line_data["duty_rate"] = clause.duty_rate
            line_data["hts_title"] = clause.title
            if clause.notes:
                line_data["hts_notes"] = clause.notes
        enriched_lines.append(line_data)
    data["manifest"] = enriched_lines
    return data


def run_lookup_shipment_manifest(
    vendor_id: str,
    shipment_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, object]]:
    """Pure core: vendor-scoped manifest lookup with single-read scope audit."""
    tool_input: dict[str, object] = {
        "shipment_id": shipment_id,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
    }
    with record_tool_call("lookup_shipment_manifest", tool_input) as out:
        result: list[dict[str, object]] = []
        scope_violation = False

        if shipment_id is not None:
            shipment = repository.get_shipment(shipment_id)
            if shipment is not None and shipment.vendor_id != vendor_id:
                scope_violation = True
                out["attempted_vendor_id"] = shipment.vendor_id
                _logger.warning(
                    "scope violation: vendor %s attempted shipment %s owned by %s",
                    vendor_id,
                    shipment_id,
                    shipment.vendor_id,
                )
            elif shipment is not None:
                result = [_enrich(shipment)]
        else:
            shipments = repository.list_shipments_for_vendor(vendor_id)
            if status is not None:
                shipments = [s for s in shipments if s.status.value == status]
            if date_from is not None:
                shipments = [s for s in shipments if s.eta >= date_from]
            if date_to is not None:
                shipments = [s for s in shipments if s.eta <= date_to]
            result = [_enrich(s) for s in shipments]

        out["count"] = len(result)
        out["scope_violation"] = scope_violation
        out["shipment_ids"] = [str(r.get("shipment_id")) for r in result]
    return result


@tool
def lookup_shipment_manifest(
    runtime: ToolRuntime[VendorContext],
    shipment_id: str | None = None,
    status: _StatusFilter | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, object]]:
    """Look up shipments for the CURRENT vendor and return their manifests, each line enriched
    with its HTS restriction details. You CANNOT specify a vendor — results are always scoped to
    the authenticated vendor. Pass `shipment_id` to fetch one shipment, or use
    `status`/`date_from`/`date_to` (ISO dates) to list filtered shipments. Returns an empty list
    if nothing matches or the id is not this vendor's."""
    vendor_id = runtime.context["vendor_id"]
    return run_lookup_shipment_manifest(vendor_id, shipment_id, status, date_from, date_to)
