; C# references.scm
; Captures: invocations, member access, object creation, return, assignments

(invocation_expression
  function: (identifier) @inv.func
  arguments: (argument_list) @inv.args) @inv.expr

(invocation_expression
  function: (member_access_expression
    (identifier) @inv.object) @inv.member_expr
  arguments: (argument_list) @inv.args) @inv.expr

(member_access_expression
  (identifier) @member.object
  (identifier) @member.name) @member.expr

(object_creation_expression
  type: (identifier) @new.type
  arguments: (argument_list) @new.args) @new.expr

(return_statement
  (_) @return.value) @return.stmt

(assignment_expression
  left: (_) @assign.left
  right: (_) @assign.right) @assign.expr

; Generic identifier reference
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
