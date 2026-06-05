; JavaScript imports.scm
; Captures: ES module imports, re-exports, dynamic import/require

; ES import statement
(import_statement
  source: (string) @import.source) @import.stmt

; Named import specifier
(import_specifier
  name: (identifier) @import.name
  alias: (identifier)? @import.alias) @import.spec

; Namespace import
(namespace_import
  (identifier) @import.ns_name) @import.ns

; Default import clause
(import_clause
  (identifier) @import.default) @import.default_clause

; Export re-export from module
(export_statement
  source: (string) @export.source) @export.re_export

; Dynamic import: import('module')
(call_expression
  function: (import) @dynamic_import.keyword
  arguments: (arguments
    (string) @dynamic_import.source)) @dynamic_import

; Require call: require('module')
(call_expression
  function: (identifier) @require.callee
  arguments: (arguments
    (string) @require.source)) @require.call
