"""DiagramSchema pydantic models - mirrors schema/diagram.schema.json.

Contract alignment is enforced by server/tests/test_contract.py.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

DiagramType = Literal[
    "flowchart", "activity", "sequence", "state", "class",
    "er", "usecase", "component", "architecture", "gantt", "pie",
]

_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"


class NodeStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fill: Optional[str] = None
    stroke: Optional[str] = None
    color: Optional[str] = None


class DiagramNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    label: str = Field(min_length=1, max_length=200)
    kind: Optional[str] = None
    style: Optional[NodeStyle] = None
    lane: Optional[str] = None


class DiagramEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: Optional[str] = None
    from_: str = Field(alias="from", pattern=_ID_PATTERN)
    to: str = Field(pattern=_ID_PATTERN)
    label: Optional[str] = Field(default=None, max_length=200)
    kind: Optional[Literal["solid", "dashed", "dotted", "thick"]] = None
    rel: Optional[Literal["associate", "extend", "include", "uses", "provides", "dependency"]] = None
    arrow: Optional[Literal["filled", "open", "none"]] = None


class DiagramGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    contains: list[str]
    kind: Optional[Literal["subgraph", "layer", "boundary"]] = None


class Lane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: Optional[Literal["participant", "actor", "boundary", "database", "entity"]] = None


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    label: str
    kind: Literal["sync", "async", "return"]
    self: Optional[bool] = None


class StateNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    initial: Optional[bool] = None
    final: Optional[bool] = None
    sub: Optional[list[str]] = None


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    label: Optional[str] = None
    guard: Optional[str] = None


class ClassMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Optional[Literal["attr", "method"]] = None
    visibility: Optional[Literal["public", "private", "protected", "package"]] = None
    type: Optional[str] = None


class Klass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    members: Optional[list[ClassMember]] = None


class ClassRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    kind: Literal["inherit", "impl", "assoc", "comp", "agg", "dep"]
    label: Optional[str] = None


class EntityAttr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    key: Optional[bool] = None
    type: Optional[str] = None


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    attrs: Optional[list[EntityAttr]] = None


class ErRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    kind: Literal["1:1", "1:N", "M:N"]
    label: Optional[str] = None


class GanttSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class GanttTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    section: str
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    duration: int = Field(ge=1, le=3650)
    dependsOn: Optional[list[str]] = None
    tags: Optional[list[Literal["done", "active", "crit"]]] = None


class SchemaAnimationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    nodes: Optional[list[str]] = None
    edges: Optional[list[str]] = None
    selectors: Optional[list[str]] = None


class PieSlice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    value: float


class SchemaAnimation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Optional[Literal["reveal", "highlight"]] = None
    stepMs: Optional[int] = Field(default=None, ge=50, le=10000)
    steps: list[SchemaAnimationStep]


_TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "flowchart": ("nodes",),
    "activity": ("nodes",),
    "usecase": ("nodes",),
    "component": ("nodes",),
    "architecture": ("nodes",),
    "sequence": ("participants", "messages"),
    "state": ("states",),
    "class": ("classes",),
    "er": ("entities",),
    "gantt": ("tasks",),
    "pie": ("slices",),
}


class DiagramSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    type: DiagramType
    title: Optional[str] = Field(default=None, max_length=200)
    direction: Optional[Literal["TB", "BT", "LR", "RL"]] = None
    nodes: Optional[list[DiagramNode]] = None
    edges: Optional[list[DiagramEdge]] = None
    groups: Optional[list[DiagramGroup]] = None
    lanes: Optional[list[Lane]] = None
    participants: Optional[list[Participant]] = None
    messages: Optional[list[Message]] = None
    states: Optional[list[StateNode]] = None
    transitions: Optional[list[Transition]] = None
    classes: Optional[list[Klass]] = None
    classRelations: Optional[list[ClassRelation]] = None
    entities: Optional[list[Entity]] = None
    erRelations: Optional[list[ErRelation]] = None
    sections: Optional[list[GanttSection]] = None
    tasks: Optional[list[GanttTask]] = None
    slices: Optional[list[PieSlice]] = None
    animation: Optional[SchemaAnimation] = None
    extra: Optional[dict] = None

    @model_validator(mode="after")
    def _check_type_requirements(self) -> "DiagramSchema":
        for field in _TYPE_REQUIRED[self.type]:
            if not getattr(self, field):
                raise ValueError(f"type '{self.type}' requires non-empty '{field}'")
        return self
