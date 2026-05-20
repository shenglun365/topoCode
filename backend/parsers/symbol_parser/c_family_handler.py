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
        import json

        func_id = func_node['node_id']

        # 策略 1: 查找 def_node_id 匹配的 identifier（兼容 list 和字符串格式）
        candidates = []
        for n in all_nodes.values():
            if n['type'] == 'identifier' and n.get('scope_node_id') == func_id:
                did = n.get('def_node_id')
                # 兼容 list 格式
                if isinstance(did, list) and func_id in did:
                    candidates.append(n)
                # 兼容字符串格式 "[5]"
                elif isinstance(did, str) and did.startswith('['):
                    try:
                        did_list = json.loads(did)
                        if func_id in did_list:
                            candidates.append(n)
                    except (json.JSONDecodeError, TypeError):
                        pass

        if candidates:
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

            return candidates[0]['name']

        # 策略 2: 同一作用域内的所有 identifier，按位置排序取第一个
        all_identifiers = [
            n for n in all_nodes.values()
            if n['type'] == 'identifier' and n.get('scope_node_id') == func_id
        ]
        if all_identifiers:
            all_identifiers.sort(key=lambda x: (x['start'][0], x['start'][1]))
            return all_identifiers[0].get('name')

        return None

    def extract_class_name(self, class_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        """从 class_specifier/struct_specifier 提取类名"""
        class_id = class_node.get('node_id')

        # 策略 1: 查找同一作用域内的 identifier 子节点
        for node in all_nodes.values():
            if (node.get('scope_node_id') == class_id and
                    node.get('type') == 'type_identifier' and
                    node.get('name')):
                return node['name']

        # 策略 2: 使用 name 字段
        name = class_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()

        return None

    def extract_method_name(self, method_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        """从 method_definition 提取方法名（复用函数名提取逻辑）"""
        return self.extract_function_name(method_node, all_nodes)

