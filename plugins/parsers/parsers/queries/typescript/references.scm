; TypeScript references.scm
; Captures: calls, member access, identifier references, type references

; Call expression (direct function calls)
(call_expression
  function: (identifier) @call.callee
  arguments: (arguments) @call.args) @call.expr

; Call expression with member access (obj.method())
(call_expression
  function: (member_expression
    property: (property_identifier) @call.method)
  arguments: (arguments) @call.args) @call.member_expr

; New expression
(new_expression
  constructor: (identifier) @new.callee
  arguments: (arguments) @new.args) @new.expr

; Member expression (obj.prop)
(member_expression
  object: (_) @member.object
  property: (property_identifier) @member.prop) @member.expr

; Type annotation reference
(type_annotation
  (type_identifier) @type_ref.name) @type_ref

; Generic type reference
(generic_type
  name: (type_identifier) @generic.name) @generic_ref

; Identifier references (non-keyword identifiers)
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_$][a-zA-Z0-9_$]*$"))

; Assignment target
(assignment_expression
  left: (_) @assign.target
  right: (_) @assign.value) @assign.expr

; Return value
(return_statement
  (_) @return.value) @return.stmt
