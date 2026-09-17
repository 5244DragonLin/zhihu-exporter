# zhihu_exporter：知乎内容导出工具

知乎内容导出工具。基于 aiohttp 异步并发抓取，将知乎的内容导出为本地 Markdown / HTML 文件，支持增量爬取、多格式输出、多种登录方式、YAML 配置文件。

- **点赞导出（`--mode upvotes`，默认）**：导出某用户**点赞过**的他人回答和文章
- **原创导出（`--mode articles` / `answers` / `all`）**：导出某用户**自己创作**的文章 / 回答（免浏览器、免签名）
- **专栏导出（`--mode column`）**：导出某专栏的全部文章，**自动识别**专栏链接无需指定模式（免浏览器、免签名）

## 💡为什么需要这个工具？

- 知乎没有官方的"导出点赞内容"功能
- 你点赞过的优质回答和文章，想回顾时只能一页页翻
- 万一哪天内容被删除或账号出问题，收藏夹里的好东西就没了
- 想把点赞内容搬到本地归档、做知识管理？只能一篇篇手动复制

**Zhihu Upvote Exporter 解决这些问题**：输入用户主页链接，自动爬取所有点赞回答和文章，每条内容保存为一个格式优美的 Markdown 或 HTML 文件。同时支持直接输入专栏链接，一键导出专栏全部文章。

## ⭐亮点

- 三抓取模式：既导出用户**点赞过**的他人内容（`--mode upvotes`，默认），也可导出用户**自己创作**的文章 / 回答（`--mode articles` / `answers` / `all`，免浏览器、免签名），还支持直接导出**专栏**全部文章（`--mode column`，自动识别专栏链接）
- 关键词过滤：`--keyword` 仅导出标题命中关键词的内容，适合长篇小说、连载文章定向归档
- 双格式输出：Markdown 纯文本 + HTML 富文本（保留原始排版、图片、样式），可同时导出，**专栏文章文件名更简洁**（仅标题，无日期/ID 前后缀）
- 增量爬取：记录上次抓取时间，下次仅抓取新增内容，不重复下载
- 异步并发：aiohttp 异步抓取，`--concurrency` 控制并发数，速度大幅提升
- 配置文件：支持 YAML 配置文件，命令行参数与配置文件无感融合
- 多种登录方式：Cookie 字符串 / Cookie 文件 / Playwright 扫码登录，灵活选择
- 拟人化策略：请求间隔 + 限流重试，降低风控风险
- 分目录存储：按用户 → 内容类型 → 格式自动整理到子文件夹
- 图片下载：支持将回答/文章中的图片下载到本地或上传到 Gitee 图床，内容中的图片链接自动替换，避免知乎图床失效
- 封面提取：文章优先使用 API 封面图，回答自动提取正文首图，Markdown 追加 `![cover]`、HTML 展示封面
- 领域分类：统计报告按 13 大领域自动归并知乎官方标签（影视文艺、两性婚恋、科技互联网、时事政治、教育成长等），一眼看出兴趣分布，点击领域可展开查看该领域全部条目；冷门问题可在 `categories.py` 手动指定归属
- 条数控制：`--limit` 限制抓取条数，适合测试或按需导出

## 🖥️效果预览

**CLI 运行效果**

```
[增量模式] 上次已抓取至 2026-06-09 15:30:00（42 个回答 + 8 篇文章）
将只抓取此时间之后的新点赞（MD+HTML）...

开始抓取用户 [xxx] 的点赞动态...

正在获取第 1 页... 本页新增 5 条（累计：5 个回答 + 0 篇文章）
正在获取第 2 页... 本页新增 3 条（累计：7 个回答 + 1 篇文章）
正在获取第 3 页... 本页新增 0 条，已到达上次记录时间，停止翻页。

========== 导出完成 ==========
本次新增：7 个回答 + 1 篇文章
输出格式：MD+HTML
  MD 回答目录：output\xxx\赞同的回答_md
  MD 文章目录：output\xxx\赞同的文章_md
  HTML 回答目录：output\xxx\赞同的回答_html
  HTML 文章目录：output\xxx\赞同的文章_html
```

