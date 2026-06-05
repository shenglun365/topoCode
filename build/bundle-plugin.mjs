/**
 * bundle-plugin.mjs — Build plugins for distribution
 *
 * For each plugin in plugins/<name>/:
 *   1. Read plugin.json, validate structure
 *   2. Copy plugin files to dist-plugins/<id>/
 *   3. (Optional) Filter by target platform via --platform flag
 *
 * Usage: node build/bundle-plugin.mjs [--platform linux-x64|win-x64|darwin-x64|darwin-arm64]
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync, cpSync, rmSync, readdirSync, statSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, '..')
const pluginsSrc = join(rootDir, 'plugins')
const pluginsOut = join(rootDir, 'dist-plugins')

const targetPlatform = process.argv.includes('--platform')
  ? process.argv[process.argv.indexOf('--platform') + 1]
  : null

if (existsSync(pluginsOut)) {
  rmSync(pluginsOut, { recursive: true, force: true })
}

const skipDirs = new Set(['__pycache__', '.git', 'node_modules'])

function copyPluginFiles(src, dst) {
  if (!existsSync(src)) return
  mkdirSync(dst, { recursive: true })
  const items = readdirSync(src)
  for (const item of items) {
    if (item.endsWith('.pyc') || skipDirs.has(item)) continue
    const s = join(src, item)
    const d = join(dst, item)
    if (statSync(s).isDirectory()) {
      copyPluginFiles(s, d)
    } else {
      cpSync(s, d)
    }
  }
}

const entries = []
const pluginDirs = readdirSync(pluginsSrc).filter(d =>
  statSync(join(pluginsSrc, d)).isDirectory() && existsSync(join(pluginsSrc, d, 'plugin.json'))
)

for (const name of pluginDirs) {
  const pluginDir = join(pluginsSrc, name)
  const manifest = JSON.parse(readFileSync(join(pluginDir, 'plugin.json'), 'utf-8'))

  if (!manifest.id || !manifest.entry) {
    console.warn(`[bundle-plugin] Skipping ${name}: invalid plugin.json (missing id or entry)`)
    continue
  }

  if (targetPlatform && manifest.platforms && !manifest.platforms.includes(targetPlatform)) {
    console.log(`[bundle-plugin] Skipping ${manifest.id}: not compatible with ${targetPlatform}`)
    continue
  }

  const outDir = join(pluginsOut, manifest.id)
  copyPluginFiles(pluginDir, outDir)
  entries.push({ id: manifest.id, name: manifest.name, version: manifest.version, size_mb: manifest.size_mb })
  console.log(`[bundle-plugin] Bundled ${manifest.id} (${name}) → ${outDir}`)
}

writeFileSync(join(pluginsOut, 'plugins.json'), JSON.stringify(entries, null, 2), 'utf-8')
console.log(`[bundle-plugin] Done — ${entries.length} plugins bundled`)
