; Java definitions.scm
; Captures: method, class, interface, enum, record, variable, parameter, constructor
; Note: Java uses positional children, not named fields for most nodes

(method_declaration
  (identifier) @method.name
  (formal_parameters) @method.params) @method.def

(constructor_declaration
  (identifier) @ctor.name
  (formal_parameters) @ctor.params
  (constructor_body) @ctor.body) @ctor.def

(class_declaration
  (identifier) @class.name
  (class_body) @class.body) @class.def

(interface_declaration
  (identifier) @interface.name
  (interface_body) @interface.body) @interface.def

(enum_declaration
  (identifier) @enum.name
  (enum_body) @enum.body) @enum.def

(record_declaration
  (identifier) @record.name
  (formal_parameters) @record.params
  (class_body) @record.body) @record.def

(variable_declarator
  (identifier) @var.name
  (_)? @var.value) @var.def

(formal_parameter
  (identifier) @param.name) @param.def
