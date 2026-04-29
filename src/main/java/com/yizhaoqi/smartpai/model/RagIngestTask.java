package com.yizhaoqi.smartpai.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class RagIngestTask {
    private String taskId;
    private String docId;
    private Integer version;
    private String fileName;
    private String bucket;
    private String objectKey;
    private String filePath;
    private String userId;
    private String orgTag;
    private boolean isPublic;
}

