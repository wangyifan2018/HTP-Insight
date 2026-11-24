# SM6650 Operation Timeline 并行分析

## SM6650 资源通道复核

2026-11-24 使用 ADB 核对当前连接的设备为 HONOR MTN-AN80、Android 16、SM6650。Qualcomm 的 Snapdragon 6 Gen 4 产品简报将 SM6650 列为该平台，规格列出 Hexagon Tensor Accelerator、HVX 和 Scalar Accelerator。公开资料未列出 HMX 或 HLX 的物理实例数量。 [Qualcomm SM6650 产品简报](https://docs.qualcomm.com/doc/87-78937-1/87-78937-1_REV_A_Snapdragon_6_Gen_4_Mobile_Platform_Product_Brief.pdf) · [QAIRT HTP 文档](https://docs.qualcomm.com/bundle/publicresource/topics/80-63442-10/htp_backend.html)

使用 QAIRT `v2.50.40.260831140417` 重新采集 Tiny Transformer W8A16 的 Optrace。原始 `thread_name` 把 Core 0、TID 256 标为 `Type: HMX`，同次采集的 QHAS 资源表和操作实例支持该归属。该通道记录 94 个事件，其中 25 个带 `uses_hmx`，其余为 DMA 或同步。例子是 `q::ConvLayer_s1.opt`、操作 `0x0000460700000015`、原始事件 `e117`。Core 0 的 HVX TID 512 和 513 分别有 39 和 31 个事件，本次采集未报告 HLX。以上数据说明运行时报告了 HMX 执行，芯片的物理资源数量仍未知。 [选中 HMX 操作](http://127.0.0.1:8000/?view=timeline&profile=profile-2e9d1761b4801deb20131964&event=profile-2e9d1761b4801deb20131964-e117) · [采集收据](../../runs/verification/resource-lanes-sm6650-capture.json) · [结构化证据](../../runs/verification/resource-lanes-sm6650.json)

Web 将其显示为 **HMX lane · Core 0 · TID 256**，事件面板分别显示 QAIRT 执行通道、Optrace/QHAS 依据、原始 lane 名称和单操作资源标志。按 Core 与资源类型筛选的选项来自捕获本身。多个 HMX 或 HLX、相同 TID 在不同 Core、缺少 Core、来源冲突及新类型已通过 Fixture 回归。不同核心之间的周期可比性需要设备证据，这类边目前不参与阻塞时长判定。

本轮通过 22 项单测、前端生产构建、17 项浏览器检查及独立 MCP stdio 查询。浏览器验收复查同一 HMX lane 上的 `uses_hmx` 与 `dma_wait`，并从 Web 发起 Android Basic。 [浏览器收据](../../runs/verification/browser.json) · [通道截图](../../runs/verification/sm6650-reported-hmx-lane.png) · [MCP 响应](../../runs/verification/resource-lanes-sm6650-mcp.json)

## 时间线与阻塞证据

使用已保存的 Tiny Transformer W8A16 Baseline `profile-2eeb593f32eabe2213210614`，并以连接的 SM6650 真机重新采集 `profile-ee7ab46ed23968266d3c2d0b`。两次均用 QAIRT 2.50.40.260831，解析到 164 条唯一 HTP 操作。每条都能通过 Optrace 实例与 QHAS 核对所在通道。实测通道为 Core 0 HMX TID 256、HVX TID 512 和 HVX TID 513。本次两份记录均没有 HLX 通道。资源标志和事件所在通道分别保留。 [复跑采集](../../runs/verification/htp-parallelism-capture.json)

| 证据 | 基线数量 | 定义 |
| --- | ---: | --- |
| 唯一生产者、消费者对 | 158 | 可同时带有 Optrace 数据流、sequencer 排序、Optrace 输入 ID 或编译图张量证据 |
| 数据流箭头 | 137 | 两端可定位到唯一实测操作的 `input_output` 事件对 |
| Sequencer 箭头 | 101 | 两端可定位到唯一实测操作的 `sequencer` 事件对 |
| 实测等待或同步事件 | 18 | 15 个 `dma_wait`，3 个 `sync` |
| 可能的跨通道阻塞 | 18 | 有记录的跨通道前置依赖，且前置操作的实测结束位于消费者通道的空档内 |

定位箭头按原始通道、生产者结束和消费者开始的精确时间匹配。丢弃 66 对缺少两个可测端点的 flow，例如常量；不会用最近邻猜对应操作。编译图以唯一张量生产者和消费者 ID 提供结构依赖。结构依赖独立展示，只有真实 trace flow 能进入候选阻塞计算。QHAS Dominant Path 是 viewer 的优先级指标，保留字段供核对。 [QAIRT HTP Optrace 和 QHAS](https://docs.qualcomm.com/bundle/publicresource/topics/80-63442-10/htp_backend.html)

## 最大重叠候选

`e201` 的 `q::ForceFormat_Crouton` 在 **HVX TID 513** 执行，向 **HMX TID 256** 上的 `e117` `q::ConvLayer_s1.opt` 提供输入。Optrace 数据流 136、sequencer 流 287、`Inputs Ops` 和 HTP Graph 张量 `0x0000464700000002` 均支持这条边。生产者执行与消费者通道可见空档重叠 **21,409 cycles**，其完成后 **45 cycles** 开始消费者。该关系可用于排查优先级，实际因果等待时长与硬件就绪时间仍不可得。`e201` 的源 ONNX 归因保留 Unknown。 [已选中阻塞的时间线](http://127.0.0.1:8000/?view=timeline&profile=profile-2eeb593f32eabe2213210614&event=profile-2eeb593f32eabe2213210614-e117&blocker=profile-2eeb593f32eabe2213210614-e201) · [API/MCP 结果](../../runs/verification/htp-parallelism.json)

在 Operation Timeline 点击 **Parallelism analysis** 的候选行，可以同时定位生产者、消费者、数据流与通道空档。Event Inspector 显示前置操作、消费者、关联张量与原始 Flow 行；可从 **Recorded waits and synchronization** 单独定位 trace 标记的等待。对没有资源 TID 或没有 flow 的文件，只展示已记录的通道、依赖和等待字段。 [界面验收](../../runs/verification/browser.json)
