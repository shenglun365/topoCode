; C definitions.scm
; Captures: function, struct, union, enum, typedef, declaration

(function_definition
  declarator: (function_declarator
    declarator: (identifier) @func.name
    parameters: (parameter_list) @func.params)) @func.def

(struct_specifier
  name: (type_identifier) @struct.name
  body: (field_declaration_list) @struct.body) @struct.def

(union_specifier
  name: (type_identifier) @union.name
  body: (field_declaration_list) @union.body) @union.def

(enum_specifier
  name: (type_identifier) @enum.name
  body: (enumerator_list) @enum.body) @enum.def

(type_definition
  (_) @typedef.type
  (type_identifier) @typedef.name) @typedef.def

(declaration
  declarator: (init_declarator
    declarator: (identifier) @var.name
    value: (_)? @var.value) @var.decl) @var.def
