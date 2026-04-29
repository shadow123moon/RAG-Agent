package com.yizhaoqi.smartpai.controller;

import com.yizhaoqi.smartpai.model.User;
import com.yizhaoqi.smartpai.repository.UserRepository;
import com.yizhaoqi.smartpai.service.OrgTagCacheService;
import com.yizhaoqi.smartpai.service.RagPythonClient;
import com.yizhaoqi.smartpai.service.RagTaskService;
import com.yizhaoqi.smartpai.utils.LogUtils;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@RequestMapping("/api/v1/rag")
public class RagController {

    private final RagPythonClient ragPythonClient;
    private final UserRepository userRepository;
    private final OrgTagCacheService orgTagCacheService;
    private final RagTaskService ragTaskService;

    public RagController(
            RagPythonClient ragPythonClient,
            UserRepository userRepository,
            OrgTagCacheService orgTagCacheService,
            RagTaskService ragTaskService
    ) {
        this.ragPythonClient = ragPythonClient;
        this.userRepository = userRepository;
        this.orgTagCacheService = orgTagCacheService;
        this.ragTaskService = ragTaskService;
    }

    @PostMapping("/query")
    public ResponseEntity<Map<String, Object>> query(@RequestBody RagQueryRequest request) {
        LogUtils.PerformanceMonitor monitor = LogUtils.startPerformanceMonitor("RAG_QUERY_PROXY");
        try {
            User user = currentUser();
            List<String> effectiveOrgTags = orgTagCacheService.getUserEffectiveOrgTags(user.getUsername());

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("query", request.query());
            payload.put("topK", request.topK() == null ? 8 : request.topK());
            payload.put("chatId", request.chatId());
            payload.put("history", request.history() == null ? List.of() : request.history());
            payload.put("userId", String.valueOf(user.getId()));
            payload.put("username", user.getUsername());
            payload.put("role", user.getRole().name());
            payload.put("allowedOrgTags", effectiveOrgTags);
            payload.put("allowPublic", true);

            Map<String, Object> pythonResponse = ragPythonClient.query(payload);
            Map<String, Object> body = new HashMap<>();
            body.put("code", 200);
            body.put("message", "success");
            body.put("data", pythonResponse);
            monitor.end("RAG query success");
            return ResponseEntity.ok(body);
        } catch (Exception e) {
            monitor.end("RAG query failed: " + e.getMessage());
            Map<String, Object> body = new HashMap<>();
            body.put("code", 500);
            body.put("message", "RAG 查询失败: " + e.getMessage());
            body.put("data", Collections.emptyMap());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
        }
    }

    @GetMapping("/tasks/{docId}/latest")
    public ResponseEntity<Map<String, Object>> latestTask(@PathVariable String docId) {
        try {
            Optional<Map<String, Object>> data = ragTaskService.findLatestIngestTask(docId).map(ragTaskService::toSummary);
            if (data.isEmpty()) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of(
                        "code", 404,
                        "message", "任务不存在",
                        "data", Collections.emptyMap()
                ));
            }
            return ResponseEntity.ok(Map.of(
                    "code", 200,
                    "message", "success",
                    "data", data.get()
            ));
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of(
                    "code", 500,
                    "message", "获取任务状态失败: " + e.getMessage(),
                    "data", Collections.emptyMap()
            ));
        }
    }

    @GetMapping("/tasks/by-task-id/{taskId}")
    public ResponseEntity<Map<String, Object>> taskByTaskId(@PathVariable String taskId) {
        try {
            Optional<Map<String, Object>> data = ragTaskService.findByTaskId(taskId).map(ragTaskService::toSummary);
            if (data.isEmpty()) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of(
                        "code", 404,
                        "message", "任务不存在",
                        "data", Collections.emptyMap()
                ));
            }
            return ResponseEntity.ok(Map.of(
                    "code", 200,
                    "message", "success",
                    "data", data.get()
            ));
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of(
                    "code", 500,
                    "message", "获取任务状态失败: " + e.getMessage(),
                    "data", Collections.emptyMap()
            ));
        }
    }

    private User currentUser() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || authentication.getName() == null) {
            throw new RuntimeException("未获取到当前用户");
        }
        String username = authentication.getName();
        return userRepository.findByUsername(username).orElseThrow(() -> new RuntimeException("用户不存在: " + username));
    }

    public record RagQueryRequest(
            String query,
            Integer topK,
            String chatId,
            List<Map<String, String>> history
    ) {}
}
