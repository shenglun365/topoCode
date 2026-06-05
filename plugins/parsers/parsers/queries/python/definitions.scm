; Python definitions.scm
; Captures: function, class, variable, type alias, parameter

(function_definition
  name: (identifier) @func.name
  parameters: (parameters) @func.params) @func.def

(class_definition
  name: (identifier) @class.name
  body: (block) @class.body) @class.def

(assignment
  left: (identifier) @var.name
  right: (_) @var.value) @var.def

(type_alias_statement
  (type) @type_alias.name
  (type) @type_alias.value) @type_alias.def

(typed_parameter
  (identifier) @param.name
  (type) @param.type) @param.typed

(default_parameter
  (identifier) @param.name
  (_) @param.default) @param.defaulted

(typed_default_parameter
  (identifier) @param.name
  (type)
  (_) @param.default) @param.typed_default
