/**
 * 语义图谱视图 · 跨域依赖袋与类型（MS6-W2）。
 * WsDeps 刻意宽松(any)：四域按声明顺序惰性互引(computed 天然惰性)。
 */
export interface WsDeps { [k: string]: any }

/** 图谱资源 tab 定义(由外部资产列表/组件列表打开)。 */
export interface GraphTabDef {
  id: string
  kind: 'all' | 'comp' | 'asset' | 'file' | 'logic'
  title: string
  compId?: string
  assetId?: string
  /** kind='file'：锚定该文件的资产子图。 */
  fileId?: string
  /** kind='logic'：逻辑视图 id + 成员快照(打开时更新；视图=成员实现资产子图+调用依赖边)。 */
  viewId?: string
  members?: string[]
}