**无新增时（v3.1 起）**：没有新点赞时不再全量重扫统计报告，秒级完成：

```
[增量模式] 上次已抓取至 2026-08-08 09:01:25（833 个回答 + 74 篇文章）
开始抓取用户 [xxx] 的点赞动态...

正在获取第 1 页... 本页新增 0 条（累计：0 个回答 + 0 篇文章）
已到达上次记录时间，停止翻页。

========== 导出完成 ==========
本次新增（去重）：0 个回答 + 0 篇文章
...
本次无新增内容，跳过统计报告生成（内容未变化，报告保持上次状态）。
```

**输出目录结构**

```
output/
└── 用户名/
    ├── 赞同的回答_md/
    │   ├── 2026-06-09_如何评价某某事件.md
    │   └── ...
    ├── 赞同的文章_md/
    │   ├── 2026-06-08_深度学习入门指南.md
    │   └── ...
    ├── 赞同的回答_html/
    │   ├── 2026-06-09_如何评价某某事件.html
    │   └── ...
    ├── 赞同的文章_html/
    │   ├── 2026-06-08_深度学习入门指南.html
    │   └── ...
    └── .progress.json          # 增量进度记录（按格式隔离）
```

**输出的 Markdown 文件**

```markdown
# [如何评价某某事件？](https://www.zhihu.com/question/xxx/answer/xxx)

**作者名** / 赞同于 2026-06-09 15:30:00

> 问题：[如何评价某某事件？](https://www.zhihu.com/question/xxx)

---

回答正文内容，包含 **加粗**、*斜体*、
![图片](https://pic.zhimg.com/xxx.jpg) 和 [链接](url) ...
```

## 🚀快速开始

### 1. 克隆项目

```bash
# Gitee 镜像（国内访问快）
git clone https://gitee.com/yhl5244/zhihu-exporter.git
cd zhihu-exporter

# GitHub 原仓库
git clone https://github.com/5244DragonLin/zhihu-exporter.git
cd zhihu-exporter
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
# 如需自动扫码登录，再安装 Playwright
pip install playwright && playwright install chromium
# 如需 YAML 配置文件支持
pip install pyyaml
```

### 3. 运行

```bash
# 导出指定用户的点赞内容（进入交互式登录）
python zhihu_exporter.py https://www.zhihu.com/people/xxx

# 使用 Cookie 字符串直接运行
python zhihu_exporter.py https://www.zhihu.com/people/xxx -c "your_cookie"

# HTML 富文本格式导出
python zhihu_exporter.py https://www.zhihu.com/people/xxx -f html

# 同时导出 MD 和 HTML
python zhihu_exporter.py https://www.zhihu.com/people/xxx -f both

# 限制抓取 20 条，指定并发数为 8
python zhihu_exporter.py https://www.zhihu.com/people/xxx --limit 20 --concurrency 8

# 全量重新抓取
python zhihu_exporter.py https://www.zhihu.com/people/xxx --no-incremental

# 使用配置文件（--config 可省略：不传时自动加载 config.yaml，再回退 config.example.yaml）
python zhihu_exporter.py --config config.yaml

# 导出专栏全部文章（自动识别专栏链接）
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx

# 专栏 + 双格式
python zhihu_exporter.py https://zhuanlan.zhihu.com/c_xxx -f both

# 专栏 + 关键词过滤
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx --keyword "关键词"
```

## ⌨️CLI 模式

```
python zhihu_exporter.py [用户主页URL] [选项]
```

### 输入选项

| 参数 | 说明 |
|------|------|
| `user_url` | 知乎用户主页 URL（例如 `https://www.zhihu.com/people/xxx`），**必填** |
| `-c, --cookie` | 知乎登录 Cookie 字符串 |
| `-C, --cookie-file` | 从文件读取 Cookie（每行一对 `name=value` 或完整 Cookie 字符串） |

