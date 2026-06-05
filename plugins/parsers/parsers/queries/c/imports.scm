; C imports.scm
; Captures: #include preprocessor directives, #define

(preproc_include
  (string_literal) @include.path) @include.stmt

(preproc_include
  (system_lib_string) @include.lib) @include.system

(preproc_def
  name: (identifier) @define.name
  value: (_) @define.value) @define.def
