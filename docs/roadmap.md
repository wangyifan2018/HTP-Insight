# 后续边界和优先级

## 当前闭环

首页五步引导、系统能力、实测样例、分层定位、诊断和 Notebook 交接使用同一个本地工作区。Web 文件导入、配对 ONNX 与 QAIRT 产物、命名 A/B，以及浏览器发起 Android 实测均已验收。 [工程复审](audit/product-gap-review.md) · [Mac MVP 验收](experiments/mac_mvp_validation.md)

## 尚未完成的产品要求

| 优先级 | 缺口 | 下一项验收 |
| --- | --- | --- |
| P1 | Claude Code 本机项目 MCP 仍待批准 | 在 Claude Code 开启项目服务器后，从同一实际会话调用 `analyze_model_performance` 与 `generate_experiment_plan`，核对 Profile ID 与原始证据链接。当前已用独立 MCP SDK 客户端验证协议与返回。 |
| P2 | 更多模型结构和硬件覆盖 | 现有模型已验证命名作用域，未命名图增加保守的数据流识别。其他导出结构、真实 HLX 和跨核心 trace 仍需对应证据。 |
| P3 | Tiny Attention rank-3 性能收益待证实 | 真机 A/B 已执行并通过数值验证，延迟变化低于 A/A 波动。稳定控制运行条件后可复验。 [真机结果](experiments/claude-code-attention-layout.md) |
| P3 | Qwen3-TTS Code Predictor 的 SM6650 整图执行 | 整图仍受 FP16 RMSNorm 限制。第一层 MLP 已取得 Basic 和 Optrace，三种量化配方未过留出数值门槛。下一次先解决这两项验收。 [模型实测](experiments/qwen3-tts-code-predictor.md) |
| P4 | 专用 Linux 与 SSH 采集 | 当前缺少可用的授权远程目标和对应硬件。Linux ARM64 转换已使用，QAIRT 的可用导出能在现有 Core 导入。 |

诊断现阶段能展示归因链、资源事件和可证伪假设。通用 HTP 微架构根因推断需要更多实测覆盖、明确的硬件计数和跨实验验证。[HTP 真机证据](experiments/android-tiny-htp-ab.md)
