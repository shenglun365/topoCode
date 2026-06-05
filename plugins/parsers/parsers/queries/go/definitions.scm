; Go definitions.scm
; Captures: functions, methods, types, structs, interfaces, variables, constants

(function_declaration
  name: (identifier) @func.name
  parameters: (parameter_list) @func.params
  result: (_)? @func.result) @func.def

(method_declaration
  receiver: (parameter_list) @method.receiver
  name: (field_identifier) @method.name
  parameters: (parameter_list) @method.params
  result: (_)? @method.result) @method.def

(type_declaration
  (type_spec
    name: (type_identifier) @type.name
    type: (_) @type.type) @type.spec) @type.decl

(struct_type
  (field_declaration_list) @struct.body) @struct.def

(interface_type
  (_) @interface.body) @interface.def

(function_type
  parameters: (parameter_list) @func_type.params
  result: (_)? @func_type.result) @func_type.def

(var_declaration
  (var_spec
    name: (identifier) @var.name
    type: (_)? @var.type
    value: (_)? @var.value) @var.spec) @var.decl

(short_var_declaration
  left: (expression_list
    (identifier) @sv.name)
  right: (_) @sv.value) @sv.def

(const_declaration
  (const_spec
    name: (identifier) @const.name
    value: (_)? @const.value) @const.spec) @const.decl
