/** afterPack script - 安装 Python 后端依赖到打包目录 */
const { execSync } = require('child_process')
const path = require('path')
const fs = require('fs')

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
  if (fs.existsSync(requirementsFile)) {
    execSync(
      `pip3 install --target "${backendDir}" -r "${requirementsFile}"`,
      { stdio: 'inherit' }
    )
    console.log('[afterPack] Python dependencies installed successfully')
  }
} catch (error) {
  console.error('[afterPack] Failed to install Python dependencies:', error.message)
  process.exit(1)
}
