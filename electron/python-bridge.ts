/** Python 进程桥接 - 管理 Python 后端进程 */

import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'

// CommonJS: __dirname is a global in CommonJS modules

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

        this.process = spawn(python, [this.pythonScript, this.dbPath], {
          stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env,
            PYTHONUNBUFFERED: '1',
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

  /** 停止 Python 后端 */
  stop(): Promise<BackendStatus> {
    return new Promise((resolve) => {
      if (this.process) {
        this.process.kill('SIGTERM')
        this.process = null
      }
      this.status = { status: 'stopped' }
      this.notify()
      resolve({ ...this.status })
    })
  }

  /** 重启 Python 后端 */
  async restart(): Promise<BackendStatus> {
    await this.stop()
    return this.start()
  }

  /** 获取当前状态 */
  getStatus(): BackendStatus {
    // 检查进程是否还在运行
    if (this.status.status === 'running' && this.process) {
      try {
        this.process.kill(0) // 发送信号 0 检查进程是否存在
      } catch {
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

  /** 清理资源 */
  destroy(): void {
    this.stop()
    this.listeners = []
  }
}

// 单例
export const pythonBridge = new PythonBridge()