### 输出选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-o, --output` | 输出根目录 | `output` |
| `-f, --format` | 输出格式：`md` / `html` / `both` | `md` |
| `-l, --limit` | 限制抓取条数，达到上限后停止 | 不限制 |
| `--download-images` | 下载图片到本地或上传到图床 | 不下载 |
| `--image-host` | 图片托管方式：`local` / `gitee` | `local` |
| `--gitee-token` | Gitee 个人访问令牌（image-host=gitee 时必需） | — |
| `--gitee-repo` | Gitee 仓库，格式 `owner/repo`（image-host=gitee 时必需） | — |
| `--gitee-branch` | Gitee 仓库分支名 | `master` |
| `--gitee-path-prefix` | Gitee 仓库中的路径前缀 | — |

### 抓取选项

| 参数 | 说明 |
|------|------|
| `--mode` | 抓取模式：`upvotes`=点赞的他人内容（默认）；`articles`=自己创作的文章；`answers`=自己创作的回答；`all`=两者都要；`column`=导出专栏全部文章（**后四种免浏览器/免签名**；专栏 URL 自动识别，无需显式 `--mode column`） |
| `--keyword` | 标题关键词过滤，仅 `--mode articles/answers/all/column` 生效 |
| `--preview` | 预览模式：仅列出专栏文章元信息（标题/日期/赞数/评论/链接），**不写入文件**（仅 `--mode column` 生效） |
| `--incremental` / `--no-incremental` | 增量模式成对开关；`--no-incremental` 全量重新抓取所有点赞内容 |
| `--no-scan` | 跳过 Playwright 扫码模式，仅使用手动粘贴 Cookie |
| `--concurrency` | 异步并发数，控制 aiohttp 同时请求数（默认 5） |
| `--only-answers` | 仅导出赞同的回答，跳过文章 |
| `--only-articles` | 仅导出赞同的文章，跳过回答 |
| `--config, -cfg` | 从 YAML 配置文件加载参数 |

### 浏览器选项（扫码时生效）

| 参数 | 说明 |
|------|------|
| `--visible` | 扫码登录时显示浏览器窗口（默认后台运行） |

### Cookie 文件格式

支持两种格式：

```
# 格式一：完整 Cookie 字符串（单行）
z_c0=xxx; d_c0=xxx; _zap=xxx

# 格式二：逐行 name=value
z_c0=xxx
d_c0=xxx
_zap=xxx
```

### 图片下载

使用 `--download-images` 可将回答/文章中的图片下载到本地或上传到 Gitee 图床，避免知乎图床链接失效导致图片无法访问。

**本地模式**（默认）：

```bash
python zhihu_exporter.py https://www.zhihu.com/people/xxx --download-images
```

图片保存到 `output/<用户名>/assets/images/<条目ID>/` 目录，内容中的图片链接自动替换为相对路径 `../assets/images/<条目ID>/<图片名>`。

**Gitee 图床模式**：

```bash
python zhihu_exporter.py https://www.zhihu.com/people/xxx \
    --download-images --image-host gitee \
    --gitee-token YOUR_ACCESS_TOKEN \
    --gitee-repo owner/repo
```

图片上传到 Gitee 仓库后，内容中的图片链接自动替换为 Gitee raw URL（`https://gitee.com/owner/repo/raw/branch/...`）。

> Gitee Token 获取：Gitee → 设置 → 私人令牌 → 生成新令牌，勾选 `projects` 权限即可。

## ✍️作者原创模式

除默认的「点赞导出」外，还可直接导出**某个用户自己创作**的文章 / 回答（免浏览器、免签名）：

```bash
# 导出某作者的全部原创文章
python zhihu_exporter.py https://www.zhihu.com/people/xxx --mode articles

# 导出某作者的全部原创回答
python zhihu_exporter.py https://www.zhihu.com/people/xxx --mode answers

# 文章 + 回答都要（推荐）
python zhihu_exporter.py https://www.zhihu.com/people/xxx --mode all -f both

# 只要标题包含「缚茧」的章节（长篇小说 / 连载定向归档）
python zhihu_exporter.py https://www.zhihu.com/people/xxx --mode articles --keyword "缚茧"
```

