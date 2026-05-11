from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

class LanguageParser(ABC):
    @abstractmethod
    def is_function_definition(self, node: Dict) -> bool:
        pass

    @abstractmethod
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        pass

    @abstractmethod
    def is_call_expression(self, node: Dict) -> bool:
        pass

    @abstractmethod
    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        pass

    @abstractmethod
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[int]:
        pass
