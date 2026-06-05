; Rust references.scm
; Captures: function calls, method invocations, field access, macro invocations, return

(call_expression
  function: (identifier) @call.func
  arguments: (arguments) @call.args) @call.expr

(call_expression
  function: (field_expression
    field: (field_identifier) @call.method)
  arguments: (arguments) @call.args) @call.member_expr

(field_expression
  value: (_) @field.object
  field: (field_identifier) @field.name) @field.expr

(macro_invocation
  (identifier) @macro_inv.name
  (token_tree) @macro_inv.args) @macro_inv.expr

(return_expression
  (_) @return.value) @return.expr

; Type identifier references
(type_identifier) @type_ref.name

; Field identifier references
(field_identifier) @field_ref.name

; Self references
(self) @self_ref.name

; Generic identifier reference
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
