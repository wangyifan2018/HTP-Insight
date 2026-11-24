# 功能矩阵

状态以 2026-11-24 开工时 `d5c72a3` 为基准。Verified 表示真实运行已核对，Partial 表示能力存在适用边界，Missing 表示缺少产品入口或实现。Mock 和 Stub 仅用于确实没有对应实测能力的情形。

| 功能 | 开工状态 | 源码和验证 |
| --- | --- | --- |
| ONNX 导入 | Verified | [`Core.import_model`](../../htp_insight/core.py#L73) 和 [`graph.inspect`](../../htp_insight/graph.py#L81)。Tiny Transformer 和 MobileNet 源文件成功注册，浏览器读取真实图。 |
| AIMET / QDQ | Verified | [`graph.py`](../../htp_insight/graph.py#L27)。真实 AIMET Encodings 与 MobileNet W8A8 QDQ 展示通过浏览器检查。 |
| Graph Explorer | Verified | [`GraphView`](../../web/src/main.tsx#L100)。真实图可按模块定位并选中节点，已验证 Graph 与 Timeline 双向定位。 |
| 语义映射 | Partial | [`module_name`](../../htp_insight/graph.py#L67) 按 ONNX 导出作用域归组。真实 Tiny Attention 和 MLP 已验证，任意模型的多层语义范围有待扩展。 |
| ORT Profiling | Verified | [`run_ort_profile`](../../htp_insight/core.py#L161) 和 [`benchmark`](../../htp_insight/profiles.py#L260)。Apple M2 的真实 CPU 测量、Trace、输出和复跑通过。 |
| QNN Profiling | Verified | [`AndroidRunner`](../../htp_insight/android.py#L20) 和[采集记录](../android-runner.md)。SM6650 实测四种模式，Web 提供已有测量的导入与查看。 |
| 热点 | Verified | [`analysis.rank`](../../htp_insight/analysis.py#L18) 从去重操作和映射聚合。真实 MCP 读取 Attention 176,616 cycles，并核对多个 HTP 原始操作。 |
| 瓶颈诊断 | Partial | [`Core.explain_hotspot`](../../htp_insight/core.py#L246) 提供证据与编译映射。硬件根因仍需实验证伪，详情缺少明确的证据分层。 |
| 优化建议 | Partial | [`analysis.hypothesis`](../../htp_insight/analysis.py#L58) 为规则假设。已有验证指标及手写任务，产品内自动生成和导出缺失。 |
| MCP | Verified／Partial | [`build_server`](../../htp_insight/mcp_server.py#L7)。独立 Python MCP SDK 客户端通过；已有 Claude Code 项目配置，Claude Code 进程是否可直接调用仍需该客户端自行启用。 |
| A/B | Verified | [`compare_experiments`](../../htp_insight/core.py#L288)。Mac CPU 和 Android HTP 均有真实比较，浏览器验证原始报告下载和条件差异提示。 |
| 初次使用与状态 | Missing | [`App`](../../web/src/main.tsx#L443) 为三个专业视图，尚无引导式首页、真实示例入口或能力状态。 |
| Linux / SSH | Stub／Missing | [`QnnNativeRunner`](../../htp_insight/profiles.py#L25) 定义接口。已有通过 Linux 用户态调用 QAIRT 转换器的记录；专用 Linux 执行和 SSH 采集未实现。 |

整条用户路径使用实测文件。Fixture 可通过导入界面显式登记，保留 Fixture 来源，未纳入上述设备结论。完整源码、报告与现有产物间的链接见 [Mac](../experiments/macos-mvp.md) 和 [Android](../experiments/android-tiny-htp-ab.md) 验收记录。
