; Go imports.scm
; Captures: import declarations, individual import specs

(import_declaration
  (import_spec
    name: (package_identifier)? @import.alias
    path: (interpreted_string_literal) @import.path) @import.spec) @import.decl

(import_declaration
  (import_spec
    path: (interpreted_string_literal) @import.path) @import.spec_simple) @import.decl_simple
