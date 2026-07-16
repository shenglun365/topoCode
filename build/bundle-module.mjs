/**
 * bundle-module.mjs — Build individual `.topo-module` packages
 *
 * Each plugin/backend-module is packaged into a standalone tar.gz archive
 * with a module.json manifest, suitable for registry distribution.
 *
 * Usage:
 *   node build/bundle-module.mjs                          # all plugins
 *   node build/bundle-module.mjs --name parsers           # single plugin
 *   node build/bundle-module.mjs --name parsers --outdir /tmp/modules
 *   node build/bundle-module.mjs --all                    # same as default
 *   node build/bundle-module.mjs --registry               # build + emit registry.json
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, statSync, createReadStream, createWriteStream, rmSync } from 'fs'
import { join, dirname, basename, resolve } from 'path'
import { fileURLToPath } from 'url'
import { createGzip } from 'zlib'
import { createHash } from 'crypto'
import { create, extract } from 'tar'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, '..')

// ========================== Config ==========================

const PLUGIN_SRC_DIR = join(rootDir, 'plugins')
const MODULE_OUT_DIR = join(rootDir, 'dist-modules')
const MODULE_EXT = '.topo-module'
const TMP_DIR = join(rootDir, 'tmp-module-build')

// ========================== Helpers ==========================

function sha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256')
    const stream = createReadStream(filePath)
    stream.on('data', chunk => hash.update(chunk))
    stream.on('end', () => resolve(hash.digest('hex')))
    stream.on('error', reject)
  })
}

function copyDir(src, dst, skipDirs = new Set()) {
  mkdirSync(dst, { recursive: true })
  for (const item of readdirSync(src)) {
    if (item.endsWith('.pyc') || skipDirs.has(item)) continue
    const s = join(src, item)
    const d = join(dst, item)
    if (statSync(s).isDirectory()) {
      copyDir(s, d, skipDirs)
    } else {
      writeFileSync(d, readFileSync(s))
    }
  }
}

function cleanDir(dir) {
  if (existsSync(dir)) {
    rmSync(dir, { recursive: true, force: true })
  }
}

// ========================== Build one module ==========================

async function buildModule(srcDir, outDir) {
  const name = basename(srcDir)
  const manifestPath = join(srcDir, 'plugin.json')
  if (!existsSync(manifestPath)) {
    console.warn(`[bundle-module] Skipping ${name}: no plugin.json`)
    return null
  }

  const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'))
  const id = manifest.id || name
  const version = manifest.version || '0.1.0'
  const moduleName = `${id}-v${version}`
  const archiveName = `${moduleName}${MODULE_EXT}`
  const archivePath = join(outDir, archiveName)

  // 1. Prepare temp build dir
  const buildDir = join(TMP_DIR, moduleName)
  cleanDir(buildDir)
  mkdirSync(buildDir, { recursive: true })

  // 2. Write module.json (superset of plugin.json)
  const moduleManifest = {
    type: 'plugin',
    id,
    name: manifest.name || name,
    version,
    description: manifest.description || '',
    entry: manifest.entry || '',
    platforms: manifest.platforms || [],
    dependencies: manifest.dependencies || {},
    size_kb: 0,
    build_at: new Date().toISOString(),
  }
  writeFileSync(join(buildDir, 'module.json'), JSON.stringify(moduleManifest, null, 2), 'utf-8')

  // 3. Copy all source files (exclude __pycache__)
  copyDir(srcDir, join(buildDir, 'src'), new Set(['__pycache__', '.git', 'node_modules']))

  // 4. Create tar.gz
  mkdirSync(outDir, { recursive: true })
  await create(
    { gzip: true, file: archivePath, cwd: buildDir },
    ['.']
  )

  // 5. Calculate checksum
  const checksum = await sha256(archivePath)
  const sizeBytes = statSync(archivePath).size
  moduleManifest.size_kb = Math.round(sizeBytes / 1024)
  moduleManifest.checksum_sha256 = checksum
  moduleManifest.download_url = `{{REGISTRY_BASE}}/${archiveName}`

  // 6. Update archive's module.json with checksum
  writeFileSync(join(buildDir, 'module.json'), JSON.stringify(moduleManifest, null, 2), 'utf-8')
  // Re-pack with checksum included
  cleanDir(archivePath)
  await create(
    { gzip: true, file: archivePath, cwd: buildDir },
    ['.']
  )

  // 7. Also save standalone module.json (for registry generation)
  writeFileSync(join(outDir, `${moduleName}.module.json`), JSON.stringify(moduleManifest, null, 2), 'utf-8')

  // 8. Cleanup
  cleanDir(buildDir)

  console.log(`[bundle-module] ✓ ${archiveName}  (${moduleManifest.size_kb} KB, sha256=${checksum.slice(0, 16)}...)`)
  return moduleManifest
}

// ========================== Entry ==========================

async function main() {
  const args = process.argv.slice(2)
  const nameIdx = args.indexOf('--name')
  const outdirIdx = args.indexOf('--outdir')
  const singleName = nameIdx >= 0 ? args[nameIdx + 1] : null
  const customOutDir = outdirIdx >= 0 ? args[outdirIdx + 1] : null
  const emitRegistry = args.includes('--registry')

  const outDir = customOutDir || MODULE_OUT_DIR
  cleanDir(outDir)

  // Collect plugin dirs
  let pluginDirs = []
  if (singleName) {
    const dir = join(PLUGIN_SRC_DIR, singleName)
    if (existsSync(dir)) {
      pluginDirs = [dir]
    } else {
      console.error(`[bundle-module] Plugin not found: ${dir}`)
      process.exit(1)
    }
  } else {
    pluginDirs = readdirSync(PLUGIN_SRC_DIR)
      .filter(d => statSync(join(PLUGIN_SRC_DIR, d)).isDirectory())
      .map(d => join(PLUGIN_SRC_DIR, d))
  }

  console.log(`[bundle-module] Building ${pluginDirs.length} module(s) → ${outDir}`)

  const results = []
  for (const dir of pluginDirs) {
    const manifest = await buildModule(dir, outDir)
    if (manifest) results.push(manifest)
  }

  // Emit registry.json
  if (emitRegistry) {
    const registry = {
      $schema: 'https://registry.topocode.dev/schema-v1.json',
      registry_version: '1.0',
      updated_at: new Date().toISOString(),
      modules: {},
    }
    for (const m of results) {
      registry.modules[m.id] = {
        name: m.name,
        version: m.version,
        description: m.description,
        download_url: m.download_url,
        checksum_sha256: m.checksum_sha256,
        size_kb: m.size_kb,
        platforms: m.platforms,
        dependencies: m.dependencies,
      }
    }
    const registryPath = join(outDir, 'registry.json')
    writeFileSync(registryPath, JSON.stringify(registry, null, 2), 'utf-8')
    console.log(`[bundle-module] ✓ Registry: ${registryPath} (${results.length} modules)`)
  }

  console.log(`[bundle-module] Done — ${results.length} module(s) in ${outDir}`)
}

main().catch(err => {
  console.error('[bundle-module] FAILED:', err)
  process.exit(1)
})
