/** Python 进程桥接 - 管理 Python 后端进程 */

import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import { join, delimiter } from 'path'
import { existsSync } from 'fs'

export const HTTP_PORT = 3456

type BridgeState = 'stopped' | 'starting' | 'running' | 'stopping' | 'error'

export interface BackendStatus {
  status: BridgeState
  pid?: number
  port?: number
  error?: string
}

export class PythonBridge {
  private process: ChildProcess | null = null
  private _state: BridgeState = 'stopped'
  private listeners: Array<(status: BackendStatus) => void> = []
  public memoryLimit: number = 4096
  public httpHost: string = '127.0.0.1'
  public httpPort: number = 3456

  private get state(): BridgeState { return this._state }
  private setState(s: BridgeState): void {
    this._state = s
    this.notify()
  }

  // Python 脚本路径
  private get pythonScript(): string {
    const isDev = !app.isPackaged
    if (isDev) {
      const devPath = join(__dirname, '../backend-core/main.py')
      if (existsSync(devPath)) return devPath
    }
    const prodPath = join(process.resourcesPath, 'backend-core', 'main.py')
    if (existsSync(prodPath)) return prodPath
    return join(__dirname, '../backend-core/main.py')
  }

  // 数据库路径
  private get dbPath(): string {
    return join(app.getPath('userData'), 'topoone.db')
  }

  // 插件目录路径（用户数据目录）
  private get pluginsDir(): string {
    return join(app.getPath('userData'), 'plugins')
  }

  // 内置插件目录路径（打包分发）
  private get bundledPluginsDir(): string {
    if (app.isPackaged) {
      return join(process.resourcesPath, 'plugins')
    }
    const distDir = join(__dirname, '../dist-plugins')
    if (existsSync(distDir)) {
      return distDir
    }
    return join(__dirname, '../plugins')
  }

  // 内置模块目录路径（打包分发）
  private get modulesDir(): string {
    return join(app.getPath('userData'), 'modules')
  }

  // private get bundledModulesDir(): string {
  //   if (app.isPackaged) {
  //     return join(process.resourcesPath, 'modules')
  //   }
  //   const distDir = join(__dirname, '../dist-modules')
  //   if (existsSync(distDir)) {
  //     return distDir
  //   }
  //   return join(__dirname, '../dist-modules')
  // }

