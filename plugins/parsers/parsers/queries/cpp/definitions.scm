; C++ definitions.scm
; Captures: function, class, struct, enum, namespace, template, type alias, concept

(function_definition
  declarator: (function_declarator
    declarator: (identifier) @func.name
    parameters: (parameter_list) @func.params)) @func.def

(class_specifier
  name: (type_identifier) @class.name
  body: (field_declaration_list) @class.body) @class.def

(struct_specifier
  name: (type_identifier) @struct.name
  body: (field_declaration_list) @struct.body) @struct.def

(enum_specifier
  name: (type_identifier) @enum.name
  body: (enumerator_list) @enum.body) @enum.def

(namespace_definition
  (namespace_identifier) @namespace.name
  (declaration_list) @namespace.body) @namespace.def

(template_declaration
  (template_parameter_list) @template.params
  (_) @template.body) @template.def

(alias_declaration
  name: (type_identifier) @type_alias.name
  type: (_) @type_alias.type) @type_alias.def

(concept_definition
  (identifier) @concept.name
  (_) @concept.body) @concept.def

(declaration
  declarator: (init_declarator
    declarator: (identifier) @var.name
    value: (_)? @var.value) @var.decl) @var.def
