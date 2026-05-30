/** Python 进程桥接 - 管理 Python 后端进程 */

import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'

// CommonJS: __dirname is a global in CommonJS modules

export const HTTP_PORT = 3456

export interface BackendStatus {
  status: 'stopped' | 'starting' | 'running' | 'error'
  pid?: number
  port?: number
  error?: string
}

export class PythonBridge {
  private process: ChildProcess | null = null
  private status: BackendStatus = { status: 'stopped' }
  private listeners: Array<(status: BackendStatus) => void> = []
  public memoryLimit: number = 4096
  public httpHost: string = '127.0.0.1'
  public httpPort: number = 3456

  // Python 脚本路径
  private get pythonScript(): string {
    const isDev = !app.isPackaged
    if (isDev) {
      // 开发环境: 从项目根目录查找
      const devPath = join(__dirname, '../../backend/main.py')
      if (existsSync(devPath)) return devPath
    }

    // 打包环境: 从 extraResources 目录查找
    const prodPath = join(process.resourcesPath, 'backend', 'main.py')
    if (existsSync(prodPath)) return prodPath

    // 回退到开发路径
    return join(__dirname, '../../backend/main.py')
  }

  // 数据库路径
  private get dbPath(): string {
    return join(app.getPath('userData'), 'topoone.db')
  }

