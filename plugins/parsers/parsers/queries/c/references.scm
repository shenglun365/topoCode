; C references.scm
; Captures: function calls, field access, assignments, return

(call_expression
  function: (identifier) @call.func
  arguments: (argument_list) @call.args) @call.expr

(call_expression
  function: (field_expression
    field: (field_identifier) @call.method)
  arguments: (argument_list) @call.args) @call.member_expr

(field_expression
  argument: (_) @field.object
  field: (field_identifier) @field.name) @field.expr

(assignment_expression
  left: (_) @assign.left
  right: (_) @assign.right) @assign.expr

(return_statement
  (_) @return.value) @return.stmt

; Generic identifier reference
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
