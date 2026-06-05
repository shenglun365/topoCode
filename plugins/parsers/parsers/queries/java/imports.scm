; Java imports.scm
; Captures: import declarations

(import_declaration
  (scoped_identifier) @import.scoped) @import.stmt

(import_declaration
  (identifier) @import.simple_name) @import.stmt_simple
