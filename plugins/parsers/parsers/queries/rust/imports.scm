; Rust imports.scm
; Captures: use declarations

(use_declaration
  (scoped_identifier) @import.scoped) @import.decl

(use_declaration
  (scoped_use_list) @import.scoped_list) @import.decl_list

(use_declaration
  (use_as_clause) @import.as_clause) @import.decl_as

(use_list
  (identifier) @import.name) @import.list

(use_as_clause
  (identifier) @import.name
  (identifier) @import.alias) @import.as_pair
