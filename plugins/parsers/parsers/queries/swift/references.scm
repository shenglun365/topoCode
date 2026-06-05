; Swift references.scm
; Captures: function calls, member access, navigation expressions, return, assignments

(call_expression
  (simple_identifier) @call.func
  (call_suffix) @call.args) @call.expr

(call_expression
  (navigation_expression
    (simple_identifier) @call.method)
  (call_suffix) @call.args) @call.member_expr

(navigation_expression
  (simple_identifier) @nav.root
  (navigation_suffix
    (simple_identifier) @nav.member) @nav.suffix) @nav.expr

(control_transfer_statement
  (_) @return.value) @return.stmt

(assignment
  (_) @assign.target
  (_) @assign.value) @assign.expr

; Type identifier references
(type_identifier) @type_ref.name

; Generic identifier reference
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
