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

  // 比对 requirements.txt 的哈希，未变化则跳过安装
  const markerFile = path.join(backendDir, '.pip-installed')
  const reqHash = crypto.createHash('sha256').update(fs.readFileSync(requirementsFile)).digest('hex')
  if (fs.existsSync(markerFile)) {
    const prevHash = fs.readFileSync(markerFile, 'utf8').trim()
    if (prevHash === reqHash) {
      console.log('[afterPack] Python dependencies unchanged, skipping install')
      process.exit(0)
    }
  }

  execSync(
    `pip3 install --target "${backendDir}" --upgrade -r "${requirementsFile}"`,
    { stdio: 'inherit' }
  )
  // 写入当前哈希作为标记
  fs.writeFileSync(markerFile, reqHash)
  console.log('[afterPack] Python dependencies installed successfully')
} catch (error) {
  console.error('[afterPack] Failed to install Python dependencies:', error.message)
  process.exit(1)
}
