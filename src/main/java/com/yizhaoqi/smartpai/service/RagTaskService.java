package com.yizhaoqi.smartpai.service;

import com.yizhaoqi.smartpai.model.FileUpload;
import com.yizhaoqi.smartpai.model.RagTask;
import com.yizhaoqi.smartpai.repository.FileUploadRepository;
import com.yizhaoqi.smartpai.repository.RagTaskRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Service
public class RagTaskService {

    private static final Logger logger = LoggerFactory.getLogger(RagTaskService.class);

    private final RagTaskRepository ragTaskRepository;
    private final FileUploadRepository fileUploadRepository;

    public RagTaskService(RagTaskRepository ragTaskRepository, FileUploadRepository fileUploadRepository) {
        this.ragTaskRepository = ragTaskRepository;
        this.fileUploadRepository = fileUploadRepository;
    }

    @Transactional
    public RagTask createIngestTask(FileUpload fileUpload, String bucketName, String objectKey, String filePath) {
        int maxRetries = 3;
        for (int attempt = 1; attempt <= maxRetries; attempt++) {
            int nextVersion = ragTaskRepository
                    .findTopByDocIdAndOpTypeOrderByVersionDesc(fileUpload.getFileMd5(), RagTask.OpType.INGEST)
                    .map(task -> task.getVersion() + 1)
                    .orElse(1);

            RagTask task = new RagTask();
            task.setTaskId(buildTaskId("ing"));
            task.setDocId(fileUpload.getFileMd5());
            task.setVersion(nextVersion);
            task.setOpType(RagTask.OpType.INGEST);
            task.setStatus(RagTask.Status.QUEUED);
            task.setFileName(fileUpload.getFileName());
            task.setBucketName(bucketName);
            task.setObjectKey(objectKey);
            task.setFilePath(filePath);
            task.setUserId(fileUpload.getUserId());
            task.setOrgTag(fileUpload.getOrgTag());
            task.setPublic(fileUpload.isPublic());

            try {
                return ragTaskRepository.save(task);
            } catch (DataIntegrityViolationException e) {
                logger.warn(
                        "Create ingest task conflict, retrying: docId={}, nextVersion={}, attempt={}/{}",
                        fileUpload.getFileMd5(),
                        nextVersion,
                        attempt,
                        maxRetries
                );
            }
        }
        throw new RuntimeException("创建 RAG 入库任务失败，请重试");
    }

    public Optional<RagTask> findByTaskId(String taskId) {
        return ragTaskRepository.findByTaskId(taskId);
    }

    public Optional<RagTask> findLatestIngestTask(String docId) {
        return ragTaskRepository.findTopByDocIdAndOpTypeOrderByVersionDesc(docId, RagTask.OpType.INGEST);
    }

    @Transactional
    public RagTask applyIngestCallback(
            String taskId,
            String docId,
            String status,
            Integer chunkCount,
            Long embeddingTokens,
            String modelVersion,
            String errorCode,
            String errorMessage
    ) {
        RagTask task = resolveTaskForCallback(taskId, docId);
        RagTask.Status nextStatus = parseStatus(status);
        RagTask.Status prev = task.getStatus();
        task.setStatus(nextStatus);
        task.setActualChunkCount(chunkCount);
        task.setActualEmbeddingTokens(embeddingTokens);
        task.setModelVersion(modelVersion);
        task.setErrorCode(errorCode);
        task.setErrorMessage(errorMessage);

        if (nextStatus == RagTask.Status.INGESTING && task.getStartedAt() == null) {
            task.setStartedAt(LocalDateTime.now());
        }
        if ((nextStatus == RagTask.Status.AVAILABLE || nextStatus == RagTask.Status.FAILED) && task.getFinishedAt() == null) {
            task.setFinishedAt(LocalDateTime.now());
            if (task.getStartedAt() == null) {
                task.setStartedAt(LocalDateTime.now());
            }
        }

        RagTask saved = ragTaskRepository.save(task);
        updateFileUploadUsage(saved);
        logger.info("RAG ingest callback applied: taskId={}, docId={}, status {} -> {}", saved.getTaskId(), saved.getDocId(), prev, nextStatus);
        return saved;
    }

