# Java + Python RAG 一期集成说明

## 1. 一期主链路选择
- `ingest` 主链路：`Kafka`（只保留 Kafka，不走 Java->Python ingest HTTP）
- `query` 主链路：`HTTP`（Java 鉴权与权限裁剪，Python 执行检索与生成）

## 2. 角色分工
- Java（业务网关）
  - 用户鉴权与权限标签计算
  - 文件分片上传、合并、生成 ingest 任务
  - 维护任务表 `rag_task`
  - 接收 Python 回调并回写任务状态
- Python（RAG 引擎）
  - 消费 `rag-ingest` 任务
  - 文档解析、切块、向量化、写索引
  - 提供 query 接口，并通过轻量 Agent 编排层完成意图识别、查询改写、证据判断与兜底回答
  - 回调 Java 更新任务状态与统计

## 3. Java 对外接口（用户侧）

### 3.1 提交上传入库任务
- `POST /api/v1/upload/merge`
- 行为：合并分片后创建 `rag_task`，发送 Kafka 任务
- 返回重点字段：
  - `data.taskId`
  - `data.docId`
  - `data.version`

### 3.2 提交重建任务
- `POST /api/v1/documents/{fileMd5}/reindex`
- 行为：直接创建新的 `INGEST` 版本任务并发送 Kafka
- 返回重点字段：
  - `data.taskId`
  - `data.fileMd5`
  - `data.version`
  - `data.status`（初始 `QUEUED`）

### 3.3 查询问答
- `POST /api/v1/rag/query`
- 行为：Java 从登录态提取用户信息与可访问组织标签，转发 Python query
- 前端聊天页仍连接原 WebSocket：`/chat/{token}`
- WebSocket 内部已切到同一条 Python RAG query 链路，返回格式继续兼容前端：
  - `{"chunk":"..."}`
  - `{"type":"completion","status":"finished"}`
- WebSocket 聊天会把 Python 返回的 `sources` 转成 `来源#1: 文件名 | 第x页`，并持久化 `referenceMappings`，刷新页面后引用预览仍可用。

### 3.4 查询任务状态
- `GET /api/v1/rag/tasks/{docId}/latest`
- `GET /api/v1/rag/tasks/by-task-id/{taskId}`

## 4. Python Agent 编排层

### 4.1 编排目标
- 不是简单的“一次检索 + 一次生成”
- query 会先经过 `AgentOrchestrator`：
  - `IntentClassifier`：识别问候、知识库问题、通用技术问题、未知问题
  - `QueryRewriter`：对“再详细点 / 继续 / 这个怎么实现”这类追问结合最近历史做查询改写
  - `Retriever`：调用 embedding + Elasticsearch 进行首轮检索
  - `EvidenceJudge`：判断检索证据是否足够
  - `QueryRepair`：证据不足时清洗查询词并二次检索
  - `AnswerGenerator`：有证据时基于知识库生成答案
  - `FallbackHandler`：无证据但属于通用技术问题时，明确标注“未检索到知识库来源”后通用回答

### 4.2 Agent 输出观测字段
- Python query response 的 `usage` 中会包含：
  - `intent`
  - `retrievalQuery`
  - `agentSteps`
  - `fallbackMode`
  - `evidenceEnough`
  - `repairedQuery`（如果发生二次检索）

### 4.3 证据门控与兜底策略
- `EvidenceJudge` 不再只看 ES 是否返回了若干 chunk，而是要求命中问题中的核心技术词，例如 `Redis`、`混合持久化`、`Kafka`、`Kubernetes`、`informer`
- 如果首轮检索弱相关，会进入 `QueryRepair` 清洗追问词、标点和面试口语后再检索一次
- 如果二次检索仍然没有足够证据，Python 会丢弃弱相关 sources，避免把不相关知识库片段挂到答案后面
- 对明显技术问题，兜底回答必须以“未检索到知识库来源，以下为通用技术回答。”开头，且不会伪造参考来源
- 对问候类输入直接走轻量对话，不再返回“暂无相关信息”

## 5. Java -> Python（内部）接口定义

### 5.1 Kafka Topic
- Topic：`spring.kafka.topic.rag-ingest`（默认 `rag-ingest-topic`）

### 5.2 Kafka 消息体（`RagIngestTask`）
- `taskId`: string
- `docId`: string
- `version`: int
- `fileName`: string
- `bucket`: string
- `objectKey`: string
- `filePath`: string（示例：`minio://uploads/merged/<docId>`）
- `userId`: string
- `orgTag`: string
- `isPublic`: boolean

## 6. Python -> Java（回调）接口定义

### 6.1 ingest 回调
- `POST /api/v1/internal/rag/callback/ingest`
- Header：`X-Rag-Callback-Token: <RAG_CALLBACK_TOKEN>`
- Body：
  - `taskId`: string（推荐）
  - `docId`: string（兜底）
  - `status`: `QUEUED|INGESTING|AVAILABLE|FAILED`（兼容 `PROCESSING/RUNNING/SUCCESS/COMPLETED/ERROR`）
  - `chunkCount`: int
  - `embeddingTokens`: long
  - `modelVersion`: string
  - `errorCode`: string
  - `errorMessage`: string

## 7. 幂等、重试、反脏写策略

### 7.1 任务唯一键
- `rag_task.task_id` 唯一
- `(doc_id, version, op_type)` 唯一

### 7.2 创建任务冲突重试
- Java 创建 ingest 任务时，如果版本唯一键冲突，会自动重试获取新版本再写入（最多 3 次）

### 7.3 回调乱序保护
- 回调写 `file_upload.actualChunkCount/actualEmbeddingTokens` 前，先校验该任务是否为当前文档最新 `INGEST` 版本
- 非最新版本回调仅更新自身任务记录，不覆盖 `file_upload` 聚合字段

### 7.4 失败重试
- Kafka 层重试由消费端控制（Python consumer）
- 回调可以重复调用，`taskId` 幂等更新

## 8. 一期流式查询说明
- 一期 Python `query` 返回为非流式（普通 JSON）
- 为兼容现有前端聊天页，Java WebSocket 会把完整答案切成多个小 `chunk` 推给前端，形成打字机式效果，再发送 completion 通知
- 注意：这只是 Java 层的模拟流式，不是真正的模型 token streaming
- 后续扩展方式：
  - Java 增加 `/api/v1/rag/query/stream`（SSE 或 WebSocket）
  - Python query 提供增量 token 流式输出
  - Java 将用户态鉴权与权限标签继续保留在网关层

## 9. Python 服务启动（本机 conda `lc`）
- 安装依赖（首次）：
  - `conda run -n lc pip install -r rag-python/requirements.txt`
- 启动服务：
  - `conda run -n lc python -m app.main`（工作目录 `rag-python`）
- 健康检查：
  - `GET http://localhost:18080/health/live`
  - `GET http://localhost:18080/health/ready`

## 10. Python 服务启动（Docker 可选）
- 该服务在 `docs/docker-compose.local.yaml` 中以 profile 形式提供：`rag-python`
- 启动命令：
  - `docker compose -f docs/docker-compose.local.yaml --profile rag-python up -d`
- 说明：
  - 宿主机 Kafka 端口建议使用 `29092`
  - 该 profile 不会影响你用 conda 方式本机运行 Python
