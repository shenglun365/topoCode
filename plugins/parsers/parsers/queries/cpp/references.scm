; C++ references.scm
; Captures: function calls, field access, new expressions, return, qualified identifiers

(call_expression
  function: (identifier) @call.func
  arguments: (argument_list) @call.args) @call.expr

(call_expression
  function: (field_expression
    field: (field_identifier) @call.method)
  arguments: (argument_list) @call.args) @call.member_expr

(call_expression
  function: (qualified_identifier
    name: (identifier) @call.qualified_name)
  arguments: (argument_list) @call.args) @call.qualified_expr

(field_expression
  argument: (_) @field.object
  field: (field_identifier) @field.name) @field.expr

(new_expression
  type: (type_identifier) @new.type
  arguments: (argument_list) @new.args) @new.expr

(return_statement
  (_) @return.value) @return.stmt

(qualified_identifier
  name: (identifier) @qualified.name) @qualified.id

; Generic identifier reference
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
