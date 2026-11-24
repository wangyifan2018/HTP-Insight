# HTP Insight 规格复审与优化结果

2026-11-24，以提交 `8113892` 和原始产品规格为检查基准。本轮用项目测试、真实浏览器、Mac ORT 与连接的 SM6650 核查，不将解析 Fixture 当成性能记录。

| 复审发现 | 本轮处理 | 验收证据 |
| --- | --- | --- |
| 导入要求先手工放文件，外置张量可能丢失相对路径 | Web 支持单个文件、多个张量及父目录，同一上传批次保留相对路径。原有 CLI、MCP Inbox 路径继续可用 | 浏览器导入带 `weights/tensors.data` 的真实 ONNX，完成 ORT 和命名 A/A。主工作区也实测了浏览器导入 DLC |
| 编译产物与源图分离，实验只能用短 ID 区分 | DLC 或 Context 支持显式绑定已有 ONNX；实验可命名并随 JSON、Markdown 记录；旧模型和实验 ID 保持有效 | 上传实测 DLC 后，浏览器沿配对源图进入采集；隔离环境通过命名 A/A |
| Android 必须切到终端，状态页只显示历史结果 | Web 探测本地 SDK/ADB/ABI 和已验证架构；对配对产物运行现有 AndroidRunner，保留产物 ID、哈希和运行条件 | 通过页面在 SM6650 实际执行 Basic，Profile 返回 measured；Optrace 已通过同一 runner 实测 |
| Web 目录重复验证完整事件，初始图和时间线对大文件较重 | Web 使用按文件替换信息缓存的轻量目录；图画布限制显示范围；时间线支持缩放、搜索和分页，过时请求可取消 | 同一实测库的热请求本地中位数 64.23 → 9.86 ms，返回大小 170,975 → 131,235 bytes；完整 Profile 保留原始样本 |
| 未命名模型难以定位，早完成的前置操作可能误列为阻塞 | 未命名图保守识别直接的 Attention/MLP 数据流模式。候选阻塞必须来自最新完成的已记录前置依赖 | 新图单测；真实 Optrace 重查仍保留原有首选候选，浏览器验证缩放和依赖选择 |
| Tiny rank-3 与 Qwen 扩展缺少新测量 | 执行 Tiny 8 输入数值检查、3 组 A/A、6 组 A/B 及 Optrace。将 Qwen 真实第一层 MLP 拆出并在 HTP 试跑 | Tiny 数值通过，速度收益不确定。Qwen 分段有真实 Profile，三种配方尚未通过精度门槛 |

源码与实验细节见 [Web 采集](../../htp_insight/android_web.py)、[本地上传](../../htp_insight/uploads.py)、[核心模型与目录](../../htp_insight/core.py)、[Timeline 分析](../../htp_insight/htp_timeline.py)、[Tiny A/B](../experiments/claude-code-attention-layout.md) 和 [Qwen 复验](../experiments/qwen3-tts-code-predictor.md)。

验收命令为 `make test`、`npm --prefix web run build`、`HTP_INSIGHT_BROWSER_ANDROID=1 make browser` 和隔离工作区的 `HTP_INSIGHT_BROWSER_ACCEPTANCE=1 make browser`。21 项单测、16 项主工作区和 5 项隔离浏览器检查通过。页面生成的 Basic Profile 为 `profile-88096b6fcb6c3eef159b4a40`，其中 `compiled_artifact_id` 指向本次上传的 DLC。 [主工作区](../../runs/verification/browser.json) · [隔离工作区](../../runs/verification/product-acceptance/cpu/verification/browser.json) · [真机时间线截图](../../runs/verification/htp-parallelism.png)

CLI 和独立 MCP 客户端可访问本地实测数据。MCP stdio 客户端重新读取 Qwen 分段 HTP 时间线和 Tiny 命名 A/B。Claude Code 客户端检查仍返回 `Pending approval`。专用 Linux/SSH 需要授权目标，完整 Qwen HTP 和新硬件资源种类需设备证据。 [MCP 实际响应](../../runs/verification/review-mcp.json) · [剩余要求](../roadmap.md)
