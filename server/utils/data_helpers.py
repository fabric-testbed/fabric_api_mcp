"""
Data manipulation utilities for sorting and pagination.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


def normalize_list_param(
    value: Optional[Union[str, List[str]]],
    param_name: str = "param",
) -> Optional[List[str]]:
    """
    Normalize a list parameter that may be passed as a JSON string or actual list.

    This handles cases where clients send list parameters as JSON strings
    (e.g., '["item1", "item2"]') instead of actual lists.

    Args:
        value: Either a list of strings, a JSON string representing a list, or None.
        param_name: Name of the parameter (for logging purposes).

    Returns:
        A list of strings or None.

    Examples:
        >>> normalize_list_param(None)
        None
        >>> normalize_list_param(["a", "b"])
        ["a", "b"]
        >>> normalize_list_param('["a", "b"]')
        ["a", "b"]
        >>> normalize_list_param("single_value")
        ["single_value"]
    """
    logger.debug(
        "normalize_list_param called: param_name=%s, value=%r, type=%s",
        param_name,
        value,
        type(value).__name__,
    )

    if value is None:
        logger.debug("normalize_list_param: %s is None, returning None", param_name)
        return None

    if isinstance(value, list):
        logger.debug(
            "normalize_list_param: %s is already a list with %d items, returning as-is",
            param_name,
            len(value),
        )
        return value

    if isinstance(value, str):
        # Try to parse as JSON
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                result = [str(item) for item in parsed]
                logger.info(
                    "normalize_list_param: %s was JSON string, parsed to list with %d items: %r",
                    param_name,
                    len(result),
                    result,
                )
                return result
            else:
                logger.warning(
                    "normalize_list_param: %s JSON parsed but not a list (got %s), treating as single-item",
                    param_name,
                    type(parsed).__name__,
                )
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(
                "normalize_list_param: %s failed JSON parse (%s), treating as single-item list",
                param_name,
                str(e),
            )
        # If not valid JSON, treat as single-item list
        logger.info(
            "normalize_list_param: %s treating string as single-item list: %r",
            param_name,
            [value],
        )
        return [value]

    logger.warning(
        "normalize_list_param: %s has unexpected type %s, returning None",
        param_name,
        type(value).__name__,
    )
    return None


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
