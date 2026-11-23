# Tiny Transformer · SM6650 HTP A/B

2026-11-23 在 HONOR MTN-AN80（SM6650、Hexagon V73、Android 16）执行。实验复用现有 Tiny Transformer Baseline 和 Packed QKV ONNX。两份模型与采集输入始终在本机或 USB 连接设备上处理。

## 编译与校准

- 使用 QAIRT 2.50.40.260831 的 Linux ARM64 转换器，容器为 Ubuntu 24.04 / Python 3.12。关闭 ONNX 自动简化以保留分解的 Attention 算子及原始名称。默认简化在本轮生成了当前 QAIRT 转换器无法识别的 ONNX Attention。
- FP16 DLC 转换完成。设备上的 HTP Op Validator 在 Baseline 的第一个 Reshape 拒绝该精度，并返回 `The SocModel doesn't support FP16`。验收改用相同 W8A16 配方。
- AIMET ONNX 2.44.0 用 48 个相同的固定种子校准样本逐模型生成 8-bit 权重和 16-bit 激活 Encodings。QAIRT 转换启用 `--enable_framework_trace`，用 `qairt-dlc-info --dump_framework_trace` 导出源算子对应关系。输入与输出的 QNN 类型均为 UINT16，Baseline 与 Candidate 的输入和输出 Scale、Zero Point 一致。
- Android 端用同一 runner、HTP backend 和 `default` 性能模式执行。用 `qnn-context-binary-generator` 在设备端为两份 DLC 生成带 Optrace 的 Context Binary，保持各自 schematic、DLC 和 Profile 配对。

[转换命令](../../runs/android-tiny/linux/convert-aimet.sh) · [Linux 镜像定义](../../runs/android-tiny/linux/Dockerfile) · [FP16 验证日志](../../runs/android-tiny/fp16-logcat.log) · [HTP Profiling 与 Optrace](https://docs.qualcomm.com/bundle/publicresource/topics/80-63442-10/htp_backend.html)

## 真机延迟与输出

在 6 组配对中交替 AB 和 BA。每组两版各执行 110 次，弃去前 10 次，每版合计 600 个用于分位数的 Basic 样本。主指标取 SDK CSV 的 `EXECUTE / NETRUN` 图执行时间。加速器时间按 `Accelerator (execute) time` 原样统计。设备电池温度首尾均报 22.0 °C。

| 指标 | Baseline | Packed QKV |
| --- | ---: | ---: |
| NetRun 图执行 p50 | 1.5320 ms | 1.6485 ms |
| NetRun 图执行 p95 | 1.8861 ms | 1.9561 ms |
| 加速器执行 p50 | 0.757 ms | 0.760 ms |
| 加速器执行 p95 | 0.783 ms | 0.780 ms |

Packed QKV 的图执行 p50 增加 7.60%，p95 增加 3.71%。六组中五组的图执行 p50 更慢，加速器延迟基本持平。本轮未观察到端到端图执行收益。

8 组独立于校准集的输入通过数值验证。对各自 FP32 ONNX 参考，Baseline 和 Candidate 的最大绝对差分别为 0.013878 和 0.013974。设备端 A/B 最大绝对差为 0.000193。验收阈值为 `atol=0.03`、`rtol=0.03`。

[逐组统计和数值 JSON](../../runs/android-tiny/summary.json) · [单组原始 Basic CSV](../../runs/android-tiny/baseline-basic-1/profile.csv) · [运行命令](../../runs/android-tiny/run-device.sh)

## Attention 归因

每版的 Optrace 都从相应 Context 采集，使用对应 schematic 和 framework-enabled DLC 转换。QAIRT 输出分别保留物理轨和按 QNN 算子查看的重复轨。导入器按 HTP ID、起始周期和持续周期去重，两版各解析 164 条唯一实测 HTP 操作。其中各有 158 条通过 `QNN Op Name → DLC framework CSV → ONNX 节点名` 归因，其余保留 Unknown。

例如 Baseline 的 HTP 操作 `0x0000415c00000036` 携带 `/attention/MatMul`。DLC framework CSV 将其关联到同名 ONNX 节点 `n17`。V 投影的 QNN `/attention/v/MatMul` 一对多关联 MatMul 和 Add。DLC 阶段可定位 Q、K、V 和 Packed QKV 投影。最终 HTP Trace 仅明确命名了部分相关操作，独立的 Q、K 和 Packed QKV 投影耗时仍留作未知。

归属于 Attention 的 Optrace 周期和为 176,616 → 125,661。这个和包含并行工作，各自约占当前 Trace 操作周期和的 70.86% 与 70.67%。Basic 延迟来自另一组可比实验，用于判断整图执行收益。

[Baseline DLC 映射 CSV](../../runs/android-tiny/baseline/aimet-w8a16.graph.csv) · [Baseline HTP 拓扑](../../runs/android-tiny/baseline-context/optrace/trace_htp.json) · [Baseline Optrace](../../runs/android-tiny/baseline-context/optrace/trace.json) · [Baseline QHAS](../../runs/android-tiny/baseline-context/optrace/trace_qnn_htp_analysis_summary.json)

## 结果入口

[Web A/B](http://127.0.0.1:8000/?view=diagnosis&experiment=experiment-01aaae99382190b5ebfcb1c4&profile=profile-2eeb593f32eabe2213210614) · [Markdown 导出](../../runs/android-tiny/report.md) · [MCP 响应](../../runs/android-tiny/mcp.json) · [Chrome 交互记录](../../runs/verification/browser.json) · [自动测试](../../runs/android-tiny/test.log)
