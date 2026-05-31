/** afterPack script - electron-builder hook: 安装 Python 后端依赖到打包目录 */
const { execSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const os = require('os')

// 跨平台递归删除 __pycache__ 目录
function removePycache(dir) {
  if (!fs.existsSync(dir)) return
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fullPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name === '__pycache__') {
          fs.rmSync(fullPath, { recursive: true, force: true })
        } else {
          removePycache(fullPath)
        }
      }
    }
  } catch {}
}

exports.default = async function (context) {
  const { appOutDir, electronPlatformName } = context
  const rootDir = path.join(__dirname, '..')

  const backendDir = path.join(appOutDir, 'resources', 'backend')
  if (!fs.existsSync(backendDir)) {
    console.log(`[afterPack] backend dir not found at ${backendDir}, skipping`)
    return
  }

  const targetPlatform = electronPlatformName
  const isCrossCompile = process.platform !== targetPlatform

  console.log(`[afterPack] Installing Python deps → ${backendDir}`)
  console.log(`[afterPack] Host: ${process.platform}, Target: ${targetPlatform}`)

  try {
    const requirementsFile = path.join(rootDir, 'backend', 'requirements.txt')
    if (!fs.existsSync(requirementsFile)) return

    const uvicornDir = path.join(backendDir, 'uvicorn')
    if (fs.existsSync(uvicornDir)) {
      console.log('[afterPack] Already installed, skipping')
      return
    }

    // 清理 __pycache__
    removePycache(backendDir)

    if (isCrossCompile && targetPlatform === 'win32') {
      // Linux → Windows 交叉编译：下载 Windows wheel 解压到 target
      console.log('[afterPack] Cross-compile mode, downloading Windows wheels...')
      const wheelDir = path.join(os.tmpdir(), 'topoone-win-wheels')
      if (fs.existsSync(wheelDir)) fs.rmSync(wheelDir, { recursive: true, force: true })
      fs.mkdirSync(wheelDir, { recursive: true })

      // python-louvain 无二进制 wheel，先排除
      const tmpReq = path.join(wheelDir, 'requirements-filtered.txt')
      const reqContent = fs.readFileSync(requirementsFile, 'utf-8')
      fs.writeFileSync(tmpReq, reqContent.split('\n').filter(l => !l.includes('python-louvain')).join('\n'))

      // 优先使用 python -m pip（兼容 venv/系统 Python）
      const pipCmd = 'python3 -m pip'

      // 下载兼容多个 Python 版本的 wheel（3.11 ~ 3.12）
      const versions = ['3.11', '3.12']
      for (const pyVer of versions) {
        const verDir = path.join(wheelDir, pyVer)
        fs.mkdirSync(verDir, { recursive: true })
        try {
          execSync(
            `${pipCmd} download --only-binary :all: --platform win_amd64 --python-version ${pyVer} -r "${tmpReq}" -d "${verDir}" 2>/dev/null`,
            { stdio: 'inherit', timeout: 120000 }
          )
          fs.readdirSync(verDir).filter(f => f.endsWith('.whl')).forEach(f => {
            const src = path.join(verDir, f)
            const dst = path.join(wheelDir, f)
            if (!fs.existsSync(dst)) fs.copyFileSync(src, dst)
          })
        } catch {
          console.warn(`[afterPack] pip download for Python ${pyVer} failed, skipping`)
        }
        fs.rmSync(verDir, { recursive: true, force: true })
      }
      // python-louvain 无二进制 wheel，单独下载源码
      execSync(
        `${pipCmd} download --no-deps --no-binary python-louvain python-louvain==0.16 -d "${wheelDir}" 2>/dev/null || true`,
        { stdio: 'inherit', timeout: 30000 }
      )
      fs.unlinkSync(tmpReq)

      console.log('[afterPack] Extracting wheels...')
      const unzipCmd = process.platform === 'win32' ? 'tar -xf' : 'unzip -qo'
      fs.readdirSync(wheelDir).filter(f => f.endsWith('.whl')).forEach(whl => {
        execSync(`${unzipCmd} "${path.join(wheelDir, whl)}" -d "${backendDir}" 2>/dev/null`, { stdio: 'inherit', timeout: 60000 })
      })

      try {
        execSync(`${pipCmd} install --no-deps --target "${backendDir}" python-louvain==0.16`, { stdio: 'inherit', timeout: 60000 })
      } catch (e) {
        console.warn('[afterPack] python-louvain install failed:', e.message)
      }

      removePycache(backendDir)
      fs.rmSync(wheelDir, { recursive: true, force: true })
      console.log('[afterPack] Windows wheels ready')
    } else {
      // 同平台编译
      const pipCmd = targetPlatform === 'win32' ? 'python -m pip' : 'python3 -m pip'
      execSync(`${pipCmd} install --target "${backendDir}" -r "${requirementsFile}"`, { stdio: 'inherit', timeout: 300000 })
      console.log('[afterPack] Python deps installed')
    }
  } catch (error) {
    console.error('[afterPack] Failed:', error.message)
    console.warn('[afterPack] Python backend may not work until deps are installed manually')
  }
}