**技术原理**：作者模式走 `/api/v4/members/{token}/articles` 与 `/api/v4/members/{token}/answers`
列表接口，参数带上 `include=data[*].content` 后，**正文会直接内嵌在列表响应里**，
因此无需请求单篇详情接口（后者会触发 `x-zse-96` 签名校验，返回 HTTP 403 / code 10003），
**全程无需 Playwright、无需逆向签名**，只需要一个有效的登录 Cookie。

**输出结构**（在默认点赞目录旁并列生成）：

```
output/
└── <用户名>/
    ├── 原创文章_md/          # 原创文章（Markdown）
    ├── 原创回答_md/          # 原创回答（Markdown）
    ├── 原创文章_html/        # 原创文章（HTML，-f html/both）
    ├── 原创回答_html/        # 原创回答（HTML）
    └── .progress_author.json # 作者模式进度记录
```

文件命名：`日期_标题_条目ID.md`（`sanitize_filename` 清理非法字符，条目 ID 保证同名不冲突）。
每篇头部带作者主页、发布时间、原文链接；文章优先取 API 封面图。

> 与点赞模式的区别：点赞模式抓的是某账号**点赞过的他人内容**（走 moments 动态流），
> 作者模式抓的是某账号**自己的原创内容**（走 members 列表接口）。两者输出目录互不干扰。

## 🗂️专栏模式

除点赞导出和作者原创模式外，还支持直接导出**某个知乎专栏**的全部文章：

```bash
# 自动识别专栏链接（推荐），无需 --mode
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx
python zhihu_exporter.py https://zhuanlan.zhihu.com/c_xxx

# 显式指定 --mode column
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx --mode column

# 双格式导出
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx -f both

# 关键词过滤
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx --keyword "关键词"

# 预览专栏文章列表（仅元信息，不下载）
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx --preview

# 预览前 10 篇
python zhihu_exporter.py https://www.zhihu.com/column/c_xxx --preview --limit 10
```

**技术原理**：专栏模式走 `/api/v4/columns/{column_id}/articles` 接口，
先请求 `/api/v4/columns/{column_id}` 获取专栏元信息（标题、描述），
再分页拉取文章列表。参数带上 `include=data[*].content` 后，
**正文直接内嵌在列表响应中**，无需单篇详情接口（后者触发 `x-zse-96` 签名校验），
**全程无需 Playwright、无需逆向签名**，只需要一个有效的登录 Cookie。

**输出结构**（输出目录以专栏名命名，与点赞/作者目录互不干扰）：

```
output/
└── <专栏名称>/                   # 使用专栏标题自动命名目录
    ├── 专栏文章_md/              # 专栏文章（Markdown）
    ├── 专栏文章_html/            # 专栏文章（HTML，-f html/both）
    └── .progress_column.json     # 专栏模式增量进度记录
```

文件命名：`标题.md`（**仅标题，无日期/ID 前后缀**，简洁易读）。
每篇头部带专栏名称、作者主页、发布时间、原文链接。

## 📝配置文件

通过 `--config` 可将参数写入 YAML 配置文件，避免每次都在命令行输入冗长的 Token 和 Repo。

**示例**（参考仓库内 `config.example.yaml`）：

```yaml
# 图片下载 - Gitee 图床模式
download_images: true
image_host: gitee
gitee_token: "your_gitee_personal_access_token"
gitee_repo: "your_username/your_repo"
gitee_branch: "master"
gitee_path_prefix: "zhihu-images"   # 可选
```

使用（--config 可省略，不传会自动读取当前目录的 config.yaml）：

```bash
python zhihu_exporter.py --config config.yaml
```

配置文件中可设置的参数和 CLI 参数一一对应，CLI 传入的值优先级更高。

## 📂项目结构

