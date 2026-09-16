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
