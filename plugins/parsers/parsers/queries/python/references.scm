; Python references.scm
; Captures: calls, attribute access, return values

(call
  function: (identifier) @call.func
  arguments: (argument_list) @call.args) @call.expr

(call
  function: (attribute
    attribute: (identifier) @call.method)
  arguments: (argument_list) @call.args) @call.member_expr

(attribute
  object: (_) @attr.object
  attribute: (identifier) @attr.name) @attr.expr

(subscript
  value: (_) @subscr.value
  subscript: (_) @subscr.index) @subscr

(binary_operator
  left: (_) @binop.left
  right: (_) @binop.right) @binop

(return_statement
  (_) @return.value) @return.stmt

; Generic identifier reference (excluding keywords)
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
