# Build Resources

此目录包含 Electron 打包所需的图标和资源文件。

## 图标要求

| 平台 | 文件 | 格式 | 尺寸 |
|------|------|------|------|
| Linux | `icon.png` | PNG | 512×512 |
| Windows | `icon.ico` | ICO | 256×256 (多尺寸) |
| macOS | `icon.icns` | ICNS | 512×512 |

## 生成图标

### Linux
```bash
# 使用 ImageMagick
convert -size 512x512 xc:'#1e1e2e' -pointsize 36 -fill '#cdd6f4' -gravity center -annotate 0 'TopoOne' icon.png
```

### Windows
```bash
# 使用 Inkscape 或在线工具
# icon.png → icon.ico
```

### macOS
```bash
# 使用 iconutil 或在线工具
# icon.png → icon.icns
```

## 占位图标

当前使用 1×1 透明 PNG 作为占位，正式打包前请替换为实际图标。
