import { useI18n } from 'vue-i18n'
import { useArchTagStore } from '@/stores/tag-store'

/** 内置类型标签维度。 */
export interface TagGroup {
  key: string
  mode: 'single' | 'multi'
  tags: string[]
}

export const TAG_GROUPS: TagGroup[] = [
  { key: 'pri', mode: 'single', tags: ['pri:must', 'pri:should', 'pri:could', 'pri:wont'] },
  { key: 'type', mode: 'single', tags: ['type:epic', 'type:feature', 'type:story', 'type:task'] },
  { key: 'source', mode: 'multi', tags: ['source:product', 'source:tech', 'source:config'] },
  { key: 'attr', mode: 'multi', tags: ['attr:functional', 'attr:performance', 'attr:security', 'attr:usability', 'attr:maintainability'] },
  { key: 'project', mode: 'single', tags: ['project:prototype', 'project:iterative', 'project:critical'] },
  { key: 'value', mode: 'single', tags: ['value:high', 'value:medium', 'value:low'] },
  { key: 'risk', mode: 'single', tags: ['risk:high', 'risk:medium', 'risk:low'] },
]

const TAG_COLOR: Record<string, string> = {
  pri: 'bg-ctp-red/15 text-ctp-red',
  type: 'bg-ctp-sky/15 text-ctp-sky',
  source: 'bg-ctp-mauve/15 text-ctp-mauve',
  attr: 'bg-ctp-teal/15 text-ctp-teal',
  project: 'bg-ctp-peach/15 text-ctp-peach',
  value: 'bg-ctp-green/15 text-ctp-green',
  risk: 'bg-ctp-blue/15 text-ctp-blue',
}

/** 类型标签展示/分组的共享逻辑(表单 + 多选弹窗共用)。 */
export function useTagTaxonomy() {
  const { t } = useI18n()
  const tagStore = useArchTagStore()
  if (!tagStore.groups.length) tagStore.load()

  function tagColorOf(tag: string): string {
    const ct = tagStore.byId(tag)
    if (ct) return TAG_COLOR[ct.groupKey] ?? 'bg-ctp-lavender/15 text-ctp-lavender'
    return TAG_COLOR[tag.split(':')[0]] ?? 'bg-ctp-surface0 text-ctp-subtext0'
  }

  function defaultTagLabel(tag: string): string {
    const [p, s] = tag.split(':')
    const key = `requirement.form.tagLabel.${p}.${s}`
    const label = t(key)
    return label === key ? tag : label
  }

  function tagLabelOf(tag: string): string {
    const ct = tagStore.byId(tag)
    return ct ? ct.label : defaultTagLabel(tag)
  }

  function groupKeyOf(tag: string): TagGroup | undefined {
    const ct = tagStore.byId(tag)
    if (ct) return TAG_GROUPS.find((g) => g.key === ct.groupKey) ?? { key: ct.groupKey, mode: 'multi', tags: [] }
    return TAG_GROUPS.find((g) => g.tags.includes(tag))
  }

  return { TAG_GROUPS, tagColorOf, defaultTagLabel, tagLabelOf, groupKeyOf }
}
