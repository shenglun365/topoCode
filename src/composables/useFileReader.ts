import { ref } from 'vue'
import type { FileTreeNode } from '@/types/ipc'

export function useFileReader() {
  const content = ref('')
  const loading = ref(false)

  async function readFile(node: FileTreeNode, rootPath: string): Promise<{ success: true } | { success: false; error: string }> {
    if (!node.path || node.type === 'directory') {
      return { success: false, error: 'directory' }
    }

    loading.value = true
    content.value = ''

    try {
      if (window.api && window.api.fs) {
        const fullPath = rootPath + '/' + node.path
        const result = await window.api.fs.readFile(fullPath)
        content.value = result
        return { success: true }
      }
      return { success: false, error: 'electronOnly' }
    } catch (err: any) {
      return { success: false, error: err.message || 'readFailed' }
    } finally {
      loading.value = false
    }
  }

  return { content, loading, readFile }
}
