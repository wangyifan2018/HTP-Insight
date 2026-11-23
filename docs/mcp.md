# Claude Code MCP 接入

从项目根目录先运行 `make install` 和 `make demo`，另开终端运行 `make web`。在项目根目录打开 Claude Code，批准项目级 `.mcp.json` 中的 `htp-insight`。在 Claude Code 运行 `/mcp` 可查看连接状态。从终端运行 `claude mcp list` 可检查配置是否被识别。

```json
{
  "mcpServers": {
    "htp-insight": {
      "type": "stdio",
      "command": "make",
      "args": ["--no-print-directory", "mcp"]
    }
  }
}
```

`make mcp` 使用 stdio 传输。可通过 `.venv/bin/python -m scripts.mcp_smoke` 对相同命令发起真实的 MCP 客户端调用。客户端会核对来自 MCP 的排序、热点解释、假设和 A/B 比较是否与本地 Core 返回值一致。

| Tool | 参数 | 返回 |
| --- | --- | --- |
| `import_model` | `filename`，可选 `encodings`、`name`、`target_device`、`compatibility` | Artifact 和 Graph 链接 |
| `inspect_graph` | `model_id` | Graph、张量、模块、量化与链接 |
| `import_profile` | `model_id`、`filename`，可选 `format`、`fixture`、`mapping_file`、版本和运行条件 | Profile ID、来源与 Timeline |
| `run_ort_profile` | `model_id`、`inputs`，可选 `warmup`、`repeats`、`trace_runs` | CPU 实测摘要、原始 Trace 和 Timeline |
| `get_hotspots` | `profile_id`、可选 `level` 和 `limit` | 排序、分母范围、证据 ID |
| `explain_hotspot` | `profile_id`、`hotspot_id`、可选 `level` | Shape、DType、QDQ、可证伪假设、事件引用 |
| `suggest_experiments` | `profile_id`、可选 `limit` | 优化假设和验证指标 |
| `compare_experiments` | `baseline`、`candidate`、可选 `hypothesis` | A/B、数值验证、Graph 差异和 Deep Link |

导入参数以 `runs/inbox/` 为根路径。接受 JSON 中已定义的字段及有限次数的本地推理。Optrace 导入支持 `optrace-chrome-v1`，QAIRT 2.50 Linting 导入支持 `qnn-linting-chrome-v2.50`。Linting 热点返回 `total_cycles` 及 DSP cycles 单位。真机 `qnn-optrace-chrome-v2.50` 可带 `framework_csv` 导入，以 QAIRT 的 QNN 算子名连接 DLC 来源映射和 ONNX 节点。A/B 可传 `atol` 与 `rtol` 检查已保存输出。可选映射文件的结构示例如下。

```json
[
  {"operation_ids": ["compiler_op_5"], "node_ids": ["n4", "n5"]},
  {"operation_ids": ["compiler_op_6", "compiler_op_7"], "node_ids": ["n8"]}
]
```

在 Claude Code 中可让它用 `get_hotspots` 定位 Baseline 的 Attention，调用 `explain_hotspot` 核对证据，然后用 `compare_experiments` 对比实验两侧，并引用返回的 Web 链接。Profile ID 可从 `runs/demo.json` 获取。
