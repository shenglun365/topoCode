"""ResultCompressor — token budget compressor for MCP tool results.

Compresses large result payloads to fit within Agent token limits:
- Truncates long lists (limit_top_5)
- Filters by time range (filter_by_range)
- Compresses symbol data by removing redundant fields
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def limit_top_5(data: list, key: str = "") -> list:
    """Limit a list to the top 5 items, optionally sorted by a key."""
    if not data:
        return data
    if len(data) <= 5:
        return data
    if key:
        try:
            sorted_data = sorted(data, key=lambda x: x.get(key, 0) if isinstance(x, dict) else 0, reverse=True)
            return sorted_data[:5]
        except Exception:
            pass
    return data[:5]


def filter_by_range(data: list, field: str, start: str = "", end: str = "") -> list:
    """Filter a list of dicts by a datetime field range."""
    if not start and not end:
        return data
    result = []
    start_dt = datetime.fromisoformat(start) if start else datetime.min
    end_dt = datetime.fromisoformat(end) if end else datetime.max
    for item in data:
        if isinstance(item, dict):
            val = item.get(field, "")
            if val:
                try:
                    dt = datetime.fromisoformat(val) if isinstance(val, str) else val
                    if start_dt <= dt <= end_dt:
                        result.append(item)
                except (ValueError, TypeError):
                    result.append(item)
            else:
                result.append(item)
    return result


def compress_symbol_payload(symbols: list[dict]) -> list[dict]:
    """Remove redundant fields from symbol entries to save tokens."""
    compressed = []
    keep_keys = {"name", "kind", "file_path", "line"}
    for sym in symbols:
        if isinstance(sym, dict):
            compressed.append({k: v for k, v in sym.items() if k in keep_keys})
        else:
            compressed.append(sym)
    return compressed


def compress_result(result: dict, max_items: int = 20) -> dict:
    """Compress a tool result dict to fit token budgets."""
    if not isinstance(result, dict):
        return result

    compressed = {}
    for key, value in result.items():
        if isinstance(value, dict):
            compressed[key] = compress_result(value, max_items)
        elif isinstance(value, list):
            if key in ("symbols", "matches", "history", "files", "dependencies", "incoming", "outgoing"):
                compressed[key] = limit_top_5(value[:max_items])
            elif key in ("by_file",):
                compressed[key] = {k: v[:max_items] for k, v in value.items()}
            else:
                compressed[key] = value[:max_items]
        else:
            compressed[key] = value
    return compressed
