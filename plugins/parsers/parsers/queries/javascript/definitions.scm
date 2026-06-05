; JavaScript definitions.scm
; Captures: function, class, method, variable, arrow function

(function_declaration
  name: (identifier) @func.name
  parameters: (formal_parameters) @func.params
  body: (statement_block) @func.body) @func.def

(arrow_function
  parameters: (formal_parameters) @arrow.params
  body: (_) @arrow.body) @arrow.def

(class_declaration
  name: (identifier) @class.name
  body: (class_body) @class.body) @class.def

(method_definition
  name: (property_identifier) @method.name
  parameters: (formal_parameters) @method.params
  body: (statement_block) @method.body) @method.def

(variable_declarator
  name: (identifier) @var.name
  value: (_)? @var.value) @var.def
