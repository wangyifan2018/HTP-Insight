# HTP Insight 工程审计

本次更新的结论、修复与真实验收见 [规格复审与优化结果](product-gap-review.md)。以下为前一阶段的审计基线。

2026-11-24 审计起点为 `d5c72a3`。逐项证据见[功能矩阵](feature_matrix.md)。基线执行 `make test` 通过 17 项，`make browser` 通过 11 项，覆盖真实 ORT、DLC framework mapping、QAIRT CSV、HTP Optrace、原始证据联动和历史 Android A/B。真机能力核对使用已保存的 SM6650 原始采集。同一仓库中 `tests/fixtures/` 仅用于解析回归。

## 已有可用闭环

- Mac 上可导入真实 ONNX、解析 QDQ 和 AIMET，运行 ORT CPU、聚合模块与操作热点，再用原 Notebook 导出 Packed QKV Candidate，完成数值和性能比较。Web 支持 Graph 与 Timeline 双向定位，CLI、MCP 和 API 共用 Core。 [Mac 实测](../experiments/macos-mvp.md)
- 已连接的 Android 曾通过 ADB 真实执行 QAIRT Basic、Detailed、Linting 和 Optrace，并按操作 ID 关联 QHAS 与 HTP Graph。周期和与 Basic 图执行微秒各有口径。跨采集条件的 A/B 会列出不匹配字段。 [真机采集](../android-runner.md)

## 对照产品要求的缺口

1. **首次使用**。默认直接进入 Graph，并自动选择已有数据。缺少 Import → Profile → Locate → Diagnose → Optimize 的路径、可选的真实引导示例和能力状态页。侧栏固定显示 CPU，容易和 Android HTP 上下文混淆。
2. **诊断易读性**。热点列表有真实排名和口径，详情主要展示规则假设。需要把原始事件、图结构、映射、推断边界和下一步放到同一个面板。图已按模块隔离，搜索与高亮可以进一步贴近模块级定位。缺少针对来源的术语说明和浅色适配。
3. **Claude Code 交接**。现有 `suggest_experiments` 返回有限的规则建议。已手写一份 [HTP 适配任务](../experiments/claude-code-attention-layout.md)，尚未通过当前热点自动生成、复制、下载与 MCP 查询。缺少一次调用即可取回主要性能证据的聚合工具。
4. **运行边界**。Web 可运行 ORT 和导入 QNN，真机采集经本地 Android runner。QNN/HTP 专有文件仍由 QAIRT 转换。专用 Linux/SSH 远程 runner、自动派发 Notebook、通用 HTP 微架构根因诊断属于后续边界。

## 架构评估

Core、版本化适配器与接口层的职责清晰。原始文件和稳定 ID 可在工作区重新加载，统一数据模型可表达不同时间单位、映射来源和 Unknown。保留现有 FastAPI、React 与 stdio MCP。产品层新增只读的证据聚合和导出，继续复用 Core 的映射与比较规则。设备调用留在现有本地 runner。

## 本轮验收结果

五步首页、系统能力、真实引导、热点证据与 Notebook 交接已贯通。按实测来源显示延迟与证据，并对基础计时文件、归因不足和缺少设备采集给出明确状态。规则假设及建议验收线仍需在新的 Notebook 实验中验证。[使用流程](../ux/user_journey.md)

最终 18 项自动测试、13 项主工作区浏览器检查和隔离工作区的真实导入、ORT 采样与 A/A 检查均通过。Tiny Transformer 原 Notebook 的 Packed QKV 重新导出，FP32 输出一致。MCP SDK 复核本轮 Mac Profile 和已保存 Android HTP Profile 的计划与事件，Claude Code 项目入口仍待批准。[Mac 复验与证据](../experiments/mac_mvp_validation.md) · [剩余缺口](../roadmap.md)
