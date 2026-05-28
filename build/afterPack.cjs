/** afterPack script - 安装 Python 后端依赖到打包目录 */
const { execSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const crypto = require('crypto')

// 自动检测打包输出目录
const rootDir = path.join(__dirname, '..')
const possibleDirs = [
  path.join(rootDir, 'release', 'linux-unpacked', 'resources', 'backend'),
  path.join(rootDir, 'release', 'TopoOne AppImage', 'resources', 'backend'),
]

let backendDir = null
for (const dir of possibleDirs) {
  if (fs.existsSync(dir)) {
    backendDir = dir
    break
  }
}

if (!backendDir) {
  console.log('[afterPack] No packaged backend directory found, skipping')
  process.exit(0)
}

console.log(`[afterPack] Installing Python dependencies to ${backendDir}`)

try {
  const requirementsFile = path.join(rootDir, 'backend', 'requirements.txt')
  if (!fs.existsSync(requirementsFile)) {
    console.log('[afterPack] No requirements.txt found, skipping')
    process.exit(0)
  }

  // 检查包是否实际已安装（验证关键包 uvicorn 是否存在）
  const uvicornDir = path.join(backendDir, 'uvicorn')
  if (fs.existsSync(uvicornDir)) {
    console.log('[afterPack] Python packages already installed, skipping')
    process.exit(0)
  }

  // 安装前清理 __pycache__，避免 pip 告警
  execSync(`find "${backendDir}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null`, { stdio: 'ignore' })

  execSync(
    `pip3 install --target "${backendDir}" -r "${requirementsFile}"`,
    { stdio: 'inherit', timeout: 300000 }
  )
  console.log('[afterPack] Python dependencies installed successfully')
} catch (error) {
  console.error('[afterPack] Failed to install Python dependencies:', error.message)
  process.exit(1)
}