```
zhihu-upvote-exporter/
├── zhihu_exporter.py   # 向后兼容桩（委托给包）
├── zhihu_exporter/     # 核心代码（13 个模块）
│   ├── __init__.py            # 版本号
│   ├── __main__.py            # python -m 入口
│   ├── main.py                # CLI 参数解析 & 主流程
│   ├── export.py              # 异步爬取核心 & 条目处理（点赞模式）
│   ├── author.py              # 作者原创内容抓取（articles / answers 模式，免浏览器/免签名）
│   ├── column.py              # 专栏文章抓取（免浏览器/免签名）
│   ├── formatters.py          # Markdown / HTML 格式输出
│   ├── images.py              # 图片下载 & 图床上传
│   ├── summary.py             # 统计报告 & 作者页面生成
│   ├── categories.py          # 领域分类：13 大类关键词表 + 手动覆盖表（MANUAL_OVERRIDES）
│   ├── utils.py               # 工具函数（URL 提取、封面图等）
│   ├── config.py              # 配置加载 & 默认参数
│   ├── auth.py                # Cookie 验证 & 扫码登录
│   └── progress.py            # 增量进度读写
├── requirements.txt           # Python 依赖
├── README.md
├── LICENSE
└── .gitignore
```

导出后的输出目录结构：

```
output/
└── <用户名>/
    ├── 赞同的回答_md/         # Markdown 格式回答
    ├── 赞同的文章_md/         # Markdown 格式文章
    ├── 赞同的回答_html/      # HTML 格式回答（-f html/both）
    ├── 赞同的文章_html/      # HTML 格式文章（-f html/both）
    ├── authors/              # Top 10 作者独立页面（仅 HTML 格式）
    ├── summary.html          # HTML 统计报告（概览 + 日期分布条形图 + 排行）
    ├── summary.md            # MD 统计报告（Markdown 表格版）
    ├── assets/images/        # 下载的图片（--download-images）
    └── .progress.json        # 增量进度记录
```

## ⚙️配置说明

`config.example.yaml` 中可配置项（命令行参数优先级更高，键名遵循《爬虫项目指南》统一规范）：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `auth.cookie` | 知乎登录 Cookie 字符串 | 空 |
| `auth.cookie_file` | Cookie 文件路径 | — |
| `request.delay` | 每页请求间隔（秒） | `0.8` |
| `request.max_retries` | 单页最大重试次数（429 限流时等待重试） | `3` |
| `user_url` | 知乎用户主页 URL | 空 |
| `output_dir` | 输出根目录 | `output` |
| `format` | 输出格式：`md` / `html` / `both` | `md` |
| `limit` | 限制抓取条数 | 不限制 |
| `incremental` | 增量模式（false = 全量重抓） | `true` |
| `concurrency` | 异步并发数 | `5` |
| `download_images` / `image_host` | 图片下载及托管方式 | 关闭 / `local` |

## ❓️FAQ

**会不会封号？**

风险极低。程序调用知乎官方 API，行为与正常浏览一致。默认 0.8 秒翻一页，遇到 429 限流自动等待 5 秒重试。最坏情况是弹出验证码，不会直接封号。

**增量模式怎么工作的？**

每次运行后会在输出目录生成 `.progress.json`，记录最后一条点赞的时间戳。下次运行时只抓取该时间之后的新点赞。MD 和 HTML 两种格式的进度独立记录，互不干扰。无新增内容时会跳过统计报告生成（v3.1 起），有新增时才重新生成报告。

**中途中断了怎么办？**

Ctrl+C 中断或请求失败后会自动保存进度到 `.progress.json`（try/finally 保证）。进度时间戳只推进到"已完整处理"的页，因此中断不会丢失未抓取的内容，重新运行后增量模式会从最后一个完整页继续抓取。已写入的文件会被 `os.path.exists` 检查跳过，不重复下载。使用 `--no-incremental` 全量重抓时，已有文件会被重新写入覆盖。

**能不能只导出回答或只导出文章？**

可以。使用 `--only-answers` 仅导出回答，`--only-articles` 仅导出文章。两个参数互斥，不能同时使用。

**macOS / Linux 能用吗？**

完全支持。核心依赖 `aiohttp` 和 `playwright` 均为跨平台库。

## 🤝贡献

欢迎提 Issue 和 PR！以下是一些潜在的改进方向，供有兴趣贡献的同学参考：

### 已知问题 / 待改进点

