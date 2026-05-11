from .base_handler import LanguageHandler
from typing import Dict, Any, Optional, List

class CFamilyHandler(LanguageHandler):
    @property
    def preproc_node_types(self) -> List[str]:
        return ['preproc_def', 'preproc_function_def', 'preproc_defined']

    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        # Primary: use refs[0] if available and non-empty string
        refs = node.get('refs')
        if isinstance(refs, list) and len(refs) > 0:
            first_ref = refs[0]
            if isinstance(first_ref, str) and first_ref.strip():
                return first_ref.strip()

        # Fallback: look for identifier node whose def_node_id contains this node's id
        node_id = node['node_id']
        for n in all_nodes.values():
            if (
                n['type'] == 'identifier'
                and isinstance(n.get('def_node_id'), list)
                and node_id in n['def_node_id']
            ):
                name = n.get('name')
                if isinstance(name, str) and name.strip():
                    return name.strip()

        # Last resort: check 'name' field
        name = node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()

        return None

    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        func_id = func_node['node_id']
        candidates = [
            n for n in all_nodes.values()
            if n['type'] == 'identifier'
               and n.get('scope_node_id') == func_id
               and isinstance(n.get('def_node_id'), list)
               and func_id in n['def_node_id']
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda x: (x['start'][0], x['start'][1]))

        # Find function_declarator to guide selection
        declarators = [
            n for n in all_nodes.values()
            if n['type'] == 'function_declarator'
               and n.get('scope_node_id') == func_id
        ]
        if declarators:
            decl = declarators[0]
            decl_line = decl['start'][0]
            for cand in candidates:
                if decl_line <= cand['start'][0] <= decl['end'][0] + 1:
                    return cand['name']

        return candidates[0]['name'] if candidates else None

