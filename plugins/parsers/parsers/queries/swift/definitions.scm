; Swift definitions.scm
; Captures: function, class/struct/enum, protocol, initializer, deinitializer, variable, parameter

(function_declaration
  name: (simple_identifier) @func.name
  body: (function_body) @func.body) @func.def

(class_declaration
  (type_identifier) @class.name
  (class_body) @class.body) @class.def

(protocol_declaration
  (type_identifier) @protocol.name
  (protocol_body) @protocol.body) @protocol.def

(init_declaration
  body: (function_body) @initializer.body) @initializer.def

(deinit_declaration
  body: (function_body) @deinit.body) @deinit.def

(property_declaration
  (pattern) @var.name
  (_)? @var.value) @var.def

(parameter
  (simple_identifier) @param.name) @param.def