    private RagTask resolveTaskForCallback(String taskId, String docId) {
        if (taskId != null && !taskId.isBlank()) {
            return ragTaskRepository.findByTaskId(taskId)
                    .orElseThrow(() -> new RuntimeException("RAG task not found: " + taskId));
        }
        if (docId != null && !docId.isBlank()) {
            return ragTaskRepository.findTopByDocIdAndOpTypeOrderByVersionDesc(docId, RagTask.OpType.INGEST)
                    .orElseThrow(() -> new RuntimeException("RAG task not found for docId: " + docId));
        }
        throw new RuntimeException("taskId/docId cannot both be empty");
    }

    private RagTask.Status parseStatus(String status) {
        if (status == null || status.isBlank()) {
            throw new RuntimeException("status is required");
        }
        String normalized = status.trim().toUpperCase(Locale.ROOT);
        return switch (normalized) {
            case "QUEUED" -> RagTask.Status.QUEUED;
            case "INGESTING", "PROCESSING", "RUNNING" -> RagTask.Status.INGESTING;
            case "AVAILABLE", "SUCCESS", "COMPLETED", "DONE" -> RagTask.Status.AVAILABLE;
            case "FAILED", "ERROR" -> RagTask.Status.FAILED;
            default -> throw new RuntimeException("unsupported status: " + status);
        };
    }

    private void updateFileUploadUsage(RagTask task) {
        if (task.getDocId() == null || task.getUserId() == null) {
            return;
        }
        if (task.getOpType() != RagTask.OpType.INGEST) {
            return;
        }
        Optional<RagTask> latestTaskOpt = ragTaskRepository.findTopByDocIdAndOpTypeOrderByVersionDesc(task.getDocId(), RagTask.OpType.INGEST);
        if (latestTaskOpt.isPresent() && !latestTaskOpt.get().getTaskId().equals(task.getTaskId())) {
            logger.info(
                    "Skip FileUpload usage update for stale callback: taskId={}, docId={}, version={}, latestTaskId={}, latestVersion={}",
                    task.getTaskId(),
                    task.getDocId(),
                    task.getVersion(),
                    latestTaskOpt.get().getTaskId(),
                    latestTaskOpt.get().getVersion()
            );
            return;
        }
        Optional<FileUpload> optional = fileUploadRepository.findFirstByFileMd5AndUserIdOrderByCreatedAtDesc(task.getDocId(), task.getUserId());
        if (optional.isEmpty()) {
            return;
        }
        FileUpload upload = optional.get();
        if (task.getActualChunkCount() != null) {
            upload.setActualChunkCount(task.getActualChunkCount());
        }
        if (task.getActualEmbeddingTokens() != null) {
            upload.setActualEmbeddingTokens(task.getActualEmbeddingTokens());
        }
        fileUploadRepository.save(upload);
    }

    private String buildTaskId(String prefix) {
        return prefix + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    public Map<String, Object> toSummary(RagTask task) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("taskId", task.getTaskId());
        summary.put("docId", task.getDocId());
        summary.put("version", task.getVersion());
        summary.put("status", task.getStatus().name());
        summary.put("opType", task.getOpType().name());
        summary.put("actualChunkCount", task.getActualChunkCount() == null ? 0 : task.getActualChunkCount());
        summary.put("actualEmbeddingTokens", task.getActualEmbeddingTokens() == null ? 0 : task.getActualEmbeddingTokens());
        summary.put("modelVersion", task.getModelVersion() == null ? "" : task.getModelVersion());
        summary.put("errorCode", task.getErrorCode() == null ? "" : task.getErrorCode());
        summary.put("errorMessage", task.getErrorMessage() == null ? "" : task.getErrorMessage());
        summary.put("createdAt", task.getCreatedAt() == null ? "" : task.getCreatedAt().toString());
        summary.put("updatedAt", task.getUpdatedAt() == null ? "" : task.getUpdatedAt().toString());
        return summary;
    }
}
