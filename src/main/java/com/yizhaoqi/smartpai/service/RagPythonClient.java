package com.yizhaoqi.smartpai.service;

import com.yizhaoqi.smartpai.config.RagProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.Map;

@Service
public class RagPythonClient {

    private static final Logger logger = LoggerFactory.getLogger(RagPythonClient.class);
    private static final Duration QUERY_TIMEOUT = Duration.ofSeconds(90);

    private final RagProperties ragProperties;

    public RagPythonClient(RagProperties ragProperties) {
        this.ragProperties = ragProperties;
    }

    public Map<String, Object> query(Map<String, Object> requestBody) {
        RagProperties.Python python = ragProperties.getPython();
        WebClient client = WebClient.builder()
                .baseUrl(python.getBaseUrl())
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .defaultHeader("X-Internal-Token", python.getInternalToken())
                .build();

        try {
            return client.post()
                    .uri(python.getQueryPath())
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(new ParameterizedTypeReference<Map<String, Object>>() {})
                    .timeout(QUERY_TIMEOUT)
                    .block();
        } catch (Exception e) {
            logger.error("调用 Python RAG query 接口失败, url={}{}", python.getBaseUrl(), python.getQueryPath(), e);
            throw new RuntimeException("调用 Python RAG 服务失败: " + e.getMessage(), e);
        }
    }

    public Mono<Map<String, Object>> queryAsync(Map<String, Object> requestBody) {
        RagProperties.Python python = ragProperties.getPython();
        WebClient client = WebClient.builder()
                .baseUrl(python.getBaseUrl())
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .defaultHeader("X-Internal-Token", python.getInternalToken())
                .build();

        return client.post()
                .uri(python.getQueryPath())
                .bodyValue(requestBody)
                .retrieve()
                .bodyToMono(new ParameterizedTypeReference<Map<String, Object>>() {})
                .timeout(QUERY_TIMEOUT);
    }
}

