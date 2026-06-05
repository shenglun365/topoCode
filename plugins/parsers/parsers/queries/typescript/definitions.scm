; TypeScript definitions.scm
; Captures: function, class, method, variable, interface, type alias, enum

; Function declaration
(function_declaration
  name: (identifier) @func.name
  parameters: (formal_parameters) @func.params) @func.def

; Arrow function
(arrow_function
  parameters: (formal_parameters) @arrow.params) @arrow.def

; Class declaration
(class_declaration
  name: (type_identifier) @class.name
  body: (class_body) @class.body) @class.def

; Method definition inside class
(method_definition
  name: (property_identifier) @method.name
  parameters: (formal_parameters) @method.params) @method.def

; Method signature (interface/abstract)
(method_signature
  name: (property_identifier) @method_sig.name) @method_sig.def

(abstract_method_signature
  name: (property_identifier) @abs_method.name) @abs_method.def

; Variable declarator (const/let/var)
(variable_declarator
  name: (identifier) @var.name
  value: (_)? @var.value) @var.def

; Interface declaration
(interface_declaration
  name: (type_identifier) @interface.name
  body: (interface_body) @interface.body) @interface.def

; Type alias
(type_alias_declaration
  name: (type_identifier) @type_alias.name
  value: (_) @type_alias.value) @type_alias.def

; Enum declaration
(enum_declaration
  (identifier) @enum.name
  body: (enum_body) @enum.body) @enum.def

; Enum member (property_identifier inside enum_body)
(enum_body
  (property_identifier) @enum_member.name) @enum_member.def

; Namespace/module
(internal_module
  name: (identifier) @namespace.name) @namespace.def

; Property signature in interface
(property_signature
  name: (property_identifier) @prop_sig.name
  type: (type_annotation) @prop_sig.type) @prop_sig.def

; Required parameter
(required_parameter
  name: (identifier) @param.name) @param.def

; Optional parameter
(optional_parameter
  name: (identifier) @opt_param.name) @opt_param.def

; Constructor (method_definition named \"constructor\")
(method_definition
  name: (property_identifier) @ctor.name
  parameters: (formal_parameters) @ctor.params) @ctor.def

; Function signature (overloads)
(function_signature
  name: (identifier) @func_sig.name) @func_sig.def
