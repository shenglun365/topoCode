/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, any>
  export default component
}

declare module 'plantuml-encoder' {
  const encoder: { encode: (text: string) => string }
  export default encoder
}

declare module 'markdown-it'
