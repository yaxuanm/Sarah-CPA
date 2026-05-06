from __future__ import annotations

from .models import SourceDefinition


STATE_CODES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

STATE_SOURCE_OVERRIDES = {
    "CA": {
        "display_name": "California Franchise Tax Board Newsroom",
        "default_url": "https://www.ftb.ca.gov/about-ftb/newsroom/index.html",
    },
    "TX": {
        "display_name": "Texas Comptroller Tax Policy News",
        "default_url": "https://comptroller.texas.gov/taxes/",
    },
    "NY": {
        "display_name": "New York Department of Taxation and Finance Press Office",
        "default_url": "https://www.tax.ny.gov/press/",
    },
}


def official_source_registry() -> dict[str, SourceDefinition]:
    registry: dict[str, SourceDefinition] = {
        "irs": SourceDefinition(
            source_key="irs",
            source_type="federal",
            jurisdiction="FEDERAL",
            official=True,
            poll_frequency_minutes=15,
            display_name="IRS.gov",
            default_url="https://www.irs.gov/newsroom",
            fetch_format="html",
        ),
        "fema": SourceDefinition(
            source_key="fema",
            source_type="federal",
            jurisdiction="FEDERAL",
            official=True,
            poll_frequency_minutes=15,
            display_name="FEMA Disaster Declarations",
            default_url="https://www.fema.gov/openfema-data-page/disaster-declarations-summaries-v2",
            fetch_format="rss",
        ),
        "federal_register": SourceDefinition(
            source_key="federal_register",
            source_type="federal",
            jurisdiction="FEDERAL",
            official=True,
            poll_frequency_minutes=60,
            display_name="Federal Register",
            default_url="https://www.federalregister.gov/api/v1/documents.rss",
            fetch_format="rss",
        ),
    }
    for state in STATE_CODES:
        override = STATE_SOURCE_OVERRIDES.get(state, {})
        registry[f"state_{state.lower()}"] = SourceDefinition(
            source_key=f"state_{state.lower()}",
            source_type="state",
            jurisdiction=state,
            official=True,
            poll_frequency_minutes=60,
            display_name=override.get("display_name", f"{state} Department of Revenue"),
            default_url=override.get("default_url", f"https://www.{state.lower()}.gov/tax"),
            fetch_format="html",
        )
    return registry


def source_for_selector(source: str | None = None, state: str | None = None) -> SourceDefinition:
    registry = official_source_registry()
    if source:
        key = source.lower()
        if key in registry:
            return registry[key]
    if state:
        key = f"state_{state.lower()}"
        if key in registry:
            return registry[key]
    raise KeyError(source or state or "unknown_source")
