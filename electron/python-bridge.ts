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
      // 开发环境: dist-electron/ -> 项目根目录 -> backend/main.py
      const devPath = join(__dirname, '../backend/main.py')
      if (existsSync(devPath)) return devPath
    }

    // 打包环境: 从 extraResources 目录查找
    const prodPath = join(process.resourcesPath, 'backend', 'main.py')
    if (existsSync(prodPath)) return prodPath

    // 回退到开发路径
    return join(__dirname, '../backend/main.py')
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
        try {
          if (process.platform === 'win32') {
            const { execSync } = require('child_process')
            execSync(`taskkill /F /PID ${this.process.pid} 2>nul`, { stdio: 'ignore' })
          } else {
            this.process.kill('SIGKILL')
          }
        } catch { /* already dead */ }
        this.process = null
      }

      this.status = { status: 'starting' }
      this.notify()

      try {
        // 查找 Python 可执行文件
        const pythonResult = this.findPython()
        if (!pythonResult) {
          this.status = { status: 'error', error: 'Python 3.10+ not found. Please install Python 3.10+' }
          this.notify()
          resolve({ ...this.status })
          return
        }

        const python = pythonResult.path
        console.error('[PythonBridge] Found:', pythonResult.version, 'at', python)

        // 验证 Python 版本
        try {
          const { execSync } = require('child_process')
          const versionOutput = execSync(`"${python}" --version`, { encoding: 'utf-8', timeout: 15000 }).trim()
          console.error('[PythonBridge] Found:', versionOutput)
          const match = versionOutput.match(/Python (\d+)\.(\d+)/)
          if (match) {
            const major = parseInt(match[1], 10)
            const minor = parseInt(match[2], 10)
            if (major < 3 || (major === 3 && minor < 10)) {
              this.status = { status: 'error', error: `Python 3.10+ required, got ${versionOutput}` }
              this.notify()
              resolve({ ...this.status })
              return
            }
          }
        } catch {
          this.status = { status: 'error', error: 'Failed to check Python version' }
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
          : join(__dirname, '../backend')

        const memoryLimit = this.memoryLimit || 4096
        console.error('[PythonBridge] Spawning:', python, this.pythonScript)
        const spawnOptions: any = {
          stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env,
            PYTHONUNBUFFERED: '1',
            PYTHONDONTWRITEBYTECODE: '1',
            PYTHONPATH: backendDir,
            ZMQ_DEALER_PORT: String(dealerPort),
            ZMQ_PUB_PORT: String(pubPort),
          },
        }
        // Windows 上启用 shell 以支持 .bat/.cmd 包装器（如 pyenv shims）
        if (process.platform === 'win32') {
          spawnOptions.shell = true
        }
        this.process = spawn(python, [
          this.pythonScript, this.dbPath,
          '--http-port', String(httpPort),
          '--http-host', String(httpHost),
          '--memory-limit', String(memoryLimit),
        ], spawnOptions)

        this.process.stdout?.on('data', (data) => {
          console.error('[Python]', data.toString())
        })

        this.process.stderr?.on('data', (data) => {
          console.error('[Python Error]', data.toString())
        })

        let exited = false
        this.process.on('exit', (code, signal) => {
          exited = true
          console.error(`[PythonBridge] Process exited code=${code} signal=${signal}`)
          if (code !== 0) {
            this.status = { status: 'error', error: `Process exited with code ${code}` }
          } else {
            this.status = { status: 'stopped' }
          }
          this.process = null
          this.notify()
        })

        this.process.on('error', (error) => {
          console.error('[PythonBridge] Spawn error:', error.message)
          this.status = { status: 'error', error: error.message }
          this.notify()
        })

        // 等待后端启动，最长 10 秒
        let waited = 0
        const checkInterval = setInterval(() => {
          waited += 1000
          if (exited) {
            clearInterval(checkInterval)
            // 进程已退出，status 已在 exit handler 中设置
            resolve({ ...this.status })
          } else if (waited >= 10000) {
            clearInterval(checkInterval)
            if (this.process && this.process.exitCode === null) {
              this.status = { status: 'running', pid: this.process.pid, port: 5671 }
              this.notify()
              resolve({ ...this.status })
            }
          }
        }, 1000)

      } catch (error: any) {
        this.status = { status: 'error', error: error.message }
        this.notify()
        resolve({ ...this.status })
      }
    })
  }

  /** 停止 Python 后端 — Windows 用 taskkill，Unix 用 SIGTERM/SIGKILL */
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

      proc.once('exit', onExit)

      if (process.platform === 'win32') {
        // Windows: taskkill /F 比 SIGTERM 更可靠
        try {
          const { execSync } = require('child_process')
          execSync(`taskkill /F /PID ${proc.pid} 2>nul`, { stdio: 'ignore' })
        } catch { /* already dead */ }
      } else {
        // Unix: SIGTERM 优雅退出
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

        proc.once('exit', () => {
          clearTimeout(killTimer)
        })
      }
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

      let output = ''
      if (process.platform === 'win32') {
        // Windows：netstat + findstr
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
        // netstat -ano 输出格式: "  TCP    0.0.0.0:3456   0.0.0.0:0    LISTENING    12345"
        pids = output.split('\n')
          .map(line => {
            const parts = line.trim().split(/\s+/)
            return parseInt(parts[parts.length - 1], 10)
          })
          .filter(pid => !isNaN(pid))
      } else if (process.platform === 'darwin') {
        pids = output.split('\n').filter(Boolean).map(Number)
      } else {
        pids = output.split(/\s+/).filter(Boolean).map(Number)
      }

      const foreignPids = pids.filter(pid => pid !== myPid && pid !== electronPid)
      if (foreignPids.length > 0) {
        console.warn(`[PythonBridge] Port ${port} occupied by foreign process(es), killing: ${foreignPids.join(', ')}`)
        foreignPids.forEach(pid => {
          try {
            if (process.platform === 'win32') {
              execSync(`taskkill /F /PID ${pid}`, { stdio: ['pipe', 'pipe', 'ignore'] })
            } else {
              execSync(`kill -9 ${pid}`, { stdio: ['pipe', 'pipe', 'ignore'] })
            }
          } catch {}
        })
        // 等待释放
        const start = Date.now()
        while (Date.now() - start < 300) { /* busy-wait 300ms */ }
      } else {
        console.log(`[PythonBridge] Port ${port} held by our own backend (PID ${myPid}), skipping kill`)
      }
    } catch {
      // 工具不可用或无占用，忽略
    }
  }

  /** 查找 Python 可执行文件（返回完整路径 + 版本号） */
  private findPython(): { path: string; version: string } | null {
    const candidates = process.platform === 'win32'
      ? ['python', 'python3', 'py']
      : ['python3', 'python']

    // 收集所有候选路径，去重
    const candidatePaths: string[] = []

    // 1. 从 PATH 中查找
    for (const cmd of candidates) {
      try {
        const { execSync } = require('child_process')
        const testCmd = process.platform === 'win32' ? `where ${cmd}` : `which ${cmd}`
        const output = execSync(testCmd, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim()
        const lines = output.split('\n').map((l: string) => l.trim()).filter(Boolean)
        for (const line of lines) {
          // Windows Store App Execution Alias 是 stub，排除
          if (process.platform === 'win32' && line.includes('Microsoft\\WindowsApps')) continue
          if (!candidatePaths.includes(line)) candidatePaths.push(line)
        }
      } catch { /* 继续 */ }
    }

    // 2. 常见安装路径（兜底）
    const homeDir = process.env.HOME || process.env.USERPROFILE || ''
    const fallbackPaths = process.platform === 'win32'
      ? [
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python313\\python.exe`,
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`,
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python311\\python.exe`,
          `${homeDir}\\AppData\\Local\\Programs\\Python\\Python310\\python.exe`,
          'C:\\Python313\\python.exe',
          'C:\\Python312\\python.exe',
          'C:\\Python311\\python.exe',
          'C:\\Python310\\python.exe',
        ]
      : [
          '/usr/bin/python3',
          '/usr/local/bin/python3',
          '/opt/homebrew/bin/python3',
          '/usr/bin/python',
          join(homeDir, '.pyenv', 'shims', 'python3'),
        ]

    for (const p of fallbackPaths) {
      if (!candidatePaths.includes(p)) candidatePaths.push(p)
    }

    // 3. 逐个验证版本，返回第一个可用的
    for (const pythonPath of candidatePaths) {
      try {
        if (!existsSync(pythonPath)) continue
        const { execSync } = require('child_process')
        const versionOutput = execSync(`"${pythonPath}" --version`, { encoding: 'utf-8', timeout: 15000 }).trim()
        const match = versionOutput.match(/Python (\d+)\.(\d+)/)
        if (match) {
          const major = parseInt(match[1], 10)
          const minor = parseInt(match[2], 10)
          if (major >= 3 && minor >= 10) {
            return { path: pythonPath, version: versionOutput }
          }
        }
      } catch { /* 继续下一个 */ }
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
