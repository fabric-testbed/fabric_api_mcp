"""
Data manipulation utilities for sorting, pagination, and declarative filtering.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Declarative filter engine
# ---------------------------------------------------------------------------

def _resolve_field(record: Dict[str, Any], field: str) -> Any:
    """Resolve a possibly dot-notated field from a dict (e.g. 'components.GPU')."""
    parts = field.split(".")
    val: Any = record
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


def _match_operator(value: Any, op: str, operand: Any) -> bool:
    """Evaluate a single operator against a value.

    Supported operators: eq, ne, lt, lte, gt, gte, in, contains, icontains,
    regex, any, all.

    The ``contains`` and ``icontains`` operators are polymorphic:
      - str: substring match (e.g. "FPGA" in "FPGA-Xilinx-U280")
      - dict: matches against any key (e.g. components dict keys)
      - list/tuple/set: matches against stringified elements
    """
    if op == "eq":
        return value == operand
    if op == "ne":
        return value != operand
    if op == "lt":
        return value is not None and value < operand
    if op == "lte":
        return value is not None and value <= operand
    if op == "gt":
        return value is not None and value > operand
    if op == "gte":
        return value is not None and value >= operand
    if op == "in":
        return value in operand
    if op == "contains":
        if isinstance(value, str):
            return operand in value
        if isinstance(value, dict):
            return any(operand in k for k in value)
        if isinstance(value, (list, tuple, set)):
            return any(operand in str(v) for v in value)
        return False
    if op == "icontains":
        op_lower = operand.lower()
        if isinstance(value, str):
            return op_lower in value.lower()
        if isinstance(value, dict):
            return any(op_lower in k.lower() for k in value)
        if isinstance(value, (list, tuple, set)):
            return any(op_lower in str(v).lower() for v in value)
        return False
    if op == "regex":
        return isinstance(value, str) and bool(re.search(operand, value))
    if op == "any":
        # value is iterable, at least one element satisfies sub-filter
        if not isinstance(value, (list, tuple, set)):
            return False
        return any(_match_record_filters({"_v": v}, {"_v": operand}) for v in value)
    if op == "all":
        if not isinstance(value, (list, tuple, set)):
            return False
        return all(_match_record_filters({"_v": v}, {"_v": operand}) for v in value)
    raise ValueError(f"Unknown filter operator: {op}")


def _match_record_filters(record: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    """
    Return True if *record* satisfies every clause in *filters*.

    Each key in *filters* is either:
      - "or"  → list of sub-filter dicts (logical OR)
      - a field name → value (shorthand for {"eq": value}) or dict of {op: operand}
    """
    for key, spec in filters.items():
        if key == "or":
            if not isinstance(spec, list) or not spec:
                continue
            if not any(_match_record_filters(record, sub) for sub in spec):
                return False
            continue

        field_val = _resolve_field(record, key)

        if isinstance(spec, dict):
            for op, operand in spec.items():
                if not _match_operator(field_val, op, operand):
                    return False
        else:
            # Shorthand: {"field": value} is eq
            if field_val != spec:
                return False
    return True


def apply_filters(
    items: List[Dict[str, Any]],
    filters: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Apply a declarative JSON filter DSL to a list of records.

    Supports field-level operators (eq, ne, lt, lte, gt, gte, in, contains,
    icontains, regex, any, all) and logical OR via {"or": [{...}, {...}]}.

    ``contains`` / ``icontains`` work on strings (substring), dicts (key match),
    and lists (element match).

    Examples::

        # Cores >= 32
        {"cores_available": {"gte": 32}}

        # Site is UCSD or STAR with >=32 cores
        {"or": [{"site": {"icontains": "UCSD"}}, {"site": {"icontains": "STAR"}}],
         "cores_available": {"gte": 32}}

        # Hosts with an FPGA component (matches dict key "FPGA-Xilinx-U280")
        {"components": {"contains": "FPGA"}}

        # Exact match shorthand
        {"name": "RENC"}
    """
    if not filters:
        return items
    return [r for r in items if _match_record_filters(r, filters)]


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


def paginate(items: List[Dict[str, Any]], limit: Optional[int], offset: int) -> Dict[str, Any]:
    """
    Apply pagination to a list of items and return metadata.

    Args:
        items: List to paginate
        limit: Maximum number of items to return (None = all)
        offset: Number of items to skip from the start

    Returns:
        Dict with keys: items, total, count, offset, has_more
    """
    total = len(items)
    start = max(0, int(offset or 0))
    if limit is None:
        sliced = items[start:]
    else:
        sliced = items[start : start + max(0, int(limit))]
    return {
        "items": sliced,
        "total": total,
        "count": len(sliced),
        "offset": start,
        "has_more": (start + len(sliced)) < total,
    }
