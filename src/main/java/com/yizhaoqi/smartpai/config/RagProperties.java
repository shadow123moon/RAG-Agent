package com.yizhaoqi.smartpai.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "rag")
public class RagProperties {
    private Python python = new Python();
    private Callback callback = new Callback();

    @Data
    public static class Python {
        private String baseUrl = "http://localhost:18080";
        private String internalToken = "change-me";
        private String queryPath = "/internal/v1/query";
    }

    @Data
    public static class Callback {
        private String token = "change-me";
    }
}

