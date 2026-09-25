/**
 * 语义图谱视图 · 跨域依赖袋与类型（MS6-W2）。
 * WsDeps 刻意宽松(any)：四域按声明顺序惰性互引(computed 天然惰性)。
 */
export interface WsDeps { [k: string]: any }
