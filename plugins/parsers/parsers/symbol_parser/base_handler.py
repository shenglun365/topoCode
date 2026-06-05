from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

class LanguageHandler(ABC):
    @property
    @abstractmethod
    def preproc_node_types(self) -> List[str]:
        pass

    @abstractmethod
    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        pass

    @abstractmethod
    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        pass
