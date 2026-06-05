; Go references.scm
; Captures: function calls, method/selector access, return

(call_expression
  function: (identifier) @call.func
  arguments: (argument_list) @call.args) @call.expr

(call_expression
  function: (selector_expression
    field: (field_identifier) @call.method)
  arguments: (argument_list) @call.args) @call.member_expr

(selector_expression
  operand: (_) @sel.object
  field: (field_identifier) @sel.field) @sel.expr

(return_statement
  (_) @return.value) @return.stmt

; Package-level identifier references
(package_identifier) @pkg_ref.name

; Type identifier references
(type_identifier) @type_ref.name

; Field identifier references
(field_identifier) @field_ref.name

; Generic identifier reference
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_][a-zA-Z0-9_]*$"))
