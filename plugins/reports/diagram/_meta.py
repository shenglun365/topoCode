from typing import Optional, Any
from dataclasses import dataclass


@dataclass
class ParserMeta:
    name: str
    start_marker: str = "@startuml"
    end_marker: str = "@enduml"
    parser_type: str = "full"       # "full" | "tree" | "pass-through"
    patterns: Optional[list] = None  # [(regex, score), ...] or [(regex, score, flags), ...]
    min_score: int = 2
    supports_skinparam: bool = True
    supports_preproc: bool = True
    supports_layout: bool = True
