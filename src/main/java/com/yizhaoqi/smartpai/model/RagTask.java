package com.yizhaoqi.smartpai.model;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Data
@Entity
@Table(
        name = "rag_task",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_rag_task_task_id", columnNames = "task_id"),
                @UniqueConstraint(name = "uk_rag_task_doc_ver_op", columnNames = {"doc_id", "version", "op_type"})
        },
        indexes = {
                @Index(name = "idx_rag_task_doc_op", columnList = "doc_id,op_type"),
                @Index(name = "idx_rag_task_status", columnList = "status")
        }
)
public class RagTask {

    public enum OpType {
        INGEST,
        DELETE,
        REINDEX
    }

    public enum Status {
        QUEUED,
        INGESTING,
        AVAILABLE,
        FAILED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false, length = 64)
    private String taskId;

    @Column(name = "doc_id", nullable = false, length = 64)
    private String docId;

    @Column(nullable = false)
    private Integer version;

    @Enumerated(EnumType.STRING)
    @Column(name = "op_type", nullable = false, length = 16)
    private OpType opType;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(name = "file_name")
    private String fileName;

    @Column(name = "bucket_name", length = 64)
    private String bucketName;

    @Column(name = "object_key", length = 512)
    private String objectKey;

    @Column(name = "file_path", length = 2048)
    private String filePath;

    @Column(name = "user_id", length = 64)
    private String userId;

    @Column(name = "org_tag", length = 64)
    private String orgTag;

    @Column(name = "is_public", nullable = false)
    private boolean isPublic;

    @Column(name = "model_version", length = 128)
    private String modelVersion;

    @Column(name = "actual_chunk_count")
    private Integer actualChunkCount;

    @Column(name = "actual_embedding_tokens")
    private Long actualEmbeddingTokens;

    @Column(name = "error_code", length = 128)
    private String errorCode;

    @Column(name = "error_message", columnDefinition = "TEXT")
    private String errorMessage;

    @Column(name = "started_at")
    private LocalDateTime startedAt;

    @Column(name = "finished_at")
    private LocalDateTime finishedAt;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}

