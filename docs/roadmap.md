# 后续边界和优先级

## 当前闭环

首页五步引导、系统能力、实测样例、分层定位、诊断和 Notebook 交接使用同一个本地工作区。Mac ORT 和 Android QAIRT 已有实测，Web、CLI 与 MCP 返回同一组证据 ID。 [功能审计](audit/current_status.md) · [验收](experiments/mac_mvp_validation.md)

## 尚未完成的产品要求

| 优先级 | 缺口 | 下一项验收 |
| --- | --- | --- |
| P1 | Claude Code 本机项目 MCP 仍待批准 | 在 Claude Code 开启项目服务器后，从同一实际会话调用 `analyze_model_performance` 与 `generate_experiment_plan`，核对 Profile ID 与原始证据链接。当前已用独立 MCP SDK 客户端验证协议与返回。 |
| P2 | 导入仍要求把文件放入本地 Inbox，命名实验与 ONNX/Context 配对没有统一项目表单 | 在不改动旧产物的前提下，提供文件选择、实验显示名、源 ONNX 与 Context 绑定，并记录相应的兼容性和版本。 |
| P2 | HTP 采集从本地 Android CLI 执行 | 只有经过设备授权、ABI、SDK 和输入检查才开放 Web 一键启动。当前 Web 支持结果查看与导入。 |
| P2 | 语义层依赖 ONNX 命名 | 用另一个真实多层模型验证 Layer → Attention/MLP 聚合，补足不同导出命名和无名称图的可解释降级。 |
| P3 | 新 HTP Attention 布局假设缺少 Candidate 测量 | 执行独立 Notebook 任务，用匹配 QAIRT 构建和真实 A/B 判定，并保留失败或不确定结果。 [具体实验](experiments/claude-code-attention-layout.md) |
| P4 | 缺少专用 Linux 与 SSH 采集适配器 | 在支持的 Qualcomm 环境验证输入清单、工具版本检测、原始日志转换和可移植缓存。 |

诊断现阶段能展示归因链、资源事件和可证伪假设。通用 HTP 微架构根因推断需要更多实测覆盖、明确的硬件计数和跨实验验证。[HTP 真机证据](experiments/android-tiny-htp-ab.md)
