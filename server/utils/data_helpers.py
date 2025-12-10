"""
Data manipulation utilities for sorting and pagination.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def apply_sort(items: List[Dict[str, Any]], sort: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort items by a specified field and direction.

    Args:
        items: List of dictionaries to sort
        sort: Sort specification with "field" and "direction" (asc/desc)

    Returns:
        Sorted list (items with None values for the field are placed last)
    """
    if not sort or not isinstance(sort, dict):
        return items
    field = sort.get("field")
    if not field:
        return items
    direction = (sort.get("direction") or "asc").lower()
    reverse = direction == "desc"
    # Sort with None values last, regardless of direction
    return sorted(items, key=lambda r: (r.get(field) is None, r.get(field)), reverse=reverse)


def paginate(items: List[Dict[str, Any]], limit: Optional[int], offset: int) -> List[Dict[str, Any]]:
    """
    Apply pagination to a list of items.

    Args:
        items: List to paginate
        limit: Maximum number of items to return (None = all)
        offset: Number of items to skip from the start

    Returns:
        Paginated slice of the items list
    """
    start = max(0, int(offset or 0))
    if limit is None:
        return items[start:]
    return items[start : start + max(0, int(limit))]
