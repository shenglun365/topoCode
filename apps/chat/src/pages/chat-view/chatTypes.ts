/**
 * useChat · 跨域依赖袋（MS6-W3 机械抽取）。
 * 刻意宽松(any)：各域按声明顺序惰性互引(computed 天然惰性)。
 */
export interface ChatDeps { [k: string]: any }
