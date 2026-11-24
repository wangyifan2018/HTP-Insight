# Claude Code Notebook Adaptation 实验任务

在 HTP Insight 工程中复用 `examples/adaptation.ipynb` 和 `examples/tiny.py`，为 Tiny Transformer 的 Attention 评分 MatMul 新建一个单变量 Candidate。验证将 Batch 与 Head 合并为 MatMul 的单一批维，能否改变 HTP 的布局处理并改善整图延迟。保留原 Notebook、Baseline、历史 Packed QKV 结果及其原始产物。把新实验写到独立的 `runs/attention-score-layout/` 目录。

## 实验起点和证据

使用 2026-11-23 的实测 Baseline `profile-2eeb593f32eabe2213210614`，源 ONNX ID 为 `model-b88aa9a5c7a935222bb80954`。后端为 QNN HTP，设备为 HONOR MTN-AN80、SM6650、Hexagon V73、Android 16，QAIRT 为 `2.50.40.260831`，运行时构建为 `v2.50.40.260831140417`。使用 W8A16、`default` 性能模式及 FP32 raw I/O。用数据目录中的真实设备记录查询证据。若文件或设备不可用，在报告中写明缺失项与当前能验证的部分。

| Baseline Optrace 模块排序 | 实测操作 cycles 和 | 占该 Trace 操作周期和 | 去重后的操作事件 |
| --- | ---: | ---: | ---: |
| Attention | 176,616 | 70.86% | 123 |
| Unknown | 32,217 | 12.93% | 6 |
| MLP | 24,456 | 9.81% | 25 |
| Input Projection | 8,976 | 3.60% | 3 |

