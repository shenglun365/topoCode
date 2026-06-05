; C# imports.scm
; Captures: using directives

(using_directive
  (identifier) @using.name) @using.directive

(using_directive
  (qualified_name) @using.qualified) @using.directive_qualified
