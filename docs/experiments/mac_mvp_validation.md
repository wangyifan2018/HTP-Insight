# Mac MVP 最小闭环复验

2026-11-24 在 Apple M2 上使用原始 Tiny Transformer 模型与 `examples/adaptation.ipynb` 重跑 FP32。实验单独写入 `runs/verification/product-acceptance/cpu/`。ORT 使用 `CPUExecutionProvider`，两侧各预热 50 次、保留 500 次无插桩延迟、独立采 8 次操作 Trace。

| 实测过程 | Baseline p50 | Candidate p50 | Baseline p95 | Candidate p95 | 输出验证 |
| --- | ---: | ---: | ---: | ---: | --- |
| 命令行导出与 Packed QKV A/B | 55.812 µs | 56.355 µs | 63.168 µs | 69.477 µs | 通过，最大绝对误差 0 |
| 原 Notebook 内实际执行 Packed QKV A/B | 55.333 µs | 57.167 µs | 68.339 µs | 65.408 µs | 通过，最大绝对误差 0 |

命令行采样中 Attention 的模块操作和为 279 µs，MLP 为 202 µs。Packed QKV 的两次复测 p50 都上升，p95 方向不同。本次记录未证实加速。独立 Notebook、比较 JSON 和原始 Trace 均已保存。[命令行报告](../../runs/verification/product-acceptance/demo.log) · [执行后的 Notebook](../../runs/verification/product-acceptance/cpu/adaptation.executed.ipynb)

## 软件验收

- `make test` 通过 18 项 Core、图、量化、版本化导入、报告、API 与 MCP 测试。Starlette TestClient 有一条依赖弃用提示。
- `npm --prefix web run build` 通过 TypeScript 检查和生产构建。`make browser` 通过 13 项检查，验证五步首页、能力状态、真实引导、Graph 与 Timeline 跳转、诊断、复制和两种任务导出。Android 历史 Optrace 可生成指向 `n17` 与原始 `e205` 的任务。[浏览器记录](../../runs/verification/browser.json)
- 在隔离工作区用浏览器表单导入 ONNX、运行两次实际 ORT、创建同模型 A/A，保证导入与运行按钮贯通真实 API。[隔离验收记录](../../runs/verification/product-acceptance/cpu/verification/browser.json)
- 独立 MCP 客户端以 stdio 调用 `analyze_model_performance`、`generate_experiment_plan` 和 `profile_event`，核对本轮 Mac Profile `profile-c626a17a67e2c73db1879456` 与已保存 Android Profile `profile-2eeb593f32eabe2213210614`。`claude mcp list` 识别项目服务器并显示 Pending approval。[MCP 实际响应](../../runs/verification/product-acceptance/mcp.json)

## 复现隔离运行

```bash
export HTP_INSIGHT_DATA="$PWD/runs/verification/product-acceptance/cpu"
export HTP_INSIGHT_WEB=http://127.0.0.1:8012
.venv/bin/python -m examples.demo --tiny-only
make web PORT=8012
```

在同样环境变量的另一个终端运行 `HTP_INSIGHT_BROWSER_ACCEPTANCE=1 make browser`，浏览器会向该隔离库实际写入模型与 Profile。在默认数据目录运行常规 `make browser` 会查看原有档案。 [首页截图](../../runs/verification/workspace-workflow.png) · [任务截图](../../runs/verification/notebook-plan.png)