**Measured**。分母为 249,259 个 Optrace 操作 cycles，来自 164 条去重事件，含并行工作和 6 条未知归因。Cycles 和衡量此 Trace 中的操作成本，不能换算为整图延迟或当作关键路径。主延迟指标另取 Basic CSV 中的 `EXECUTE / NETRUN / ROOT` 单图时间。以下短事件 ID 均须加上 Baseline Profile 前缀和一个连字符。 [Baseline Top Hotspots](http://127.0.0.1:8000/?view=diagnosis&profile=profile-2eeb593f32eabe2213210614&hotspot=attention&level=module) · [原始 Optrace](../../runs/android-tiny/baseline-context/optrace/trace.json) · [Qualcomm HTP Profiling 文档](https://docs.qualcomm.com/bundle/publicresource/topics/80-63442-10/htp_backend.html)

| ONNX 节点 | 归因 cycles 和 | 可核查的单操作证据 |
| --- | ---: | --- |
| `n17` `/attention/MatMul`，评分 `QKᵀ` | 92,983（55 条） | `e205`，`0x0000415c00000036`，HVX `q::Transpose.2D`，13,609 cycles |
| `n21` `/attention/MatMul_1`，注意力概率乘 `V` | 42,022（33 条） | `e259`，`0x0000447600000040`，HVX `q::Transpose_impl`，17,823 cycles |
| `n20` `/attention/Softmax` | 27,207（3 条） | `e316`，`0x000045b20000003d`，HVX `q::Softmax_Crouton`，13,626 cycles |
| `n19` `/attention/Div`，评分缩放 | 322（1 条） | `e307`，`0x0000462a0000003b`，HVX `q::ForceFormat_Crouton`，322 cycles |

**Inferred**。归因链为 Optrace 中的 HTP Operation ID 和 QNN Op Name，经 DLC framework trace CSV 对应到源 ONNX。`n17` 的 92,983 cycles 包含转置、权重格式转换等多个底层事件，无法单独衡量矩阵乘内核。`e205` 可通过同一 HTP ID 在 QHAS 和 HTP Graph 复核。Unknown 中的 `e201` 为 21,409 cycles 的 `q::ForceFormat_Crouton`，缺少源节点证据，继续保留 Unknown。 [e205 时间线](http://127.0.0.1:8000/?view=timeline&profile=profile-2eeb593f32eabe2213210614&event=profile-2eeb593f32eabe2213210614-e205) · [Framework CSV](../../runs/android-tiny/baseline/aimet-w8a16.graph.csv) · [QHAS](../../runs/android-tiny/baseline-context/optrace/trace_qnn_htp_analysis_summary.json) · [HTP Graph](../../runs/android-tiny/baseline-context/optrace/trace_htp.json)

**历史对照**。原 Baseline → Packed QKV 的六组配对测量各保留 600 次 Basic 样本，整图 p50 为 1,532.0 → 1,648.5 µs（+7.60%），p95 为 1,886.1 → 1,956.1 µs（+3.71%）。Attention 周期和同时从 176,616 降到 125,661。后续每侧 15 次保留样本的短复跑中，p50 下降 2.10%，p95 上升 2.71%。这些记录用于说明局部周期、整图延迟和重复测量的关系。新实验以本轮新采集的 Baseline 为对照。 [历史真机 A/B](android-tiny-htp-ab.md) · [短复跑记录](../../runs/verification/android-runner-comparison.json)

## 模型结构和单变量改动

源 ONNX 为 opset 17，共 43 个节点、148,544 个 initializer 元素。FP32 输入 `hidden` 和输出 `logits` 均为 `[1,12,64]`。计算从 `64 → 128` 输入投影进入 Attention、残差、`128 → 256 → GELU → 128` MLP、残差和 `128 → 64` 输出投影。Attention 有 4 个 Head，每个宽度为 32，Q、K、V 和输出各有一个带 bias 的 `128 → 128` 投影，共 66,048 个参数。参考源模型为 FP32，目标设备 DLC 使用 W8A16。 [PyTorch 模型和导出入口](../../examples/tiny.py) · [现有 Notebook](../../examples/adaptation.ipynb)

只修改 `Attention.forward` 内的评分 MatMul 结构，保留独立的 Q、K、V 投影、全部原权重及 bias、缩放 `1/√32`、最后一维 Softmax、`P·V`、输出投影、残差和 MLP。

- 原版 `Q [B,H,T,D] × Kᵀ [B,H,D,T] → [B,H,T,T]`。
- Candidate 将两个操作数 reshape 为 `[B×H,T,D]` 和 `[B×H,D,T]`，执行同一批矩阵乘法，再将输出恢复为 `[B,H,T,T]`，进入原有缩放与 Softmax。令 `j=b×H+h`，保证每个 `(b,h)` 独立计算，Query、Key 和 Softmax 的序列轴顺序保持一致。
- **Hypothesis**。降低评分 MatMul 的批维秩可能改变 QAIRT 对该组的布局转换。主机制信号是评分 MatMul 组内 HVX 转置或格式转换变化。比较导出的 MatMul 输入秩、同语义 QNN 组内的 HTP 操作类型、数量与周期，以及可用的 QHAS VTCM 读写字段。按各次编译的映射重新关联，跨产物以数据流语义对齐，HTP ID 只在对应产物内使用。若导出或编译把两侧归一为相同布局，记录该改写未触发预期路径。若增加转换、改变编码或 SDK 拒绝编译，记录实际表现和失败的阶段。

## 数值验证和量化

1. 使用 `runs/android-tiny/verification-inputs.npz` 中的 8 组固定输入，与原来的 48 组校准样本隔离。逐组运行 PyTorch FP32 的两侧、各自导出的 ONNX Runtime CPU 输出及两份 ORT 输出的 A/B。要求输出名、形状、dtype 相同且有限，`allclose(atol=1e-5, rtol=1e-4)` 全部通过。先核对缩放前的 Attention scores，再核对最终 `logits`。报告 max/mean absolute error 和最差样本编号。
2. 用同一份 48 样本及相同顺序、AIMET ONNX 2.44.0、相同 W8A16 配方逐模型重新生成 Encodings。保存校准清单摘要，检查新的评分路径张量、量化轴、位宽和 scale/zero point，以及边界 I/O 编码。使用相同的 QAIRT 版本、HTP backend、ONNX 简化设置及 `--enable_framework_trace` 编译。每侧保留各自的 DLC、Context、schematic 和 framework CSV。 [已有校准入口](../../runs/android-tiny/calibrate.py) · [已有编译参数](../../runs/android-tiny/linux/convert-aimet.sh)
3. 在设备上对两侧分别跑完同 8 组输入，保存每个 `logits`。检查每侧 HTP 对各自 FP32 ORT 参考，以及 HTP 两侧互比。三组检查均要求 `allclose(atol=0.03, rtol=0.03)` 逐样本通过，输出为有限的 FP32 `[1,12,64]`。报告 max/mean absolute error。历史 A/B 的最大绝对差 0.000193 仅作为参考。普通 Basic runner 每次只保留一个输出，8 组正确性验证使用单独的设备输出采集。

## 真机 A/B 和验收判定

1. 在同一台 SM6650 上使用同版本 runner、同一份 `runs/android-tiny/inputs/hidden-0.raw`、FP32 I/O、同一 W8A16 配方、`default` 性能模式和相同热状态。记录输入和编译产物 SHA-256、运行顺序和电池温度。先做 3 组 Baseline 对 Baseline 的 A/A，记录块内 p50/p95 波动。接着完成 6 个配对块，按 AB、BA 交替。每侧每块 110 次 Basic，丢弃前 10 次，每侧保留 600 个原始单图样本。每块使用相同采样规则并保存原始 CSV。预先记录测量配置、排除条件及所有失败采集。
2. 以 Basic 的 pooled p50/p95 为主指标，同时报告每个配对块的相对差。用单独的匹配 Optrace 采集比较 Attention、目标评分 MatMul 组、Softmax、Unknown 和可用资源事件。按 SHA-256 保证每份 Trace、QHAS、HTP Graph、schematic 和对应模型来自同一次运行或对应的编译产物。 [Android 采集用法](../android-runner.md)
3. **性能通过**要求数值验证通过、比较条件可匹配、至少 5/6 块的 Candidate p50 更低、汇总 p50 降幅至少 5% 且超过 A/A 三组的最大绝对配对 p50 百分比波动，汇总 p95 上升不超过 2%。5% 与 2% 是本任务预设验收线。若 A/A 的 p95 波动已超过 2%，报告尾延迟不可判定。数值失败记为正确性未通过。p50 上升至少 5% 且超过 A/A 波动，或 p95 上升超过 2% 且超过 A/A 波动，记为性能退化。其余未达到门槛的结果标为收益未证实。只有目标组的布局证据也发生可追溯的变化，才将收益归因于本假设。若采集条件不匹配或缺少对应的设备证据，报告阻塞或不确定性。

## 导入与交付

在 `runs/inbox/` 用唯一实验文件名暂存 Candidate ONNX 和 Encodings，经 CLI 或 MCP `import_model` 注册。用 `.venv/bin/python -m scripts.run_android_qnn --mode basic` 采集时传入对应 `--model-id`，保存各块 `capture.json`。用 `--mode optrace --schematic ... --trace-dlc ... --framework-csv ...` 登记匹配的 Optrace、QHAS 和 HTP Graph。已有真实导出也可经 `import_profile` 使用 `qnn-viewer-csv-v2.50` 或 `qnn-optrace-chrome-v2.50` 导入，再用 `import_evidence` 附加 JSON。用 `compare_experiments` 比较每块的匹配 Basic Profile。跨块分位数从各块保留的真实样本汇总。Android Basic Profile 未登记输出时，Core 的 `numeric` 可为空，在报告中引用单独的 8 样本数值验证工件。 [CLI 和 MCP 参数](../mcp.md)

用实际 MCP 客户端核对 `get_hotspots`、`explain_hotspot` 和 `profile_event`。在 Web 用新 Profile ID 回到同一 HTP 操作的源码映射和原始证据。交付可执行的适配 Notebook、ONNX 图差异、FP32 与量化数值报告、原始采集、机器可读 A/B 指标及 Markdown 结论。结论须包含模型和 Profile ID、证据深链接、数值判定、p50/p95 判定及布局假设是否得到支持。只在对应工件实际生成后填写新结果。

## 2026-11-24 实际验收

执行 `.venv/bin/python scripts/run_notebook.py --attention-layout` 复用原始 Tiny Transformer 权重。评分 MatMul 的两个输入秩均由 4 降为 3。八组留出数据的 unscaled scores 和 logits 在两份 ONNX 之间逐元素一致，各自与 PyTorch 的最大 logits 绝对误差为 7.15×10⁻⁷。设备 W8A16 与各自参考之间的最大绝对误差为 0.01388，逐组通过。AIMET 使用同一组 48 个校准输入。两侧的输入、输出与评分 MatMul Activation 编码为 uint16，对应 scale 和量化轴一致。Baseline ONNX 的 SHA-256 与已实测 DLC 对应的源图一致。 [可执行 Notebook](../../examples/attention_layout.ipynb) · [执行结果](../../runs/attention-score-layout/adaptation.executed.ipynb) · [FP32 数值工件](../../runs/tiny-attention-layout-fp32.json)

运行 `.venv/bin/python -m scripts.run_tiny_attention_ab --sdk runs/qairt/sdk/2.50.40.260831`。先跑 3 组 A/A，再以 AB、BA 交替跑 6 组，每组每版保留 100 次 NetRun Basic 样本。汇总 p50 为 **1817.50 → 1788.00 µs（−1.62%）**，p95 为 **2359.95 → 2309.15 µs（−2.15%）**，p50 在 4/6 配对更低。A/A 最大配对波动为 p50 **17.27%**、p95 **6.29%**，未达到性能通过门槛。这批记录缺少块级电池温度，采集脚本已加入前后温度记录。各块作为命名实验登记。 [六组原始统计与实验 ID](../../runs/attention-score-layout/paired-results.json) · [设备数值核对](../../runs/attention-score-layout/numeric.json) · [第一组 Web A/B](http://127.0.0.1:8000/?view=diagnosis&experiment=experiment-4bcfe3c27c65ac2c28faefbf&profile=profile-fd2007dbc306a75f1fb8f42c)

另采两侧 Optrace，评分 MatMul 归因的操作周期和为 **69,534 → 63,877 cycles**，整个 Attention 的操作周期和为 **132,787 → 125,963 cycles**。两份 Trace 均有 164 条去重事件和 18 个可能跨通道阻塞。操作周期和包括并行执行，只用于局部分析。 [Baseline Optrace](http://127.0.0.1:8000/?view=timeline&profile=profile-7575595108ed18a3eab5f23c) · [Rank-3 Optrace](http://127.0.0.1:8000/?view=timeline&profile=profile-741f3763667870ae079fa571)