  /** 启动 Python 后端 */
  start(): Promise<BackendStatus> {
    return new Promise((resolve) => {
      if (this.status.status === 'running') {
        resolve({ ...this.status })
        return
      }

      // 如果旧进程还在，先清理
      if (this.process && this.process.exitCode === null) {
        try { this.process.kill('SIGKILL') } catch { /* already dead */ }
        this.process = null
      }

      this.status = { status: 'starting' }
      this.notify()

      try {
        // 查找 Python 可执行文件
        const python = this.findPython()
        if (!python) {
          this.status = { status: 'error', error: 'Python not found. Please install Python 3.10+' }
          this.notify()
          resolve({ ...this.status })
          return
        }

        // 读取端口配置 (从 Electron store)
        const dealerPort = 5671  // TODO: 从 store 读取
        const pubPort = 5680
        const httpPort = this.httpPort || HTTP_PORT
        const httpHost = this.httpHost || '0.0.0.0'

        // 启动前检查端口占用 — 如果有残留 Python 进程占用端口，先清理
        this.checkAndKillPortOccupant(dealerPort)

        // 设置 PYTHONPATH，让 Python 能找到 backend/ 目录下的依赖包
        const backendDir = app.isPackaged
          ? join(process.resourcesPath, 'backend')
          : join(__dirname, '../../backend')

        const memoryLimit = this.memoryLimit || 4096
        this.process = spawn(python, [
          this.pythonScript, this.dbPath,
          '--http-port', String(httpPort),
          '--http-host', String(httpHost),
          '--memory-limit', String(memoryLimit),
        ], {
          stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env,
            PYTHONUNBUFFERED: '1',
            PYTHONPATH: backendDir,
            ZMQ_DEALER_PORT: String(dealerPort),
            ZMQ_PUB_PORT: String(pubPort),
          },
        })

        this.process.stdout?.on('data', (data) => {
          console.log('[Python]', data.toString())
        })

        this.process.stderr?.on('data', (data) => {
          console.error('[Python Error]', data.toString())
        })

        this.process.on('exit', (code, signal) => {
          if (code !== 0) {
            this.status = { status: 'error', error: `Process exited with code ${code}` }
          } else {
            this.status = { status: 'stopped' }
          }
          this.process = null
          this.notify()
        })

        this.process.on('error', (error) => {
          this.status = { status: 'error', error: error.message }
          this.notify()
        })

        // 等待后端启动
        setTimeout(() => {
          if (this.process && this.process.exitCode === null) {
            this.status = { status: 'running', pid: this.process.pid, port: 5671 }
            this.notify()
            resolve({ ...this.status })
          }
        }, 2000)

      } catch (error: any) {
        this.status = { status: 'error', error: error.message }
        this.notify()
        resolve({ ...this.status })
      }
    })
  }

  /** 停止 Python 后端 — 先 SIGTERM 优雅退出，超时后 SIGKILL */
  stop(): Promise<BackendStatus> {
    return new Promise((resolve) => {
      if (!this.process) {
        this.status = { status: 'stopped' }
        this.notify()
        resolve({ ...this.status })
        return
      }

      const proc = this.process
      this.process = null

      const onExit = () => {
        this.status = { status: 'stopped' }
        this.notify()
        resolve({ ...this.status })
      }

      // 监听 exit 事件（可能已经注册过，用 once 确保只触发一次）
      proc.once('exit', onExit)

      // SIGTERM 优雅退出
      try { proc.kill('SIGTERM') } catch { /* already dead */ }

      // 5s 超时后 SIGKILL
      const killTimer = setTimeout(() => {
        try {
          if (proc.exitCode === null) {
            console.warn('[PythonBridge] SIGTERM timed out, sending SIGKILL')
            proc.kill('SIGKILL')
          }
        } catch { /* already dead */ }
      }, 5000)

      // 成功退出时清理 timer
      proc.once('exit', () => {
        clearTimeout(killTimer)
      })
    })
  }

  /** 重启 Python 后端 */
  async restart(): Promise<BackendStatus> {
    await this.stop()
    return this.start()
  }

  /** 获取当前状态 */
  getStatus(): BackendStatus {
    if (this.status.status === 'running' && this.process) {
      if (this.process.exitCode !== null) {
        this.status = { status: 'stopped' }
        this.notify()
      }
    }
    return { ...this.status }
  }

  /** 订阅状态变更 */
  onStatusChange(callback: (status: BackendStatus) => void): void {
    this.listeners.push(callback)
  }

  /** 移除状态订阅 */
  offStatusChange(callback: (status: BackendStatus) => void): void {
    const idx = this.listeners.indexOf(callback)
    if (idx >= 0) this.listeners.splice(idx, 1)
  }

  /** 通知所有监听器 */
  private notify(): void {
    const status = { ...this.status }
    this.listeners.forEach(cb => cb(status))
  }

  /** 检查并清理占用端口的残留进程 */
  private checkAndKillPortOccupant(port: number): void {
    try {
      const { execSync } = require('child_process')
      const myPid = this.process?.pid
      const electronPid = process.pid
      if (process.platform === 'linux') {
        const output = execSync(`fuser ${port}/tcp 2>/dev/null`, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim()
        if (output) {
          const pids = output.split(/\s+/).filter(Boolean).map(Number)
          const foreignPids = pids.filter((pid: number) => pid !== myPid && pid !== electronPid)
          if (foreignPids.length > 0) {
            console.warn(`[PythonBridge] Port ${port} occupied by foreign process(es), killing: ${foreignPids.join(', ')}`)
            foreignPids.forEach((pid: number) => {
              try { execSync(`kill -9 ${pid}`, { stdio: ['pipe', 'pipe', 'ignore'] }) } catch {}
            })
            const start = Date.now()
            while (Date.now() - start < 300) { /* busy-wait 300ms */ }
          } else {
            console.log(`[PythonBridge] Port ${port} held by our own backend (PID ${myPid}), skipping kill`)
          }
        }
      } else if (process.platform === 'darwin') {
        const output = execSync(`lsof -ti:${port} 2>/dev/null`, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim()
        if (output) {
          const pids = output.split('\n').filter(Boolean).map(Number)
          const foreignPids = pids.filter((pid: number) => pid !== myPid && pid !== electronPid)
          if (foreignPids.length > 0) {
            console.warn(`[PythonBridge] Port ${port} occupied by foreign process(es), killing: ${foreignPids.join(', ')}`)
            foreignPids.forEach((pid: number) => {
              try { execSync(`kill -9 ${pid}`, { stdio: ['pipe', 'pipe', 'ignore'] }) } catch {}
            })
            const start = Date.now()
            while (Date.now() - start < 300) { /* busy-wait 300ms */ }
          } else {
            console.log(`[PythonBridge] Port ${port} held by our own backend (PID ${myPid}), skipping kill`)
          }
        }
      }
    } catch {
      // fuser/lsof 不可用或无占用进程，忽略
    }
  }

  /** 查找 Python 可执行文件 */
  private findPython(): string | null {
    const candidates = process.platform === 'win32'
      ? ['python', 'python3', 'py']
      : ['python3', 'python']

    // 直接在 PATH 中查找
    for (const cmd of candidates) {
      try {
        const { execSync } = require('child_process')
        const testCmd = process.platform === 'win32'
          ? `where ${cmd}`
          : `which ${cmd}`
        execSync(testCmd, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] })
        return cmd
      } catch {
        // 继续尝试
      }
    }

    // 常见安装路径
    const paths = process.platform === 'win32'
      ? [
          'C:\\Python312\\python.exe',
          'C:\\Python311\\python.exe',
          'C:\\Python310\\python.exe',
        ]
      : [
          '/usr/bin/python3',
          '/usr/local/bin/python3',
          '/usr/bin/python',
          join(process.env.HOME || '', '.pyenv', 'shims', 'python3'),
        ]

    for (const path of paths) {
      if (existsSync(path)) return path
    }

    return null
  }

  /** 清理资源 — 返回 Promise 以便调用方等待 */
  destroy(): Promise<void> {
    this.listeners = []
    return this.stop().then(() => {})
  }
}

// 单例
export const pythonBridge = new PythonBridge()
