/** MCP 进程桥接 — 管理 MCP Server Python 子进程生命周期 */

import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'

type MCPState = 'stopped' | 'starting' | 'running' | 'error'

export interface MCPStatus {
  state: MCPState
  pid?: number
  port?: number
  error?: string
}

export class MCPManager {
  private process: ChildProcess | null = null
  private _state: MCPState = 'stopped'
  private _port: number = 0
  private listeners: Array<(status: MCPStatus) => void> = []

  get state() { return this._state }
  get port() { return this._port }

  private get pythonScript(): string {
    const isDev = !app.isPackaged
    if (isDev) {
      const devPath = join(__dirname, '../backend-core/mcp_server/__main__.py')
      if (existsSync(devPath)) return devPath
    }
    const prodPath = join(process.resourcesPath, 'backend-core', 'mcp_server', '__main__.py')
    if (existsSync(prodPath)) return prodPath
    return join(__dirname, '../backend-core/mcp_server/__main__.py')
  }

  onStatusChange(cb: (status: MCPStatus) => void): () => void {
    this.listeners.push(cb)
    return () => { this.listeners = this.listeners.filter(l => l !== cb) }
  }

  private notify() {
    const status: MCPStatus = { state: this._state }
    if (this.process?.pid) status.pid = this.process.pid
    if (this._port) status.port = this._port
    if (this._state === 'error') status.error = 'MCP Server process exited unexpectedly'
    for (const cb of this.listeners) cb(status)
  }

  async start(projectRoot: string, zmqDealerPort: number = 0, logLevel: string = 'WARN'): Promise<void> {
    if (this._state === 'running') return
    this._state = 'starting'
    this.notify()

    const script = this.pythonScript
    if (!existsSync(script)) {
      this._state = 'error'
      this.notify()
      throw new Error(`MCP script not found: ${script}`)
    }

    const args = [
      script,
      '--project-root', projectRoot,
      '--log-level', logLevel,
    ]
    if (zmqDealerPort > 0) {
      args.push('--zmq-dealer-port', String(zmqDealerPort))
    }

    const pythonPath = process.platform === 'win32' ? 'python' : 'python3'
    this.process = spawn(pythonPath, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    })

    this.process.on('spawn', () => {
      this._state = 'running'
      this.notify()
    })

    this.process.on('exit', (code) => {
      this._state = code === 0 ? 'stopped' : 'error'
      this.process = null
      this.notify()
    })

    this.process.on('error', (_err) => {
      this._state = 'error'
      this.notify()
    })

    // Read stdout for port notification
    this.process.stdout?.on('data', (data: Buffer) => {
      const text = data.toString()
      const portMatch = text.match(/listening on port (\d+)/i)
      if (portMatch) this._port = parseInt(portMatch[1], 10)
    })

    this.process.stderr?.on('data', (data: Buffer) => {
      // stderr may contain log messages
    })
  }

  stop(): void {
    if (this.process) {
      this.process.kill('SIGTERM')
      setTimeout(() => {
        if (this.process) this.process.kill('SIGKILL')
      }, 5000)
    }
    this._state = 'stopped'
    this.process = null
    this.notify()
  }
}
