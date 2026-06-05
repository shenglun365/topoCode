; C# definitions.scm
; Captures: class, struct, interface, method, constructor, variable, parameter

(class_declaration
  (identifier) @class.name
  (declaration_list) @class.body) @class.def

(struct_declaration
  (identifier) @struct.name
  (declaration_list) @struct.body) @struct.def

(interface_declaration
  (identifier) @interface.name
  (declaration_list) @interface.body) @interface.def

(method_declaration
  (identifier) @method.name
  (parameter_list) @method.params
  (block) @method.body) @method.def

(constructor_declaration
  (identifier) @ctor.name
  (parameter_list) @ctor.params
  (block) @ctor.body) @ctor.def

(variable_declaration
  (variable_declarator
    (identifier) @var.name
    (_)? @var.value) @var.decl) @var.def

(parameter
  (identifier) @param.name) @param.def
