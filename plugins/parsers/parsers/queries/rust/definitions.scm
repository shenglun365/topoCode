; Rust definitions.scm
; Captures: functions, structs, enums, traits, impls, type aliases, constants, statics, modules, enum variants, let bindings, macros

(function_item
  name: (identifier) @func.name
  parameters: (parameters) @func.params
  body: (block) @func.body) @func.def

(struct_item
  name: (type_identifier) @struct.name
  body: (field_declaration_list) @struct.body) @struct.def

(enum_item
  name: (type_identifier) @enum.name
  body: (enum_variant_list) @enum.body) @enum.def

(trait_item
  name: (type_identifier) @trait.name
  (declaration_list) @trait.body) @trait.def

(impl_item
  trait: (_)? @impl.trait
  type: (_) @impl.type
  body: (declaration_list) @impl.body) @impl.def

(type_item
  name: (type_identifier) @type_alias.name
  type: (_) @type_alias.type) @type_alias.def

(const_item
  name: (identifier) @const.name
  value: (_) @const.value) @const.def

(static_item
  name: (identifier) @static.name
  value: (_) @static.value) @static.def

(mod_item
  name: (identifier) @mod.name
  body: (declaration_list) @mod.body) @mod.def

(enum_variant
  name: (identifier) @variant.name) @variant.def

(let_declaration
  pattern: (identifier) @let.name
  value: (_)? @let.value) @let.def

(macro_definition
  (identifier) @macro.name
  (_) @macro.body) @macro.def
