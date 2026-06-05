; Java references.scm
; Captures: method invocations, field access, new expressions, type references

(method_invocation
  name: (identifier) @method_inv.name
  arguments: (argument_list) @method_inv.args) @method_inv.expr

(method_invocation
  object: (_) @method_inv.object
  name: (identifier) @method_inv.method
  arguments: (argument_list) @method_inv.args) @method_inv.member_expr

(field_access
  object: (_) @field.object
  field: (identifier) @field.name) @field.expr

(object_creation_expression
  type: (type_identifier) @new.type
  arguments: (argument_list) @new.args) @new.expr

(return_statement
  (_) @return.value) @return.stmt

(type_identifier) @type_ref.name

; Generic identifier reference (non-keyword)
((identifier) @ref.name
  (#match? @ref.name "^[a-zA-Z_$][a-zA-Z0-9_$]*$"))
