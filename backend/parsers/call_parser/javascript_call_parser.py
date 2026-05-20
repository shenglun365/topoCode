# parsers/languages/call_parser/javascript_call_parser.py
"""
JavaScript 调用图提取器

实现 JavaScript/TypeScript 语言的函数/方法调用识别和提取逻辑。

支持的调用语法:
- 函数调用：func()
- 方法调用：obj.method()
- 构造函数调用：new Class()
- 箭头函数调用
- 异步函数调用：await func()
"""
import logging
from typing import Dict, Any, Optional, List
from .extractor_factory import CallGraphExtractor, register_call_extractor

logger = logging.getLogger(__name__)


@register_call_extractor('javascript')
@register_call_extractor('typescript')
class JavaScriptCallExtractor(CallGraphExtractor):
    """JavaScript/TypeScript 函数/方法调用提取器"""

    # 调用表达式类型（包括 JSX 组件调用）
    CALL_EXPRESSION_TYPES = {'call_expression', 'new_expression'}
    # JSX 组件调用类型
    JSX_COMPONENT_TYPES = {'jsx_self_closing_element', 'jsx_element'}
    # 函数定义类型
    FUNCTION_DEFINITION_TYPES = {'function_declaration', 'function_expression', 'arrow_function', 'method_definition'}
    
    def extract(self, proj_id: int, nodes_by_file: Dict[str, Dict[str, Dict]]) -> List[Dict[str, Any]]:
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info(f"🔍 JavaScriptCallExtractor.extract 开始执行")
        logger.info(f"   输入参数：proj_id={proj_id}, nodes_by_file 文件数={len(nodes_by_file)}")


        func_map = self._build_global_function_map_from_ast(nodes_by_file)
        logger.info(f"   全局函数映射大小：{len(func_map)} 个函数")
        
        # 统计节点类型
        total_nodes = 0
        call_expr_nodes = 0
        jsx_nodes = 0
        for file_id, nodes in nodes_by_file.items():
            total_nodes += len(nodes)
            for node in nodes.values():
                node_type = node.get("type", "")
                if node_type == "call_expression":
                    call_expr_nodes += 1
                elif node_type in ["jsx_element", "jsx_self_closing_element"]:
                    jsx_nodes += 1
        
        logger.info(f"   AST 节点统计：总节点={total_nodes}, call_expression={call_expr_nodes}, JSX={jsx_nodes}")

        call_edges = []
        processed_files = 0
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(proj_id, file_id, nodes, func_map)
            call_edges.extend(file_edges)
            processed_files += 1
            
            # 每处理 10 个文件打印进度
            if processed_files % 10 == 0:
                logger.info(f"   进度：{processed_files}/{len(nodes_by_file)} 文件，已提取 {len(call_edges)} 条边")

        logger.info(f"✅ JavaScriptCallExtractor.extract 完成，返回 {len(call_edges)} 条边")
        return call_edges
    
    def _build_global_function_map_from_ast(self, nodes_by_file: Dict[int, Dict[int, Dict]]) -> Dict[str, Dict]:
        """从 AST 节点中构建全局函数映射（不依赖数据库）"""
        func_map = {}
        for file_id, nodes in nodes_by_file.items():
            for node_id, node in nodes.items():
                node_type = node.get("type", "")
                if node_type in self.FUNCTION_DEFINITION_TYPES:
                    func_name = self.extract_function_name(node, nodes)
                    if func_name:
                        func_map[func_name] = {"file_id": file_id, "node_id": node_id}
        return func_map
    
    def _extract_file_calls(self, proj_id: int, file_id: int, nodes: Dict[int, Dict], func_map: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """提取单个文件中的调用关系"""
        call_edges = []
        
        # 统计
        total_nodes = len(nodes)
        call_expr_checked = 0
        jsx_checked = 0
        callee_name_failed = 0
        enclosing_func_failed = 0
        caller_name_failed = 0
        success_count = 0
        
        for node in nodes.values():
            # 处理普通函数调用
            if self.is_call_expression(node):
                call_expr_checked += 1
                
                callee_name = self.extract_callee_name(node, nodes)
                if not callee_name:
                    callee_name_failed += 1
                    continue

                caller_func_node = self.find_enclosing_function(node, nodes)
                # 注意：caller_func_node 可以为 None（全局作用域）
                
                if caller_func_node:
                    caller_name = self.extract_function_name(caller_func_node, nodes)
                    if not caller_name:
                        caller_name_failed += 1
                        continue
                else:
                    # 全局作用域的调用
                    caller_name = "(global)"
                
                edge = self._create_call_edge(proj_id, file_id, node, nodes, func_map, caller_name, caller_func_node)
                if edge:
                    success_count += 1
                    call_edges.append(edge)

            # 处理 JSX 组件调用
            elif self.is_jsx_component(node):
                jsx_checked += 1
                
                edge = self._create_jsx_call_edge(proj_id, file_id, node, nodes, func_map)
                if edge:
                    success_count += 1
                    call_edges.append(edge)
        
        # 打印详细统计（INFO 级别）
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"   📊 文件 {file_id}: call_expression={call_expr_checked}, JSX={jsx_checked}")
        logger.info(f"      成功={success_count}, 失败：callee_name={callee_name_failed}, caller_name={caller_name_failed}, enclosing_func={enclosing_func_failed}")
        
        # 如果失败率高，输出样例
        total_checked = call_expr_checked + jsx_checked
        if total_checked > 0:
            fail_rate = (callee_name_failed + caller_name_failed + enclosing_func_failed) / total_checked
            if fail_rate > 0.5:
                logger.warning(f"   ⚠️  失败率过高：{fail_rate:.2%}，可能原因:")
                logger.warning(f"      1. call_expression 节点没有 refs 或 name 字段")
                logger.warning(f"      2. find_enclosing_function 未找到函数（scope_node_id 链断裂）")
                logger.warning(f"      3. extract_function_name 未能提取函数名")

        return call_edges

    def _create_call_edge(self, proj_id: int, file_id: int, node: Dict, nodes: Dict[int, Dict], func_map: Dict[str, Dict], caller_name: str, caller_func_node: Optional[Dict]) -> Optional[Dict[str, Any]]:
        """创建普通函数调用的边"""
        callee_name = self.extract_callee_name(node, nodes)
        if not callee_name:
            return None
        
        # caller_name 和 caller_func_node 已经由调用方提供
        
        edge = {
            "proj_id": proj_id,
            "symbol_node_type": "call_relation",
            "caller_file_id": file_id,
            "caller_func_name": caller_name,
            "caller_node_id": caller_func_node["node_id"] if caller_func_node else None,
            "callee_name": callee_name,
            "call_site_node_id": node["node_id"],
            "call_site_file_id": file_id,
        }
        
        if callee_name in func_map:
            callee_info = func_map[callee_name]
            edge.update({
                "callee_file_id": callee_info["file_id"],
                "callee_node_id": callee_info["node_id"],
                "callee_type": "function"
            })
        else:
            edge.update({
                "callee_file_id": None,
                "callee_node_id": None,
                "callee_type": "external_or_unknown"
            })
        
        return edge

    def _create_jsx_call_edge(self, proj_id: int, file_id: int, node: Dict, nodes: Dict[int, Dict], func_map: Dict[str, Dict]) -> Optional[Dict[str, Any]]:
        """创建 JSX 组件调用的边"""
        # 从 JSX 节点提取组件名
        component_name = self.extract_jsx_component_name(node, nodes)
        if not component_name:
            return None

        caller_func_node = self.find_enclosing_function(node, nodes)
        if not caller_func_node:
            return None

        caller_name = self.extract_function_name(caller_func_node, nodes)
        if not caller_name:
            return None

        edge = {
            "proj_id": proj_id,
            "symbol_node_type": "call_relation",
            "caller_file_id": file_id,
            "caller_func_name": caller_name,
            "caller_node_id": caller_func_node["node_id"],
            "callee_name": component_name,
            "call_site_node_id": node["node_id"],
            "call_site_file_id": file_id,
            "callee_type": "jsx_component",
        }

        # 检查是否在全局函数映射中（React 组件通常是函数）
        if component_name in func_map:
            callee_info = func_map[component_name]
            edge.update({
                "callee_file_id": callee_info["file_id"],
                "callee_node_id": callee_info["node_id"],
            })
        else:
            edge.update({
                "callee_file_id": None,
                "callee_node_id": None,
            })

        return edge
    
    def is_call_expression(self, node: Dict) -> bool:
        return node.get("type") in self.CALL_EXPRESSION_TYPES

    def is_jsx_component(self, node: Dict) -> bool:
        """判断是否为 JSX 组件调用"""
        return node.get("type") in self.JSX_COMPONENT_TYPES

    def extract_jsx_component_name(self, jsx_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从 JSX 节点提取组件名
        
        JSX 组件名通常是大写字母开头的标识符
        例如：<Component /> 或 <Component>...</Component>
        
        Args:
            jsx_node: JSX 节点
            all_nodes: 所有 AST 节点
            
        Returns:
            组件名
        """
        refs = jsx_node.get("refs", [])
        if refs:
            # JSX 组件名通常是第一个 ref
            component_name = refs[0]
            # 组件名通常是大写字母开头（React 约定）
            if component_name and len(component_name) > 0 and component_name[0].isupper():
                return component_name

        # 回退：使用 name 字段
        return jsx_node.get("name")
    
    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """从调用节点提取被调用函数名"""
        refs = call_node.get("refs", [])
        name = call_node.get("name")
        node_type = call_node.get("type")
        node_id = call_node.get("node_id")
        
        # 调试日志：检查 call_expression 节点的 refs 和 name
        if node_type == "call_expression" and refs:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"   📍 call_expression node_id={node_id}: refs={refs[:5]}..., name={name}")
        
        if refs and len(refs) > 0:
            name = refs[0]
            if name and len(name) > 0:  # 确保非空
                return name.split(".")[-1] if "." in name else name
        return call_node.get("name")
    
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """查找包含该节点的最近函数"""
        scope = node.get("scope_node_id")
        node_id = node.get("node_id")
        node_type = node.get("type")
        depth = 0
        max_depth = 20  # 防止无限循环
        
        while scope is not None and scope != 1 and scope in all_nodes and depth < max_depth:
            depth += 1
            parent_node = all_nodes[scope]
            parent_type = parent_node.get("type")
            
            if parent_type in self.FUNCTION_DEFINITION_TYPES:
                # 找到函数
                return parent_node
            
            scope = parent_node.get("scope_node_id")
        
        # 未找到函数，返回 None（表示在全局作用域）
        # 注意：scope_node_id=1 或遍历结束都表示在全局作用域
        # 这是正常的，调用可以发生在全球作用域
        return None
    
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """从函数节点提取函数名

        策略:
        1. 优先使用 name 字段
        2. 回退: 查找同一作用域内的 identifier/property_identifier 子节点
        3. 最后回退: 使用 node_id 作为占位符（而非误取 refs[0]）
        """
        name = func_node.get("name")

        if not name:
            # 查找同一作用域内的 identifier 子节点（函数名通常作为直接子节点）
            func_id = func_node.get("node_id")
            for node in all_nodes.values():
                if node.get("scope_node_id") == func_id:
                    if node.get("type") in ("identifier", "property_identifier", "method_name"):
                        name = node.get("name")
                        if name:
                            break

        if not name:
            # 最后回退: 使用节点类型 + node_id 作为占位符
            name = f"func_{func_node.get('node_id', 'unknown')}"

        return name
