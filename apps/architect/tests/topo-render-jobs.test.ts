/**
 * plantuml 异步渲染链路(renderPlantumlJobs)特征测试：
 * POST /api/topo/plantuml/jobs 提交 → 轮询 GET → done 回填 svg；
 * cached 直返(零轮询)；error 上抛；404 幂等重提交。后端契约: 裸 dict。
 */
import { describe, expect, it, vi } from 'vitest'

const SVG = '<svg id="pj">ok</svg>'

type Route = { status: number; body: unknown }

function installFetch(routes: Array<(url: string, method: string, body: string) => Route | null>) {
  const calls: Array<{ url: string; method: string; body: string }> = []
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input instanceof Request ? input.url : input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = typeof init?.body === 'string' ? init.body : ''
    calls.push({ url, method, body })
    for (const h of routes) {
      const r = h(url, method, body)
      if (r) return new Response(JSON.stringify(r.body), { status: r.status, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response('{}', { status: 404 })
  }) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

/** jobs 路径判定: POST 端点 .../jobs 与轮询 .../jobs/{id} 都命中 */
const isJobs = (url: string): boolean => new URL(url, 'http://x').pathname.includes('/plantuml/jobs')

async function loadRenderDiagram() {
  return (await import('@/services/topo-render')).renderDiagram
}

function jobPost(jobId: string, status: string, svg?: string): Route {
  return {
    status: 200,
    body: { jobId, status, ...(status === 'done' ? { svg } : {}), ...(status === 'error' ? { error: 'boom' } : {}) },
  }
}

describe('renderDiagram × plantuml jobs 协议', () => {
  // 唯一源文避免模块级内存缓存串扰
  const code = (tag: string) => `@startuml\n${tag}\n@enduml`

  it('queued → 轮询 → done 回填 svg', async () => {
    const render = await loadRenderDiagram()
    let n = 0
    installFetch([
      (url, method) => {
        if (!isJobs(url)) return null
        if (method === 'POST') return jobPost('j-a', 'queued')
        n += 1
        return jobPost('j-a', n >= 2 ? 'done' : 'running', SVG)
      },
    ])
    const svg = await render('plantuml', code('p1'))
    expect(svg).toBe(SVG)
  })

  it('提交即 done(cached) 直接返回，零轮询', async () => {
    const render = await loadRenderDiagram()
    let polls = 0
    installFetch([
      (url, method) => {
        if (!isJobs(url)) return null
        if (method === 'POST') return jobPost('j-b', 'done', SVG + 'cached')
        polls += 1
        return jobPost('j-b', 'running')
      },
    ])
    const svg = await render('plantuml', code('p2'))
    expect(svg).toContain('cached')
    expect(polls).toBe(0)
  })

  it('error 状态上抛', async () => {
    const render = await loadRenderDiagram()
    installFetch([
      (url, method) => {
        if (!isJobs(url)) return null
        return jobPost('j-c', method === 'POST' ? 'queued' : 'error')
      },
    ])
    await expect(render('plantuml', code('p3'))).rejects.toThrow('boom')
  })

  it('轮询 404 → 幂等重提交后完成', async () => {
    const render = await loadRenderDiagram()
    const calls: string[] = []
    let submitted = 0
    let polls = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input instanceof Request ? input.url : input)
      const method = (init?.method ?? 'GET').toUpperCase()
      calls.push(`${method} ${url.slice(-36)}`)
      const path = new URL(url, 'http://x').pathname
      if (!path.includes('/plantuml/jobs')) return new Response('{}', { status: 404 })
      if (method === 'POST') {
        submitted += 1
        return new Response(JSON.stringify({ jobId: `j-${submitted}`, status: 'queued' }), { status: 200 })
      }
      polls += 1
      if (polls === 1) return new Response('{}', { status: 404 })
      return new Response(JSON.stringify({ jobId: 'j-2', status: 'done', svg: SVG + 'resub' }), { status: 200 })
    }) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const svg = await render('plantuml', code('p4'))
    expect(svg).toContain('resub')
    expect(submitted).toBe(2)
  })
})
