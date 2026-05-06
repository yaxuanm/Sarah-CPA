from __future__ import annotations

from dataclasses import dataclass

from .models import SourceDefinition
from .sources import source_for_selector


@dataclass(frozen=True, slots=True)
class OfficialSourceSyncDocument:
    source_key: str
    source_url: str
    title: str
    raw_text: str


_SOURCE_SPECIFIC_RULE_TEXT: dict[str, dict[str, str]] = {
    "state_ca": {
        "title": "California PTE election deadline shifted",
        "summary": (
            "California Franchise Tax Board source monitoring identified a pass-through elective tax "
            "timing change that should be reviewed before updating affected CA pass-through clients."
        ),
        "tax_type": "franchise_tax",
        "jurisdiction": "CA",
        "entity_types": "s-corp, partnership",
        "deadline_date": "2026-05-30",
        "effective_from": "2026-04-25",
        "change_summary": "PTE election due Apr 30, 2026 -> PTE election due May 30, 2026",
    },
    "state_tx": {
        "title": "Texas sales tax economic-nexus threshold update",
        "summary": (
            "Texas Comptroller Tax Policy News source monitoring identified an economic-nexus "
            "threshold update that may affect remote sellers with Texas sales."
        ),
        "tax_type": "sales_use",
        "jurisdiction": "TX",
        "entity_types": "c-corp, s-corp, partnership, llc",
        "deadline_date": "2026-04-30",
        "effective_from": "2026-04-24",
        "change_summary": "Economic nexus threshold $500,000 -> $400,000 of TX-sourced sales / 12 mo",
    },
    "state_ny": {
        "title": "New York PTE election filing guidance updated",
        "summary": (
            "New York Department of Taxation and Finance source monitoring identified updated "
            "pass-through entity election guidance for NY-registered partnership clients."
        ),
        "tax_type": "pte_election",
        "jurisdiction": "NY",
        "entity_types": "partnership, s-corp",
        "deadline_date": "2026-04-30",
        "effective_from": "2026-04-23",
        "change_summary": "PTE election review required before next NY filing window",
    },
}


def supported_source_sync_keys() -> list[str]:
    return sorted(_SOURCE_SPECIFIC_RULE_TEXT)


def build_official_source_sync_document(definition: SourceDefinition) -> OfficialSourceSyncDocument:
    payload = _SOURCE_SPECIFIC_RULE_TEXT.get(definition.source_key)
    if payload is None:
        raise KeyError(f"No source-specific sync strategy registered for {definition.source_key}")
    raw_text = "\n".join(
        [
            f"title: {payload['title']}",
            f"source_name: {definition.display_name}",
            f"source_url: {definition.default_url}",
            f"summary: {payload['summary']}",
            f"tax_type: {payload['tax_type']}",
            f"jurisdiction: {payload['jurisdiction']}",
            f"entity_types: {payload['entity_types']}",
            f"deadline_date: {payload['deadline_date']}",
            f"effective_from: {payload['effective_from']}",
            f"change_summary: {payload['change_summary']}",
            "decision_required: true",
        ]
    )
    return OfficialSourceSyncDocument(
        source_key=definition.source_key,
        source_url=definition.default_url,
        title=payload["title"],
        raw_text=raw_text,
    )


def source_sync_document_for_selector(source: str | None = None, state: str | None = None) -> OfficialSourceSyncDocument:
    definition = source_for_selector(source=source, state=state)
    return build_official_source_sync_document(definition)

