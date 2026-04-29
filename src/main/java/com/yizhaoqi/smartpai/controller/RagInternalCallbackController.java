package com.yizhaoqi.smartpai.controller;

import com.yizhaoqi.smartpai.config.RagProperties;
import com.yizhaoqi.smartpai.model.RagTask;
import com.yizhaoqi.smartpai.service.RagTaskService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/internal/rag/callback")
public class RagInternalCallbackController {

    private final RagTaskService ragTaskService;
    private final RagProperties ragProperties;

    public RagInternalCallbackController(RagTaskService ragTaskService, RagProperties ragProperties) {
        this.ragTaskService = ragTaskService;
        this.ragProperties = ragProperties;
    }

    @PostMapping("/ingest")
    public ResponseEntity<Map<String, Object>> ingestCallback(
            @RequestHeader(value = "X-Rag-Callback-Token", required = false) String callbackToken,
            @RequestBody IngestCallbackRequest request
    ) {
        if (!matchesCallbackToken(callbackToken, ragProperties.getCallback().getToken())) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of(
                    "code", 401,
                    "message", "非法回调",
                    "data", Collections.emptyMap()
            ));
        }

        try {
            RagTask task = ragTaskService.applyIngestCallback(
                    request.taskId(),
                    request.docId(),
                    request.status(),
                    request.chunkCount(),
                    request.embeddingTokens(),
                    request.modelVersion(),
                    request.errorCode(),
                    request.errorMessage()
            );
            return ResponseEntity.ok(Map.of(
                    "code", 200,
                    "message", "ok",
                    "data", ragTaskService.toSummary(task)
            ));
        } catch (Exception e) {
            String message = e.getMessage() == null ? "unknown error" : e.getMessage();
            if (message.contains("not found")) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of(
                        "code", 404,
                        "message", "任务不存在: " + message,
                        "data", Collections.emptyMap()
                ));
            }
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of(
                    "code", 500,
                    "message", "回调处理失败: " + message,
                    "data", Collections.emptyMap()
            ));
        }
    }

    private boolean matchesCallbackToken(String actual, String expected) {
        if (actual == null || expected == null || expected.isBlank()) {
            return false;
        }
        byte[] actualBytes = actual.getBytes(StandardCharsets.UTF_8);
        byte[] expectedBytes = expected.getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(actualBytes, expectedBytes);
    }

    public record IngestCallbackRequest(
            String taskId,
            String docId,
            String status,
            Integer chunkCount,
            Long embeddingTokens,
            String modelVersion,
            String errorCode,
            String errorMessage
    ) {}
}
