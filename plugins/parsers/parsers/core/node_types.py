"""统一节点类型与边类型枚举

NodeKind: 22 种符号/结构节点类型
EdgeKind: 13 种关系边类型
Provenance: 边来源标注 (parser / resolution / synthesizer / framework)
"""

from enum import Enum


class NodeKind(str, Enum):
    FILE        = "file"
    MODULE      = "module"
    CLASS       = "class"
    STRUCT      = "struct"
    INTERFACE   = "interface"
    TRAIT       = "trait"
    PROTOCOL    = "protocol"
    FUNCTION    = "function"
    METHOD      = "method"
    PROPERTY    = "property"
    FIELD       = "field"
    VARIABLE    = "variable"
    CONSTANT    = "constant"
    ENUM        = "enum"
    ENUM_MEMBER = "enum_member"
    TYPE_ALIAS  = "type_alias"
    NAMESPACE   = "namespace"
    PARAMETER   = "parameter"
    IMPORT      = "import"
    EXPORT      = "export"
    ROUTE       = "route"
    COMPONENT   = "component"


class EdgeKind(str, Enum):
    CONTAINS      = "contains"
    CALLS         = "calls"
    IMPORTS       = "imports"
    EXPORTS       = "exports"
    EXTENDS       = "extends"
    IMPLEMENTS    = "implements"
    REFERENCES    = "references"
    TYPE_OF       = "type_of"
    RETURNS       = "returns"
    INSTANTIATES  = "instantiates"
    OVERRIDES     = "overrides"
    DECORATES     = "decorates"
    CALLBACK      = "callback"


class Provenance(str, Enum):
    PARSER      = "parser"
    RESOLUTION  = "resolution"
    SYNTHESIZER = "synthesizer"
    FRAMEWORK   = "framework"
