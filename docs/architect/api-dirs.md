# 宿主机目录浏览 API — 打开新项目弹窗

> 契约对象：打开新项目弹窗 `web/architect-src/components/project/HostDirPickerDialog.vue`
> 所属服务：`plugins/architect`(独立 FastAPI，端口 `3470`，前缀 `/api/architect`)
> 传输：JSON，`{code, message, data}` 包络(见 `conventions.md`)。
> 权限：目录读写一律用**宿主机会话权限**(`os.access` R_OK/W_OK)判定，无跨主机提权。

## 背景

「打开新项目」不再走 Greenfield 引导弹窗(该引导后续另置)，改为**宿主机目录浏览器**：
按文件目录层级逐级访问宿主机目录，可新建目录(需写权限)；选定目录后建立 architect
项目根目录前先自动识别其特征，据此决定直接打开 / 重新打开已有项目 / 可选关联 KB。

## `GET /dir/list`

列出宿主机目录内容(目录优先 + 名称排序，跳过 `.git`/`node_modules` 等系统目录与隐藏项)。

### 请求

| Query | 类型 | 说明 |
| --- | --- | --- |
| `path` | `string?` | 绝对路径；缺省为当前用户主目录 |

### 响应 `data`

| 字段 | 类型 | 说明 |
| --- | --- | ---- |
| `path` | `string` | 当前目录绝对路径 |
| `parent` | `string\|null` | 父目录路径(根目录为 null) |
| `host` | `{name, ip}` | 宿主机标识(主机名 + 对外 IP)，供远程 Web-UI 访问时确认目录所在机器 |
| `readable` / `writable` | `boolean` | 当前目录读写权限 |
| `entries` | `DirEntry[]` | 子项：`name`/`isDir`/`size`/`mtime`/`readable`/`writable` |

## `POST /dir/create`

在指定父目录下新建目录(需父目录**写权限**，否则 403)。

| Body | 类型 | 说明 |
| --- | --- | --- |
| `parent` | `string` | 父目录绝对路径 |
| `name` | `string` | 新目录名(不含路径分隔符) |

## `POST /dir/analyze`

对选定目录做**前置识别**(建立 architect 项目根目录前的自动识别)。

### Body

| Body | 类型 | 说明 |
| --- | --- | --- |
| `root` | `string` | 选定目录的绝对路径 |

### 响应 `data`

| 字段 | 类型 | 说明 |
| --- | --- | ---- |
| `root` / `name` | `string` | 目录路径与末段名 |
| `readable` / `writable` | `boolean` | 该目录读写权限 |
| `isGitRoot` | `boolean` | 是否为本地 git **主目录**(顶层) |
| `gitToplevel` | `string\|null` | git 仓库顶层路径(非 git 仓库为 null) |
| `gitBranch` | `string\|null` | 当前分支 |
| `isEmpty` | `boolean` | 是否空目录(忽略隐藏项/系统目录) |
| `hasCode` | `boolean` | 是否已有代码/内容 |
| `duplicate` | `{id,name,rootPath,mode}\|null` | 是否**重复打开已建立**的 architect 项目(`arch_projects` 中同一 `root_path`) |
| `kbCandidates` | `KbCandidate[]` | 可安全关联的有效 KB 项目(同一仓库源校验通过且已有基线)，含 `reason` |

### 决策映射

- `isGitRoot` → 展示分支；非 git 主目录提示。
- `isEmpty`/`hasCode` → 提示目录状态。
- `duplicate` → 提示将重新打开已有项目(不重复登记)。
- `kbCandidates` → 弹窗内可选勾选，确认时调 `POST /project/bind {execRoot, kbProjectId}` 一并关联。

### 弹窗交互(选中状态)

弹窗支持**三种选中方式**，不必进入目录即可选中作为项目目录：

1. **进入子目录**：点行内「进入」或双击目录行 → 浏览到该子目录，选中自动落到该目录；
2. **点选当前目录下的子目录**：单击目录行(单选圈)即可选中，不进入；
3. **选中当前目录**：默认选中当前浏览目录，或点「选中当前目录」按钮。

弹窗标题与确认页均显示**宿主机标识**(`host.name (host.ip)`，来自 `GET /dir/list` 的 `host`
字段)，避免远程 Web-UI 访问时用户误以为目录在本机。

## 实现

- 后端：`plugins/architect/arch_routes/dirs.py`(复用 `project._same_repo_source`、`_list_kb_projects`)
- 前端：`web/architect-src/services/dir-service.ts`(`list`/`createDir`/`analyze`)、
  `types/index.ts`(`DirList` / `DirAnalysis` / `DirEntry`)、
  `HostDirPickerDialog.vue`(浏览 → 识别 → 绑定，绑定复用 `project-store.bindWorkingDir`/`bindKbProject`)。
