# 产品范围

HTP Insight 是 Qualcomm HTP 性能诊断工具。它连接编译前 ONNX、编译后图与设备证据，帮助回答哪些模块耗时、时间和周期统计的口径、哪些映射可靠，以及下一轮实验如何证伪假设。

| 工作流 | 目标 |
| --- | --- |
| 模型导入 | ONNX、QDQ、AIMET Encodings、DLC 与 HTP Context 的身份和兼容性 |
| 采集与导入 | 本机 ORT CPU 与 Android QAIRT HTP。保留 Basic/Detailed、Linting、Optrace、QHAS 和编译图 |
| 图与证据 | ONNX 张量、语义模块、版本化的 HTP → QNN → ONNX 映射、Unknown 和原始证据 |
| 诊断 | Node/Module 归因、时间线、量化标注、可证伪的优化假设 |
| 实验 | 匹配输入、设备、后端和采集条件的 A/B，延迟分位数、原始样本和数值误差 |
| 接口 | 统一 Core 驱动 Web、CLI 和 MCP，链接可以回到同一条证据 |

模型训练和大模型本体适配在外部项目中完成。HTP Insight 的示例覆盖可运行的小 Batch Transformer 与 Qualcomm MobileNet‑v2。

## 验收顺序

1. 可复现地采集和导入同一模型的证据。
2. 在 Web 和 MCP 核对同一个 HTP 热点与原始证据。
3. 在相同条件下重跑 Baseline 与 Candidate，并报告收益、退化或观测不确定性。
4. 保持 Mac ORT 工作流独立可运行，并保留 Android 与 Linux 扩展边界。
