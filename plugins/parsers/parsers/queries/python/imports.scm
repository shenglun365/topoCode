; Python imports.scm
; Captures: import statements, from-import statements

(import_statement
  (dotted_name) @import.name) @import.stmt

(import_from_statement
  (dotted_name) @import.module) @import.from_stmt

(aliased_import
  (dotted_name) @import.name
  (identifier) @import.alias) @import.aliased_pair

(wildcard_import) @import.wildcard

(future_import_statement
  (dotted_name) @future.name) @future.stmt
