"""store — arch_routes 存储层（A1-T3：由 store.py 1834 行拆为 base + 6 领域模块）。

`from . import store` / `store.XxxStore` 使用方式与拆分前完全一致（全量 re-export，
类属性 patch 语义不变）。
"""
from __future__ import annotations

from .contract import AcceptanceStore, ContractItemStore, ContractPackageStore
from .conv import AgentBusStore, AgentSessionsStore, ContextUnitsStore, ConversationsStore, DocsStore, InteractionsStore, McpCallsStore, UnitTestSessionsStore, UnitTestsStore
from .semantic import AstCacheStore, ExtractTaskStore, SemanticAssetsStore, SemanticRefsStore
from .blueprint import BlueprintsStore, CollabConfigStore, SnapshotsStore, StagingScansStore, TagsStore
from .core import ExecutionTasksStore, PlansStore, ProjectsStore, RequirementsStore, TaskTreesStore
from .governance import CapabilityProposalStore, FrameworkConfigStore, GlossaryStore, NameTombstoneStore, NamingConventionStore, UserOverlayStore
from .base import _now_ms, PROJECT_TABLES, _CAMEL_RE, _JSON_COLUMNS, _SEQ_SQL, _all, _data_to_db, _db, _delete, _dumps, _fetchall_routed, _get, _insert, _loads, _locate_db, _next_seq, _resolve_pid, _route_read, _row_to_api, _scan_dbs, _target_db, _to_camel, _to_snake, _update, bump_seq, get_by_id, next_id, run_atomic
