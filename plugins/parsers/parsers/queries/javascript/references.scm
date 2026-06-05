; JavaScript references.scm
; Captures: calls, member access, new expressions, return, assignments

(call_expression
  function: (identifier) @call.func
  arguments: (arguments) @call.args) @call.expr

(call_expression
  function: (member_expression
    property: (property_identifier) @call.method)
  arguments: (arguments) @call.args) @call.member_expr

(member_expression
  object: (_) @member.object
  property: (property_identifier) @member.prop) @member.expr

(new_expression
  constructor: (identifier) @new.callee
  arguments: (arguments) @new.args) @new.expr

(assignment_expression
  left: (_) @assign.left
  right: (_) @assign.right) @assign.expr

(return_statement
  (_) @return.value) @return.stmt

; Generic identifier reference (non-keyword)
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_$][a-zA-Z0-9_$]*$"))
