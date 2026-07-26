import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return code
    },
  })
)

marked.setOptions({
  gfm: true,
  breaks: true,
})

export function renderMarkdown(text: string): string {
  if (!text) return ''
  return marked.parse(text) as string
}

export function renderDocMarkdown(text: string): string {
  if (!text) return ''
  let html = renderMarkdown(text)
  html = html.replace(
    /<a href="##community:(\w+):([\w-]+)">/g,
    '<a href="#" class="comm-link" data-et="$1" data-cid="$2">'
  )
  return html
}

export function renderDiagrams(container: HTMLElement): void {
  // Mermaid
  container.querySelectorAll('code.language-mermaid').forEach((block) => {
    const pre = block.parentElement
    if (!pre || pre.tagName !== 'PRE') return
    const code = block.textContent?.trim()
    if (!code) return
    const wrapper = document.createElement('div')
    wrapper.className = 'mermaid'
    wrapper.textContent = code
    pre.parentNode?.replaceChild(wrapper, pre)
  })
}
