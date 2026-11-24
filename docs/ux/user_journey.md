# 从模型到 Notebook 实验

打开 [HTP Insight](http://127.0.0.1:8000/)，选择 **Explore Mac ORT recording** 或 **Explore Android HTP recording** 查看已有实测，或从 **Import** 分析自己的 ONNX。当前流程中的模型、后端、来源和实验会随页面跳转保留。

| 步骤 | 操作 | 页面提供的证据 |
| --- | --- | --- |
| Import | 把本地 ONNX、可选 AIMET Encodings 放到 `runs/inbox/`。点击 Import，填写相对路径。 | 图、输入输出 Shape 与 dtype、量化注释、参数元素数、模块和对应节点。HTP Context 可单独登记目标兼容性。 |
| Profile | 在图页面点 **Profile this model**。选择 **Run ORT CPU Profile**，填写匹配 ONNX 输入名的 NPZ。已有 QAIRT 结果可用 **Import QNN Profile**。 | 后端、设备、Profiler、来源、预热、保留样本、p50/p95。Basic 只有图延迟时，页面提示另收集操作 Trace。 |
| Locate | 点 **Locate hotspots**。默认按模块，底层可切换为节点或操作。选择一行，查看输入输出和量化。 | 时间或周期、相对于 Trace 的比例、编译映射、Unknown。Graph Explorer 按可识别的层和模块展开，支持搜索与时间线互跳。 |
| Diagnose | 点 **Diagnose hotspot**。先看 **Measured** 和原始事件，再读 **Inferred mapping** 与 **Hypothesis**。 | 操作、资源、映射方法、源节点和附件。A/B 在同页保留数值正确性、分位数、条件差异和报告下载。 |
| Optimize | 点 **Generate Claude Code Experiment Plan**。复制 Markdown，或下载 Markdown/JSON。 | 任务携带来源、张量、可核查证据、变更假设、数值验证条件和下一轮匹配 A/B 的门槛。 |

在 **System Status** 可确认当前工作区有没有实测档案，以及 ORT CPU 提供者是否可用。Android 真机采集用本地 QAIRT runner。已有支持格式的 QAIRT 导出和对应源 ONNX 时，可以直接导入现有 Profile。[Android 采集说明](../android-runner.md)

实验的时间口径随来源显示。ORT 独立采无插桩延迟和操作 Trace。Android Basic 图执行以微秒显示，Optrace 和 Linting 使用 DSP cycles，重叠操作计入对应的 Trace 周期和。对映射不足的热点，Notebook 任务会先要求补齐编译证据。[架构说明](../architecture.md)

Claude Code 可用 `analyze_model_performance` 一次读取模型、分位数、模块热点、证据缺口和下一项建议，再按选定热点调用 `generate_experiment_plan`。[MCP 操作参数](../mcp.md)
