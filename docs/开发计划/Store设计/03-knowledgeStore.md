# stores/knowledge.ts

> Phase 3: 知识库状态管理

```typescript
import { defineStore } from 'pinia';

interface DimensionTag {
  id: string;
  label: string;
  dimensionId: string;
}

interface Dimension {
  id: string;
  name: string;
  icon: string;
  tags: DimensionTag[];
}

interface KnowledgeDoc {
  id: string;
  title: string;
  description: string;
  type: 'project' | 'document';
  status: 'draft' | 'pending' | 'reviewed';
  dimensions: Record<string, string[]>;  // dimensionId → tagIds
  favorite: boolean;
  pinned: boolean;
  createdAt: number;
  updatedAt: number;
}

interface GraphNode {
  id: string;
  type: 'module' | 'class' | 'function' | 'knowledge';
  label: string;
  x?: number;
  y?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  type: 'dependency' | 'reference';
}

export const useKnowledgeStore = defineStore('knowledge', () => {
  // ---- State ----
  const docs = ref<KnowledgeDoc[]>([]);
  const selectedDoc = ref<KnowledgeDoc | null>(null);
  const docMode = ref<'edit' | 'view' | 'preview'>('view');
  const dimensions = ref<Dimension[]>([]);
  const selectedFilterTags = ref<Map<string, string[]>>(new Map());  // dimId → tagIds
  const graphNodes = ref<GraphNode[]>([]);
  const graphEdges = ref<GraphEdge[]>([]);
  const selectedGraphNode = ref<string | null>(null);
  const activeKbTab = ref<'graph' | 'categories' | 'documents'>('graph');

  // ---- Getters ----
  const filteredDocs = computed(() => {
    let result = docs.value;
    selectedFilterTags.value.forEach((tagIds, dimId) => {
      if (tagIds.length > 0) {
        result = result.filter(doc =>
          doc.dimensions[dimId]?.some(tagId => tagIds.includes(tagId))
        );
      }
    });
    return result;
  });

  const docById = (id: string) =>
    computed(() => docs.value.find(d => d.id === id) ?? null);

  // ---- Actions ----
  function setDocs(list: KnowledgeDoc[]) {
    docs.value = list;
  }

  function selectDoc(doc: KnowledgeDoc | null) {
    selectedDoc.value = doc;
    docMode.value = 'view';
  }

  function setDocMode(mode: 'edit' | 'view' | 'preview') {
    docMode.value = mode;
  }

  function setDimensions(dims: Dimension[]) {
    dimensions.value = dims;
  }

  function toggleFilterTag(dimensionId: string, tagId: string) {
    const current = selectedFilterTags.value.get(dimensionId) ?? [];
    if (current.includes(tagId)) {
      selectedFilterTags.value.set(dimensionId, current.filter(t => t !== tagId));
    } else {
      selectedFilterTags.value.set(dimensionId, [...current, tagId]);
    }
  }

  function clearFilters() {
    selectedFilterTags.value = new Map();
  }

  function setGraphData(nodes: GraphNode[], edges: GraphEdge[]) {
    graphNodes.value = nodes;
    graphEdges.value = edges;
  }

  function selectGraphNode(nodeId: string | null) {
    selectedGraphNode.value = nodeId;
  }

  function setActiveKbTab(tab: 'graph' | 'categories' | 'documents') {
    activeKbTab.value = tab;
  }

  return {
    docs, selectedDoc, docMode, dimensions,
    selectedFilterTags, graphNodes, graphEdges,
    selectedGraphNode, activeKbTab,
    filteredDocs, docById,
    setDocs, selectDoc, setDocMode, setDimensions,
    toggleFilterTag, clearFilters, setGraphData,
    selectGraphNode, setActiveKbTab,
  };
});
```