- [x] ~~**关键词过滤**：新增 `--filter "关键词"`，仅导出标题或正文匹配指定关键词的内容，支持知识库定向归档。~~（v3.4 实现：新增 `--keyword` 参数，按标题关键词过滤内容）
- [x] ~~**专栏文章导出**：支持输入专栏链接，直接导出专栏全部文章。~~（v3.4 实现：新增 `--mode column`，专栏 URL 自动识别）
- [ ] **导出单文件合集**：新增 `--merge` 模式，将所有点赞合并输出为一个 Markdown / HTML 文件（含目录导航），方便全文搜索和阅读。
- [ ] **增量模式自动刷新赞同数**：增量运行时，自动刷新已导出条目的赞同数（Top N 高赞条目），通过 `--refresh-top` 参数控制刷新数量，默认 100，设为 0 则禁用。
- [ ] **多账号 Cookie 轮换**：支持配置多个 Cookie 文件路径，触发风控时自动轮换，适合大量抓取场景。
- [ ] **Web UI 模式**：提供 `--serve` 启动本地 Web 界面，浏览器内输入 URL 和配置，避免命令行操作。

### 贡献流程

1. Fork 本仓库
2. 创建分支：`git checkout -b feature/your-feature`
3. 提交修改：`git commit -m "描述本次改动"`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

有任何疑问欢迎提 Issue 讨论 😊

## 📋更新日志

### v3.4（当前版本）

- **新增：** `--mode` 抓取模式：除默认点赞导出外，新增 `articles` / `answers` / `all` 三种作者原创导出（免浏览器、免签名），支持 `--keyword` 标题关键词过滤
- **新增：** `--mode column` 专栏导出：输入专栏链接自动识别并导出专栏全部文章，支持增量、关键词过滤、多格式输出（免浏览器、免签名）
- **新增：** `--preview` 专栏预览模式：**无需下载**即可快速浏览专栏文章列表（标题/日期/赞数/评论/链接），支持 `--limit` / `--keyword` 配合使用
- **新增：** `column.py` 专栏导出模块，走 `/api/v4/columns/{column_id}/articles` 接口，正文内嵌无签名校验
- **优化：** 专栏文章文件名仅使用标题，无日期/ID 前后缀，简洁易读
- **修复：** 配置文件缺失 `page_delay` / `max_retries` 时 `'Namespace' object has no attribute` 报错（`getattr` 安全取值）

### v3.3
- **变更：** 配置键对齐《爬虫项目指南》统一规范：顶层 `cookie` / `cookie_file` 移入 `auth` 节、`output_dir` 统一命名、`no_incremental` 改名 `incremental`（取反）；CLI `--no-incremental` 改为 `--incremental` / `--no-incremental` 成对开关；配置文件仅支持 YAML，移除遗留 JSON 配置（`config.example.json` 已删除）
- **新增：** `request.delay` / `request.max_retries` 配置项——翻页间隔与重试次数从源码常量提为可配置

### v3.2

- **新增：** 封面提取：文章用 API `image_url`、回答提取正文首图，Markdown 文末追加 `![cover]`、HTML 展示封面；Markdown 同样支持懒加载图静态化
- **优化：** 增量模式下已存在的文件直接跳过；统计报告分组与手动覆盖表匹配提速；清理死代码；示例配置默认关闭图片下载 / Gitee 图床
- **修复：** 中途中断 / 请求失败不再丢数据：进度只推进到已完整处理的页，中断时自动保存
- **修复：** 扫码登录真正等待登录成功（轮询 `z_c0` Cookie）；`--concurrency` 真正限制全部请求并发（列表页 / 问题详情 / 图片下载共享同一信号量）

### v3.1

