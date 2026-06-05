/** afterPack script - electron-builder hook: 安装 Python 依赖到打包目录 */
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

// 安装单个插件的 Python 依赖
function installPluginDeps(pluginDir) {
  const jsonPath = path.join(pluginDir, 'plugin.json')
  if (!fs.existsSync(jsonPath)) return
  try {
    const manifest = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'))
    const deps = manifest.dependencies?.python
    if (!deps || deps.length === 0) return
    const pipCmd = process.platform === 'win32' ? 'python -m pip' : 'python3 -m pip'
    console.log(`[afterPack] Installing deps for plugin ${manifest.id}...`)
    execSync(`${pipCmd} install --target "${pluginDir}" ${deps.map(d => `"${d}"`).join(' ')}`, {
      stdio: 'inherit', timeout: 300000,
    })
    removePycache(pluginDir)
    console.log(`[afterPack] Plugin ${manifest.id} deps installed`)
  } catch (e) {
    console.warn(`[afterPack] Plugin dep install failed for ${pluginDir}: ${e.message}`)
  }
}

exports.default = async function (context) {
  const { appOutDir, electronPlatformName } = context
  const rootDir = path.join(__dirname, '..')

  // ── 1. Install backend-core Python deps ──
  const backendDir = path.join(appOutDir, 'resources', 'backend-core')
  if (!fs.existsSync(backendDir)) {
    console.log(`[afterPack] backend-core dir not found at ${backendDir}, skipping`)
  } else {
    const targetPlatform = electronPlatformName
    const isCrossCompile = process.platform !== targetPlatform

    console.log(`[afterPack] Installing Python deps → ${backendDir}`)
    console.log(`[afterPack] Host: ${process.platform}, Target: ${targetPlatform}`)

    try {
      const requirementsFile = path.join(rootDir, 'backend-core', 'requirements-core.txt')
      if (!fs.existsSync(requirementsFile)) {
        console.log('[afterPack] No requirements-core.txt found, skipping core deps')
      } else {
        const uvicornDir = path.join(backendDir, 'uvicorn')
        if (fs.existsSync(uvicornDir)) {
          console.log('[afterPack] Backend deps already installed, skipping')
        } else {
          removePycache(backendDir)

          if (isCrossCompile && targetPlatform === 'win32') {
            console.log('[afterPack] Cross-compile mode, downloading Windows wheels...')
            const wheelDir = path.join(os.tmpdir(), 'topoone-win-wheels')
            if (fs.existsSync(wheelDir)) fs.rmSync(wheelDir, { recursive: true, force: true })
            fs.mkdirSync(wheelDir, { recursive: true })

            const tmpReq = path.join(wheelDir, 'requirements-filtered.txt')
            const reqContent = fs.readFileSync(requirementsFile, 'utf-8')
            fs.writeFileSync(tmpReq, reqContent.split('\n').filter(l => !l.includes('python-louvain')).join('\n'))

            const pipCmd = 'python3 -m pip'
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
            fs.unlinkSync(tmpReq)

            console.log('[afterPack] Extracting wheels...')
            const unzipCmd = process.platform === 'win32' ? 'tar -xf' : 'unzip -qo'
            fs.readdirSync(wheelDir).filter(f => f.endsWith('.whl')).forEach(whl => {
              execSync(`${unzipCmd} "${path.join(wheelDir, whl)}" -d "${backendDir}" 2>/dev/null`, { stdio: 'inherit', timeout: 60000 })
            })

            removePycache(backendDir)
            fs.rmSync(wheelDir, { recursive: true, force: true })
            console.log('[afterPack] Windows wheels ready')
          } else {
            const pipCmd = targetPlatform === 'win32' ? 'python -m pip' : 'python3 -m pip'
            execSync(`${pipCmd} install --target "${backendDir}" -r "${requirementsFile}"`, { stdio: 'inherit', timeout: 300000 })
            console.log('[afterPack] Backend Python deps installed')
          }
        }
      }
    } catch (error) {
      console.error('[afterPack] Backend dep install failed:', error.message)
      console.warn('[afterPack] Python backend may not work until deps are installed manually')
    }
  }

  // ── 2. Install plugin Python deps ──
  const pluginsDir = path.join(appOutDir, 'resources', 'plugins')
  if (!fs.existsSync(pluginsDir)) {
    console.log(`[afterPack] plugins dir not found at ${pluginsDir}, skipping plugin deps`)
    return
  }

  console.log(`[afterPack] Installing plugin deps → ${pluginsDir}`)
  for (const entry of fs.readdirSync(pluginsDir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      installPluginDeps(path.join(pluginsDir, entry.name))
    }
  }
  console.log('[afterPack] Plugin deps done')

  // ── 3. Install bundled module Python deps ──
  const modulesDir = path.join(appOutDir, 'resources', 'modules')
  if (fs.existsSync(modulesDir)) {
    console.log(`[afterPack] Installing module deps → ${modulesDir}`)
    for (const entry of fs.readdirSync(modulesDir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        installPluginDeps(path.join(modulesDir, entry.name))
      }
    }
    console.log('[afterPack] Module deps done')
  } else {
    console.log('[afterPack] modules dir not found, skipping')
  }
}
