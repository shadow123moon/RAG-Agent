# PaiSmart 上传与解析时序图（简化版）

这版按 `PaiSmart` 当前真实实现拆成两张图：

- 第一张只看“上传与合并”
- 第二张只看“异步解析与入库”

这样比一张特别宽的总图更容易看清。

---

## 1. 上传与合并

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant UC as UploadController
    participant US as UploadService
    participant DB as MySQL
    participant R as Redis
    participant M as MinIO
    participant K as Kafka

    loop 每个分片
        Client->>UC: POST /upload/chunk
        Note over UC: 校验文件类型、orgTag、大小限制
        UC->>US: uploadChunk(fileMd5, chunkIndex, ...)

        US->>DB: 查询/创建 file_upload
        US->>R: 检查 bitmap 是否已上传
        US->>DB: 检查 chunk_info 是否存在

        alt 需要真正上传
            US->>M: 保存分片 chunks/fileMd5/chunkIndex
            US->>R: setBit(upload:userId:fileMd5, chunkIndex)
            US->>DB: 保存 chunk_info
        else 已上传且状态一致
            US-->>UC: 幂等成功
        end

        UC->>US: 获取已上传分片与进度
        US->>R: 读取 bitmap
        US->>DB: 根据 totalSize 计算总分片数
        UC-->>Client: 返回 progress
    end

    Client->>UC: POST /upload/merge
    UC->>DB: 校验文件归属与状态
    UC->>US: 获取上传完成情况
    UC->>DB: 状态从 UPLOADING 改为 MERGING
    UC->>US: mergeChunks(fileMd5, fileName, userId)

    US->>DB: 查询所有 chunk_info
    US->>M: composeObject 合并为 merged/fileMd5
    US->>M: 删除原始分片
    US->>R: 删除上传 bitmap
    US->>DB: 更新 file_upload 为 COMPLETED

    Note over DB: 这里的 COMPLETED 更接近“文件合并完成”

    UC->>US: 读取 merged 文件流
    US->>M: getObject(merged/fileMd5)
    Note over UC: 估算 estimatedEmbeddingTokens / estimatedChunkCount
    UC->>DB: 回写预估值
    UC->>K: 发送 FileProcessingTask
    UC-->>Client: 返回合并成功
```

---

## 2. 异步解析与入库

```mermaid
sequenceDiagram
    autonumber
    participant K as Kafka
    participant FC as FileProcessingConsumer
    participant M as MinIO
    participant P as ParseService
    participant DB as MySQL
    participant V as VectorizationService
    participant E as Embedding API
    participant ES as Elasticsearch

    K-->>FC: 消费 FileProcessingTask
    FC->>M: 下载 merged/fileMd5
    FC->>P: parseAndSave(fileMd5, stream, userId, orgTag, isPublic)

    Note over P: PDF 走 PDFBox 按页提取\n清理页眉页脚\n按段落/句子/HanLP 切片
    Note over P: 非 PDF 走 Tika 流式解析\n父块/子块切分

    P->>DB: 保存 document_vectors(textContent, pageNumber, anchorText, ...)

    FC->>V: vectorizeWithUsage(fileMd5, ...)
    V->>DB: 按 fileMd5 读取切片文本
    V->>E: 生成每个切片的向量
    E-->>V: 返回 vectors + token usage + modelVersion
    V->>ES: bulkIndex 到 knowledge_base
    FC->>DB: 回写 actualEmbeddingTokens / actualChunkCount
```

---

## 3. 一句话理解

第一张图解决的是：

- 文件怎么可靠上传
- 分片怎么落存储
- 什么时候合并成完整文件
- 什么时候发异步任务

第二张图解决的是：

- Kafka 任务怎么被消费
- 文档怎么解析和切片
- 切片文本先落哪
- 向量最后写到哪

