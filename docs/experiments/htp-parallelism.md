# SM6650 Operation Timeline 并行分析

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