- **新增：** 领域分类体系（`categories.py`）：统计报告按 13 大领域自动归并知乎官方标签（影视与文艺 / 两性与婚恋 / 科技与互联网 / 教育与成长 / 时事与政治 / 历史与文化 / 情感与心理 / 生活与健康 / 游戏与电竞 / 职场与体制 / 体育与竞技 / 自然科学与科普 / 经济与商业），报告新增"领域分布"小节（折叠式条形图，点击领域展开该领域全部条目）
- **新增：** 手动覆盖表 `MANUAL_OVERRIDES`：可按问题ID / 问题链接 / 问题标题精确指定所属领域（优先级最高），无标签的文章与冷门问题也能归类
- **新增：** HTML 统计报告左侧目录侧边栏：固定导航（概览 / 日期分布 / 领域分布 / 最新点赞 / 作者排行 / 赞同数排行），点击平滑滚动跳转
- **新增：** 统计报告新增"最新点赞 Top 10"章节（按赞同时间倒序），概览表格新增"历史累计"回答 / 文章数
- **新增：** 页面图标：统计报告与内容页内嵌 favicon（data URI，无外部文件依赖），源文件随项目版本控制
- **优化：** 增量模式下无新增内容时跳过统计报告生成，避免全量重扫上千个文件，无新增时运行秒级完成；有新增时才重新生成 `summary.html` / `summary.md` 及作者页面
- **优化：** MD 输出目录更名"赞同的回答_md / 赞同的文章_md"，与 HTML 目录的 `_html` 后缀对齐
- **修复：** 不传 `--config` 时未自动加载 `config.yaml` 的问题，现按 `--config` 参数 > `config.yaml` > `config.example.yaml` 的优先级自动查找配置文件
- **修复：** 图片链路多处修复：图片处理模块未定义变量导致图片从未真正下载上传、Gitee 重复上传中文提示不匹配、知乎懒加载图（`data-actualsrc`）不识别致页面空白、`unicom` 包装域名连接超时；已补齐历史 443 个文件的图片并静态化懒加载图（另有 220 个文件图片因知乎源站删除 404 无法恢复）

### v3.0

工程化重构版本：1937 行单文件拆分为 11 个模块，净减约 255 行。

- **新增：** `summary.py` 统计报告模块，导出完成后自动扫描文件系统生成 `summary.html`（概览表格 + 日期分布条形图 + 作者排行 Top 10 + 赞同数排行 Top 50）、`summary.md`（纯 Markdown 表格 + ASCII 柱状图），并生成 `authors/` Top 10 作者独立页面（仅 HTML 格式，`-f both` 时两版报告同时产出）
- **新增：** 根目录保留 `zhihu_exporter.py` 兼容桩（7 行），旧用法完全不变
- **优化：** 清理重复定义，统一配置加载路径

### v2.1

- **优化：** 移除 tqdm 进度条依赖
- **优化：** `requirements.txt` 精简为仅依赖 aiohttp
- **修复：** `asyncio.gather` 异常丢失问题，单个条目处理失败不再导致整页结果丢弃
- **修复：** `-f both` 双格式导出时进度计数虚高的 bug，改为按格式独立追踪实际写入数
- **修复：** 文件写入并发覆盖问题，改为临时文件 + `os.replace` 原子重命名
- **修复：** 同名标题文件冲突，文件名追加 `answer_id` / `article_id` 后缀保证唯一性

### v2.0

- **新增：** 架构升级，从 requests 同步迁移至 aiohttp 异步并发，新增 `--concurrency` 参数
- **新增：** `--config` / `-cfg` 参数，支持 YAML / JSON 配置文件
- **新增：** 输出格式 `both`，同时导出 Markdown 和 HTML
- **优化：** 进度记录按格式隔离，`-f both` 时两种格式的增量进度互不干扰
- **优化：** 延迟导入 aiohttp / yaml，`--help` 无需安装依赖即可运行

### v1.0

- 首个版本：支持 Cookie / 扫码 / 文件三种登录方式
- Markdown 和 HTML 双格式输出
- 增量爬取机制，基于 `.progress.json` 断点续爬
- Playwright 自动扫码登录

## ☕捐赠

如果你觉得本项目帮助了你，请作者喝一杯咖啡，你的支持是作者最大的动力。本项目会持续更新。

| 支付宝 | 微信 |
|--------|------|
| ![支付宝](./assets/donate_alipay.jpg) | ![微信](./assets/donate_wechat.jpg) |

## ⚠️免责声明

本工具仅供学习交流使用，不得用于任何违反法律法规或侵犯第三方权益的用途。
因使用本工具产生的一切后果由使用者自行承担，作者不承担任何法律责任。

## 📃许可证

[MIT License](LICENSE) — 随便用，标注来源即可。
*（内容由AI生成，仅供参考）*
