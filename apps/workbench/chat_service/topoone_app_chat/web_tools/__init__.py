"""web_tools 子包（MS5-V3 重做；导出面与原单文件一致）。"""
from .defs import (  # noqa: F401
    MAX_RESULT_LENGTH, REF_TYPES, WEB_TOOL_DEFINITIONS, WEB_TOOL_MAP,
    get_web_tool_definitions, _strip_ref_prefix,
)
from .executor import WebToolExecutor  # noqa: F401
from .refs import resolve_refs_to_context  # noqa: F401