  /** 启动 Python 后端 */
  async start(): Promise<BackendStatus> {
    if (this.state === 'running') {
      return this.getStatus()
    }
    if (this.state === 'starting' || this.state === 'stopping') {
      throw new Error(`Cannot start while ${this.state}`)
    }

    this.setState('starting')

    try {
      const pythonResult = this.findPython()
      if (!pythonResult) {
        this.setState('error')
        return { status: 'error', error: 'Python 3.10+ not found' }
      }

      const python = pythonResult.path

      // 验证版本
      const { execSync } = require('child_process')
      const versionOutput = execSync(`"${python}" --version`, { encoding: 'utf-8', timeout: 15000 }).trim()
      const match = versionOutput.match(/Python (\d+)\.(\d+)/)
      if (match) {
        const major = parseInt(match[1], 10), minor = parseInt(match[2], 10)
        if (major < 3 || (major === 3 && minor < 10)) {
          this.setState('error')
          return { status: 'error', error: `Python 3.10+ required, got ${versionOutput}` }
        }
      }

      const dealerPort = parseInt(process.env.ZMQ_DEALER_PORT || '5671', 10)
      const pubPort = parseInt(process.env.ZMQ_PUB_PORT || '5680', 10)
      const httpPort = this.httpPort || HTTP_PORT
      const httpHost = this.httpHost || '0.0.0.0'

      this.checkAndKillPortOccupant(dealerPort)

      const backendDir = app.isPackaged
        ? join(process.resourcesPath, 'backend-core')
        : join(__dirname, '../backend-core')

      const spawnOptions: any = {
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          PYTHONDONTWRITEBYTECODE: '1',
          PYTHONPATH: [backendDir, this.bundledPluginsDir, this.pluginsDir].join(delimiter),
          ZMQ_DEALER_PORT: String(dealerPort),
          ZMQ_PUB_PORT: String(pubPort),
          TOPOCODE_MODULES_DIR: this.modulesDir,
          TOPOCODE_MODULE_REGISTRY: process.env.TOPOCODE_MODULE_REGISTRY || 'https://registry.topocode.dev/v1/registry.json',
        },
      }
      if (process.platform === 'win32') spawnOptions.shell = true

      this.process = spawn(python, [
        this.pythonScript, this.dbPath,
        '--http-port', String(httpPort),
        '--http-host', String(httpHost),
        '--memory-limit', String(this.memoryLimit),
      ], spawnOptions)

      this.process.stdout?.on('data', (data) => {
        console.error('[Python]', data.toString())
      })
      this.process.stderr?.on('data', (data) => {
        console.error('[Python Error]', data.toString())
      })

      this.process.on('exit', (code, signal) => {
        console.error(`[PythonBridge] Process exited code=${code} signal=${signal}`)
        this.process = null
        if (this.state !== 'stopping') {
          this.setState(code !== 0 ? 'error' : 'stopped')
        } else {
          this.setState('stopped')
        }
      })

      this.process.on('error', (error) => {
        console.error('[PythonBridge] Spawn error:', error.message)
        this.process = null
        this.setState('error')
      })

      // 等待后端启动 — 最多 10s，然后做健康检查
      await new Promise<void>((resolve, reject) => {
        let waited = 0
        const check = setInterval(() => {
          waited += 1000
          if (this.process?.exitCode !== null && this.process?.exitCode !== undefined) {
            clearInterval(check)
            reject(new Error(`Process exited with code ${this.process.exitCode}`))
          } else if (waited >= 10000) {
            clearInterval(check)
            resolve()
          }
        }, 1000)
      })

      this.setState('running')
      return { status: 'running', pid: this.process?.pid, port: dealerPort }

    } catch (error: any) {
      this.setState('error')
      return { status: 'error', error: error.message }
    }
  }

  /** 健康检查 — ZMQ ping */
  async healthCheck(): Promise<boolean> {
    if (this.state !== 'running') return false
    try {
      const { zmqRouter } = await import('./zmq-router')
      return await zmqRouter.ping(3000)
    } catch {
      return false
    }
  }

  /** 停止 Python 后端 */
  async stop(): Promise<BackendStatus> {
    if (!this.process) {
      this.setState('stopped')
      return { status: 'stopped' }
    }

    this.setState('stopping')
    const proc = this.process
    this.process = null

    return new Promise((resolve) => {
      const onExit = () => {
        this.setState('stopped')
        resolve({ status: 'stopped' })
      }
      proc.once('exit', onExit)

      if (process.platform === 'win32') {
        try {
          const { execSync } = require('child_process')
          execSync(`taskkill /F /PID ${proc.pid} 2>nul`, { stdio: 'ignore' })
        } catch { /* already dead */ }
      } else {
        try { proc.kill('SIGTERM') } catch { /* already dead */ }
        const killTimer = setTimeout(() => {
          try {
            if (proc.exitCode === null) {
              console.warn('[PythonBridge] SIGTERM timed out, sending SIGKILL')
              proc.kill('SIGKILL')
            }
          } catch { /* already dead */ }
        }, 5000)
        proc.once('exit', () => clearTimeout(killTimer))
      }
    })
  }

  async restart(): Promise<BackendStatus> {
    await this.stop()
    return this.start()
  }

  getStatus(): BackendStatus {
    const s: BackendStatus = { status: this.state }
    if (this.process) s.pid = this.process.pid
    return s
  }

  onStatusChange(callback: (status: BackendStatus) => void): void {
    this.listeners.push(callback)
  }

  offStatusChange(callback: (status: BackendStatus) => void): void {
    const idx = this.listeners.indexOf(callback)
    if (idx >= 0) this.listeners.splice(idx, 1)
  }

  private notify(): void {
    const status = { status: this.state }
    this.listeners.forEach(cb => cb(status))
  }

  private checkAndKillPortOccupant(port: number): void {
    try {
      const { execSync } = require('child_process')
      const myPid = this.process?.pid
      const electronPid = process.pid

      let output = ''
      if (process.platform === 'win32') {
        output = execSync(
          `netstat -ano | findstr "LISTENING" | findstr ":${port} "`,
          { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'], timeout: 5000 }
        ).trim()
      } else if (process.platform === 'darwin') {
        output = execSync(`lsof -ti:${port} 2>/dev/null`, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim()
      } else {
        output = execSync(`fuser ${port}/tcp 2>/dev/null`, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim()
      }

      if (!output) return

      let pids: number[] = []
      if (process.platform === 'win32') {
        pids = output.split('\n').map(line => {
          const parts = line.trim().split(/\s+/)
          return parseInt(parts[parts.length - 1], 10)
        }).filter(pid => !isNaN(pid))
      } else if (process.platform === 'darwin') {
        pids = output.split('\n').filter(Boolean).map(Number)
      } else {
        pids = output.split(/\s+/).filter(Boolean).map(Number)
      }

      const foreignPids = pids.filter(pid => pid !== myPid && pid !== electronPid)
      if (foreignPids.length > 0) {
        console.warn(`[PythonBridge] Port ${port} occupied, killing: ${foreignPids.join(', ')}`)
        foreignPids.forEach(pid => {
          try {
            execSync(process.platform === 'win32' ? `taskkill /F /PID ${pid}` : `kill -9 ${pid}`, { stdio: 'ignore' })
          } catch {}
        })
        const start = Date.now()
        while (Date.now() - start < 300) { /* busy-wait */ }
      }
    } catch { /* ignore */ }
  }

  private findPython(): { path: string; version: string } | null {
    const candidates = process.platform === 'win32' ? ['python', 'python3', 'py'] : ['python3', 'python']
    const candidatePaths: string[] = []

    for (const cmd of candidates) {
      try {
        const { execSync } = require('child_process')
        const testCmd = process.platform === 'win32' ? `where ${cmd}` : `which ${cmd}`
        const output = execSync(testCmd, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim()
        const lines = output.split('\n').map((l: string) => l.trim()).filter(Boolean)
        for (const line of lines) {
          if (process.platform === 'win32' && line.includes('Microsoft\\WindowsApps')) continue
          if (!candidatePaths.includes(line)) candidatePaths.push(line)
        }
      } catch { /* continue */ }
    }

    const homeDir = process.env.HOME || process.env.USERPROFILE || ''
    const fallbackPaths = process.platform === 'win32'
      ? [
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python313\\python.exe`,
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`,
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python311\\python.exe`,
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python310\\python.exe`,
          'C:\\Python313\\python.exe', 'C:\\Python312\\python.exe', 'C:\\Python311\\python.exe', 'C:\\Python310\\python.exe',
        ]
      : ['/usr/bin/python3', '/usr/local/bin/python3', '/opt/homebrew/bin/python3', '/usr/bin/python',
         join(homeDir, '.pyenv', 'shims', 'python3')]

    for (const p of fallbackPaths) {
      if (!candidatePaths.includes(p)) candidatePaths.push(p)
    }

    for (const pythonPath of candidatePaths) {
      try {
        if (!existsSync(pythonPath)) continue
        const { execSync } = require('child_process')
        const versionOutput = execSync(`"${pythonPath}" --version`, { encoding: 'utf-8', timeout: 15000 }).trim()
        const match = versionOutput.match(/Python (\d+)\.(\d+)/)
        if (match) {
          const major = parseInt(match[1], 10), minor = parseInt(match[2], 10)
          if (major >= 3 && minor >= 10) return { path: pythonPath, version: versionOutput }
        }
      } catch { /* continue */ }
    }
    return null
  }

  destroy(): Promise<void> {
    this.listeners = []
    return this.stop().then(() => {})
  }
}

export const pythonBridge = new PythonBridge()
