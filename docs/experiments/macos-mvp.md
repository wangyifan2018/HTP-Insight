# macOS MVP 实测验收

在 Apple M2 / macOS 26.7.3 上执行。ORT 1.20.1 使用 `CPUExecutionProvider`、单线程顺序执行、`ORT_DISABLE_ALL`。本页引用固定的已保存实验 `experiment-e3bda0904227e3e85655b508`。每次重新运行 `make demo` 会生成新的实测记录。

## Tiny Transformer

输入是确定性的 FP32 `[1, 12, 64]` 张量，Baseline 和 Candidate 使用同一份 NPZ、各 warm up 50 次、采样 500 次无插桩 `session.run`，另采集 8 次节点 Trace。Attention 的 Baseline 归因耗时为 **288 µs / 567 µs（50.8%）**，MLP 为 202 µs。Attention 的原始证据包括事件 `profile-87b619e863eee49e22841bb1-e9`。Baseline 实测 280 个操作事件均匹配到 ONNX，Candidate 实测 328 个均匹配。

| 指标 | Baseline | Packed QKV | 变化 |
| --- | ---: | ---: | ---: |
| 无插桩 p50 | 56.250 µs | 57.625 µs | +2.44% |
| 无插桩 p95 | 62.804 µs | 67.589 µs | +7.62% |
| Attention 操作耗时累加 | 288 µs | 300 µs | +12 µs |
| ONNX 节点数 | 43 | 56 | +13 |
| ONNX 连接差异 | 15 条移除 | 36 条新增 | — |
| Attention MatMul 数 | 6 | 4 | −2 |

相同权重按 Q、K、V 顺序拼接，运行一次投影后分片。PyTorch 原版与适配版通过比较，两侧 PyTorch 与各自 ORT 输出通过比较。两个 ORT 输出的最大与平均绝对误差均为 **0**，阈值为 `atol=1e-5`、`rtol=1e-4`。

**本轮 Candidate 变慢。** Graph diff 确认 MatMul 减少，导出的分片增加了 Slice 与 shape 相关节点。它们可能抵消少两次投影的收益，当前实验仅验证了端到端结果。次序、系统负载和关闭优化的 ORT 设置都是结果适用范围的一部分。

## Qualcomm MobileNet-v2

下表使用 Qualcomm 公开 v0.64.0 ONNX 资产。三个模型使用匹配各自接口的固定随机输入 `[1, 3, 224, 224]`，各 warm up 10 次、采样 40 次无插桩延迟，并写入 4 次节点 Trace。数值检查覆盖重复推理和插桩会话的一致性。这三组的不同输入精度对应不同接口。

| 资产 | 输入类型 | 节点 | QDQ 记录 | p50 | p95 | 已归因事件 / 操作事件 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Float | FP32 | 101 | 0 | 13.425 ms | 13.955 ms | 404 / 404 |
| W8A8 | UINT8 | 470 | 369 | 17.938 ms | 21.186 ms | 1880 / 2192 |
| W8A16 | UINT16 | 470 | 369 | 17.951 ms | 20.894 ms | 1880 / 2192 |

两份量化 Trace 各有 312 个事件没有唯一源节点匹配，保留在 Unknown 和总时长分母中。

## AIMET Encodings

在独立 Python 3.11 环境中实测 AIMET ONNX 2.44.0，使用 32 个确定性随机样本在 CPU 上校准 Tiny Transformer，导出 v2.0.0 Encodings。Core 成功导入 48 条编码并关联到 39 个 ONNX 节点。计数含 32 条 UINT8、8 条 INT8 和 8 条 INT32。在 Web 选取 `Tiny Transformer · AIMET Encodings` 可查看这些注释。这个标注模型的 ORT 实测使用导出伴随的 FP32 Graph，量化模拟由 AIMET 自身运行。

[Encodings 文件](../../runs/inbox/tiny-aimet.encodings) · [导入结果](../../runs/verification/aimet.json) · [校准日志](../../runs/verification/aimet-calibration.log)

## 实际执行与生成物

| 执行命令 | 结果 | 生成物 |
| --- | --- | --- |
| `make doctor`、`make install` | 本机盘点、独立 Python 环境和前端依赖安装成功 | `runs/verification/doctor.txt`、`install.log` |
| `make demo` | Tiny A/B 和三种 Qualcomm 模型 CPU 推理、归因、原始 Trace | [A/B Markdown](../../runs/report.md)、[A/B JSON](../../runs/demo.json)、[MobileNet JSON](../../runs/mobile.json)、`runs/store/` |
| `make notebook` | Notebook kernel 真实执行，完成 QKV 合并、导出和数值验证 | [执行后的 Notebook](../../runs/adaptation.executed.ipynb) |
| `runs/aimet-env/bin/python -m scripts.aimet_encodings` | AIMET CPU 校准和 Encodings 导出 | [真实编码](../../runs/inbox/tiny-aimet.encodings) |
| `make test` | 12 个自动测试通过，Starlette TestClient 输出 1 条依赖弃用提示 | [测试日志](../../runs/verification/test.log) |
| `make mcp` 由 `.venv/bin/python -m scripts.mcp_smoke` 启动 | SDK stdio 协议 2025-06-18，8 个工具，热点、解释、建议和 A/B 与 Core 一致 | [MCP JSON](../../runs/verification/mcp.json) |
| `make web`、`make browser` | Chrome 验证 Graph 与 Timeline 双向选中、诊断、Markdown/JSON 下载与 MobileNet QDQ、Tiny AIMET Encodings | [浏览器结果](../../runs/verification/browser.json) |

浏览器记录对应的实验可从 [Diagnosis & Comparison](http://127.0.0.1:8000/?view=diagnosis&experiment=experiment-e3bda0904227e3e85655b508&profile=profile-87b619e863eee49e22841bb1) 打开。Claude Code 已识别项目配置并显示待批准，实际协议与调用由独立的 MCP SDK 客户端验证。

## 浏览器截图

[Graph Explorer](../../runs/verification/graph.png) · [Profile Timeline](../../runs/verification/timeline.png) · [Diagnosis & Comparison](../../runs/verification/diagnosis.png) · [MobileNet W8A8](../../runs/verification/mobile-qdq.png)
