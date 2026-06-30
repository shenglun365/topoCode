import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

MSG_PRIORITY_CONTROL = 0
MSG_PRIORITY_READ = 1
MSG_PRIORITY_WRITE = 2
MSG_PRIORITY_PUSH = 3
MSG_PRIORITY_BATCH = 4

MSG_TYPE_RPC = "rpc"
MSG_TYPE_PUBLISH = "publish"
MSG_TYPE_HEARTBEAT = "heartbeat"
MSG_TYPE_ACK = "ack"


@dataclass
class InternalMessage:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    src: str = ""
    dst: str = ""
    msg_type: str = MSG_TYPE_RPC
    priority: int = MSG_PRIORITY_WRITE
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    method: str = ""
    params: dict = field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "InternalMessage":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
