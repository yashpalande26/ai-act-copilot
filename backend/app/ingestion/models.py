from pydantic import BaseModel


class ParsedProvision(BaseModel):
    citation_id: str
    eid: str | None
    unit_type: str
    number: str
    heading: str | None
    text_content: str
    parent_citation_id: str | None
    amendment_marker: str | None
    ordinal: int
    # An item the consolidation shows as deleted by an amending act (a marker
    # with a dash run and no text). Kept as a row with empty text and the
    # marker so the numbering and the deletion are on record; never chunked.
    deleted: bool = False
