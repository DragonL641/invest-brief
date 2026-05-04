"""
Pydantic models for structured AI output validation.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class NewsSummaryItem(BaseModel):
    title: str
    summary: str


class NewsSummaryResponse(BaseModel):
    """Validates the news summary array from Claude API."""
    items: List[NewsSummaryItem]

    @classmethod
    def from_raw_list(cls, data: list) -> Optional["NewsSummaryResponse"]:
        """Parse a raw JSON list into validated items."""
        if not isinstance(data, list):
            return None
        items = []
        for item in data:
            if isinstance(item, dict) and "title" in item and "summary" in item:
                items.append(NewsSummaryItem(title=item["title"], summary=item["summary"]))
        if not items:
            return None
        return cls(items=items)
