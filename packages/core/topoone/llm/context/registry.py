from .assembly import ContextAssembler
from .ingredients.community_info import CommunityInfoIngredient
from .ingredients.file_list import FileListIngredient
from .ingredients.directory_tree import DirectoryTreeIngredient
from .ingredients.exported_symbols import ExportedSymbolsIngredient
from .ingredients.file_centrality import FileCentralityIngredient
from .ingredients.edge_relations import EdgeRelationsIngredient
from .ingredients.parent_chain import ParentChainIngredient
from .ingredients.import_external import ImportExternalIngredient
from .ingredients.tech_stack import TechStackIngredient
from .ingredients.test_coverage import TestCoverageIngredient
from .ingredients.entry_points import EntryPointsIngredient
from .ingredients.file_metadata import FileMetadataIngredient
from .recipes import (
    RECIPE_COMPONENT_ANALYSIS,
    RECIPE_COMPONENT_ANALYSIS_AGENTIC,
    RECIPE_ARCH_COMMUNITY,
    RECIPE_ARCH_OVERVIEW,
    RECIPE_FILE_SUMMARY,
)


def create_assembler() -> ContextAssembler:
    a = ContextAssembler()
    for cls in [
        CommunityInfoIngredient,
        FileListIngredient,
        DirectoryTreeIngredient,
        ExportedSymbolsIngredient,
        FileCentralityIngredient,
        EdgeRelationsIngredient,
        ParentChainIngredient,
        ImportExternalIngredient,
        TechStackIngredient,
        TestCoverageIngredient,
        EntryPointsIngredient,
        FileMetadataIngredient,
    ]:
        a.register(cls())
    return a


# 全局单例
_assembler: ContextAssembler | None = None


def get_assembler() -> ContextAssembler:
    global _assembler
    if _assembler is None:
        _assembler = create_assembler()
    return _assembler
