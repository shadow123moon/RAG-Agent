# PaiSmart RAG Agent

这是一个面向知识库问答场景的 Java + Python RAG 学习项目，主要用于练习后端工程、文档上传解析、异步任务处理、向量检索和大模型问答链路。

项目以 Spring Boot 作为业务后端，负责用户体系、权限控制、文件上传、任务管理和接口编排；以 Python FastAPI 作为 RAG 服务，负责文档解析、文本切分、Embedding、检索增强和答案生成。基础设施使用 MySQL、Redis、Kafka、MinIO 和 Elasticsearch。

## 主要功能

- 用户登录与 JWT 鉴权
- 文档上传、分片处理和文件管理
- MinIO 对象存储
- Kafka 异步文档解析任务
- Python RAG 服务处理解析、切片、向量化和检索
- Elasticsearch 存储文本块与向量数据
- 基于知识库的问答和来源引用
- WebSocket 聊天交互
- 基于组织标签的基础权限隔离

## 技术栈

后端：

- Java 17
- Spring Boot 3
- Spring Security + JWT
- Spring Data JPA
- MySQL 8
- Redis
- Kafka
- MinIO
- Elasticsearch
- WebSocket

RAG 服务：

- Python
- FastAPI
- aiokafka
- Elasticsearch Python Client
- MinIO Python SDK
- Embedding API
- LLM API

前端：

- Vue 3
- TypeScript
- Vite
- Naive UI
- Pinia

## 项目结构

```text
.
├── src/                 # Java Spring Boot 后端
├── rag-python/          # Python RAG 服务
├── frontend/            # Vue 前端
├── docs/                # 本地开发配置和项目说明
├── pom.xml              # Maven 配置
└── README.md
```

## 本地启动

1. 准备环境变量：

```bash
copy docs\env.docker.example .env
```

2. 启动基础服务：

```bash
docker compose -f docs\docker-compose.local.yaml up -d
```

3. 启动 Java 后端：

```bash
mvn spring-boot:run
```

4. 启动 Python RAG 服务：

```bash
cd rag-python
conda run -n lc python -m app.main
```

5. 启动前端：

```bash
cd frontend
pnpm install
pnpm run dev
```

## 默认说明

- 后端默认端口：`8081`
- Python RAG 默认端口：`18080`
- 前端开发环境默认端口以 Vite 输出为准
- 本地配置文件 `.env` 不应提交到仓库
- API Key、数据库密码等敏感信息请只放在本地环境变量或 `.env` 中

## 说明

本仓库主要用于个人学习、项目梳理和技术实践，不包含任何线上生产环境配置。项目中的部分配置、模型服务和本地运行方式可根据自己的环境进行调整。
