# HTP Insight 工程指南

## 产品边界

HTP Insight 将真实的 ONNX、ORT、Qualcomm QAIRT/QNN/HTP 证据整理成可定位的 Graph、Profile、热点、比较和实验假设。Core 是 Web、CLI 和 MCP 的共同入口。外部训练、量化和正式部署由对应项目负责。示例可包含复现实验所需的导出与校准。

## 从干净检出启动

在仓库根目录使用 Python 3.11、Node.js 22+、npm 和 Make。Mac 或 Linux 上可以先运行 CPU 工作流。

```bash
make doctor
make install
.venv/bin/python -m examples.demo --tiny-only
make test
make web
```

打开 [本地工作台](http://127.0.0.1:8000/)。首页的 Guided analysis 读取刚生成的真实 Tiny Transformer ORT 数据。需要 MobileNet 实测时运行 `make demo`，首次会下载公开模型。 `make notebook` 重新执行 Packed QKV 适配例子。

输入与模型暂存到 `runs/inbox/`。模型、Profile、原始证据和 A/B 记录位于 `runs/store/<id>/`。浏览器截图与验收收据位于 `runs/verification/`。远程检出包含源码和解析 Fixture。真机示例 ID 及其本地链接需要已有工作区或新采集。

并行启动独立工作区时，为 Web、CLI 和 MCP 设置同一个 `HTP_INSIGHT_DATA` 与 `HTP_INSIGHT_WEB`，例如把数据指向 `runs/dev`、URL 指向 `http://127.0.0.1:8010`，并运行 `make web PORT=8010`。

## 修改入口

| 要改的东西 | 首选入口 |
| --- | --- |
| 数据契约、导入和持久化 | [schema.py](htp_insight/schema.py)、[core.py](htp_insight/core.py) |
| ONNX 结构、量化、作用域和归因 | [graph.py](htp_insight/graph.py)、[analysis.py](htp_insight/analysis.py)、[qnn_evidence.py](htp_insight/qnn_evidence.py) |
| ORT、版本化 Trace 解析和 Profile | [profiles.py](htp_insight/profiles.py)、[qnn.py](htp_insight/qnn.py) |
| HTP 通道、依赖与阻塞 | [htp_timeline.py](htp_insight/htp_timeline.py)、[hardware-timeline.tsx](web/src/hardware-timeline.tsx)、[Timeline in main.tsx](web/src/main.tsx) |
| Web、CLI、MCP 工具 | [web.py](htp_insight/web.py)、[interfaces.py](htp_insight/interfaces.py)、[mcp_server.py](htp_insight/mcp_server.py) |
| 真机采集与浏览器入口 | [android.py](htp_insight/android.py)、[android_web.py](htp_insight/android_web.py)、[run_android_qnn.py](scripts/run_android_qnn.py) |
| 实验建议和 Notebook | [experiment_plan.py](htp_insight/experiment_plan.py)、[examples/](examples/)、[docs/experiments/](docs/experiments/) |

## 真机、MCP 和验收

- 在 Android 上先核对 `adb get-state`、`adb shell getprop ro.soc.model` 和已验证的 Hexagon 版本。配置 `QAIRT_SDK_ROOT`，必要时设置 `ADB_BIN` 和 `HTP_INSIGHT_ADB_SERIAL`。Optrace 需要同一 Context 编译产物生成的 schematic；用对应 DLC 和 Framework CSV 做源模型归因。 [Android 采集指南](docs/android-runner.md)
- 时间线从 Optrace 和 QHAS 元数据读取资源类型及实例。Core 不可用时保留 PID，TID 的数值和 `uses_*` 标志不能用来推导通道。保留冲突、缺失、原始行和证据 ID。通道数量描述本次采集，跨核心阻塞需要验证过的时钟和调度证据。 [时间线实测与验收](docs/experiments/htp-parallelism.md)
- 生成 Tiny 数据后，用 `.venv/bin/python -m htp_insight catalog` 核对 CLI 能读取模型和实测记录。独立 MCP 回归用 `.venv/bin/python -m scripts.mcp_smoke`。项目 `.mcp.json` 通过 `make mcp` 启动 stdio 服务器，Claude Code 中项目服务器由用户批准。 [MCP 工具和启动说明](docs/mcp.md)
- Web 改动执行 `npm --prefix web run build` 并启动服务后运行 `make browser`。需要时通过 `CHROME_BIN` 指定浏览器。 `HTP_INSIGHT_BROWSER_ACCEPTANCE=1 make browser` 会在指定工作区写入真实 ORT/A/A 数据，`HTP_INSIGHT_BROWSER_ANDROID=1 make browser` 需要已准备好的本地真机样例与 ADB。 [验收用法](docs/audit/product-gap-review.md)

## 开发约定

- 先读 [产品范围](docs/product.md)、[数据与接口架构](docs/architecture.md) 与 [当前路线图](docs/roadmap.md)。使用 `git status --short --branch` 核对现有改动。
- 保留原始文件、SDK 版本、设备、运行条件和稳定证据 ID。微秒、DSP cycles、计数和估算保持独立。缺失字段返回 null，归因失败保留 Unknown。只在来源和实验条件吻合时比较延迟。
- 使用真实 SDK 导出验证版本化解析。硬件或工具链不可用时写明阻塞点，使用明确标记为 Fixture 的测试数据。
- ONNX 源节点和 HTP 操作可以多对多关联。归因需要可检查的编译或运行证据。推测作为 hypothesis 表达，保持与测量分离。
- Android 验证使用 ADB shell 下项目自己的临时目录。SDK、工具镜像、模型、设备日志、大型数据和生成结果放在 `runs/`。模型保持本地处理。禁止将密钥、设备序列号、个人日志、私有样本或 SDK 二进制提交到 Git。
- Core 保持可移植性。设备采集和 QAIRT 转换工具通过显式参数或注册的适配器运行。MCP 避免任意 Shell 执行入口。
- 运行 `make test`，核对改动涉及的实际入口。验证后更新对应的审计或实测记录，注明真机验收与 Fixture 的覆盖范围。
- 按功能分批提交，每批包含必要的验证和文档。尊重已有的工作树改动。推送需有用户授权，推送后核对远程分支的提交。
