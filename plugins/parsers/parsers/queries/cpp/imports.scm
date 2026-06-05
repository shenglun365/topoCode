; C++ imports.scm
; Captures: #include, using declarations

(preproc_include
  (string_literal) @include.path) @include.stmt

(preproc_include
  (system_lib_string) @include.lib) @include.system

(using_declaration
  (qualified_identifier) @using.qualified) @using.decl

(using_declaration
  (identifier) @using.name) @using.simple
