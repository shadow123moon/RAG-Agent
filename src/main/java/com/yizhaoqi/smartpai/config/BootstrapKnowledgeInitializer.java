package com.yizhaoqi.smartpai.config;

import com.yizhaoqi.smartpai.model.FileUpload;
import com.yizhaoqi.smartpai.model.RagIngestTask;
import com.yizhaoqi.smartpai.model.RagTask;
import com.yizhaoqi.smartpai.model.User;
import com.yizhaoqi.smartpai.repository.DocumentVectorRepository;
import com.yizhaoqi.smartpai.repository.FileUploadRepository;
import com.yizhaoqi.smartpai.repository.RagTaskRepository;
import com.yizhaoqi.smartpai.repository.UserRepository;
import com.yizhaoqi.smartpai.service.ElasticsearchService;
import com.yizhaoqi.smartpai.service.RagTaskService;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import org.apache.commons.codec.digest.DigestUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * 启动时导入内置知识库文档（新版链路：发送 rag-ingest 任务到 Python RAG）。
 */
@Component
@Order(3)
@ConditionalOnProperty(name = "knowledge.bootstrap.enabled", havingValue = "true", matchIfMissing = true)
public class BootstrapKnowledgeInitializer implements CommandLineRunner {

    private static final Logger logger = LoggerFactory.getLogger(BootstrapKnowledgeInitializer.class);

    private final ElasticsearchService elasticsearchService;
    private final FileUploadRepository fileUploadRepository;
    private final DocumentVectorRepository documentVectorRepository;
    private final RagTaskRepository ragTaskRepository;
    private final RagTaskService ragTaskService;
    private final MinioClient minioClient;
    private final UserRepository userRepository;
    private final KafkaTemplate<String, Object> kafkaTemplate;
    private final KafkaConfig kafkaConfig;

    @Value("${knowledge.bootstrap.path:docs/paismart.pdf}")
    private String bootstrapDocumentPath;

    @Value("${knowledge.bootstrap.org-tag:default}")
    private String bootstrapOrgTag;

    @Value("${knowledge.bootstrap.public:true}")
    private boolean bootstrapPublic;

    @Value("${knowledge.bootstrap.user-id:system-bootstrap}")
    private String bootstrapUserId;

    @Value("${minio.bucketName:uploads}")
    private String minioBucketName;

    @Value("${admin.bootstrap.username:}")
    private String adminUsername;

    public BootstrapKnowledgeInitializer(ElasticsearchService elasticsearchService,
                                         FileUploadRepository fileUploadRepository,
                                         DocumentVectorRepository documentVectorRepository,
                                         RagTaskRepository ragTaskRepository,
                                         RagTaskService ragTaskService,
                                         MinioClient minioClient,
                                         UserRepository userRepository,
                                         KafkaTemplate<String, Object> kafkaTemplate,
                                         KafkaConfig kafkaConfig) {
        this.elasticsearchService = elasticsearchService;
        this.fileUploadRepository = fileUploadRepository;
        this.documentVectorRepository = documentVectorRepository;
        this.ragTaskRepository = ragTaskRepository;
        this.ragTaskService = ragTaskService;
        this.minioClient = minioClient;
        this.userRepository = userRepository;
        this.kafkaTemplate = kafkaTemplate;
        this.kafkaConfig = kafkaConfig;
    }

    @Override
    public void run(String... args) throws Exception {
        Path documentPath = resolveDocumentPath();
        if (!Files.isRegularFile(documentPath)) {
            logger.warn("启动知识库文档不存在，跳过导入: {}", documentPath);
            return;
        }

        String fileName = documentPath.getFileName().toString();
        String fileMd5 = calculateMd5(documentPath);
        long totalSize = Files.size(documentPath);
        String ownerUserId = resolveOwnerUserId();

        cleanupBootstrapHistory(fileName, fileMd5, ownerUserId);
        if (isBootstrapDocumentReadyOrInProgress(fileMd5, fileName, ownerUserId)) {
            logger.info("启动知识库文档已就绪或任务处理中，跳过重复处理: fileName={}, fileMd5={}", fileName, fileMd5);
            return;
        }

        cleanupBootstrapData(fileMd5, ownerUserId);
        submitBootstrapIngestTask(documentPath, fileMd5, fileName, totalSize, ownerUserId);
    }

    private void cleanupBootstrapHistory(String fileName, String currentFileMd5, String ownerUserId) {
        List<FileUpload> bootstrapHistory = fileUploadRepository.findByUserIdAndFileNameOrderByCreatedAtDesc(ownerUserId, fileName);
        if (bootstrapHistory.isEmpty()) {
            return;
        }

        boolean keptCurrentRecord = false;
        List<FileUpload> duplicateCurrentRecords = new ArrayList<>();
        Set<String> staleFileMd5s = new LinkedHashSet<>();

        for (FileUpload fileUpload : bootstrapHistory) {
            if (currentFileMd5.equals(fileUpload.getFileMd5())) {
                if (!keptCurrentRecord) {
                    keptCurrentRecord = true;
                } else {
                    duplicateCurrentRecords.add(fileUpload);
                }
            } else {
                staleFileMd5s.add(fileUpload.getFileMd5());
            }
        }

        staleFileMd5s.forEach(staleFileMd5 -> {
            logger.info("清理旧版本启动知识库文档: oldFileMd5={}, currentFileMd5={}", staleFileMd5, currentFileMd5);
            cleanupBootstrapData(staleFileMd5, ownerUserId);
        });

        if (!duplicateCurrentRecords.isEmpty()) {
            logger.warn("检测到重复的启动知识库文件记录，删除多余记录: fileName={}, fileMd5={}, duplicates={}",
                    fileName, currentFileMd5, duplicateCurrentRecords.size());
            fileUploadRepository.deleteAll(duplicateCurrentRecords);
        }
    }

    private boolean isBootstrapDocumentReadyOrInProgress(String fileMd5, String fileName, String ownerUserId) {
        Optional<FileUpload> existingFile = fileUploadRepository.findFirstByFileMd5AndUserIdOrderByCreatedAtDesc(fileMd5, ownerUserId);
        long fileRecordCount = fileUploadRepository.countByFileMd5AndUserId(fileMd5, ownerUserId);
        long esCount = elasticsearchService.countByFileMd5(fileMd5);
        Optional<RagTask> latestIngestTask = ragTaskRepository.findTopByDocIdAndOpTypeOrderByVersionDesc(fileMd5, RagTask.OpType.INGEST);

        if (existingFile.isEmpty()) {
            return false;
        }

        FileUpload fileUpload = existingFile.get();
        boolean metadataMatches = fileName.equals(fileUpload.getFileName())
                && bootstrapOrgTag.equals(fileUpload.getOrgTag())
                && bootstrapPublic == fileUpload.isPublic()
                && fileUpload.getStatus() == FileUpload.STATUS_COMPLETED
                && fileRecordCount == 1;

        if (!metadataMatches) {
            logger.info("启动知识库元数据变化，准备重新导入: fileMd5={}, fileRecords={}", fileMd5, fileRecordCount);
            return false;
        }

        if (latestIngestTask.isPresent()) {
            RagTask.Status status = latestIngestTask.get().getStatus();
            if (status == RagTask.Status.AVAILABLE && esCount > 0) {
                return true;
            }
            if (status == RagTask.Status.QUEUED || status == RagTask.Status.INGESTING) {
                logger.info("启动知识库任务处理中，等待完成: taskId={}, status={}",
                        latestIngestTask.get().getTaskId(), status);
                return true;
            }
            logger.info("启动知识库任务状态需要重建: taskId={}, status={}",
                    latestIngestTask.get().getTaskId(), status);
            return false;
        }

        // 兼容历史：存在 ES 数据但没有 rag_task 记录时，认为已就绪
        return esCount > 0;
    }

    private void submitBootstrapIngestTask(Path documentPath,
                                           String fileMd5,
                                           String fileName,
                                           long totalSize,
                                           String ownerUserId) throws IOException {
        logger.info("开始提交启动知识库入库任务: path={}, fileMd5={}", documentPath, fileMd5);

        uploadToMinio(documentPath, fileMd5);
        FileUpload fileUpload = upsertFileUpload(fileMd5, fileName, totalSize, ownerUserId);

        String objectKey = "merged/" + fileMd5;
        String filePath = "minio://" + minioBucketName + "/" + objectKey;
        RagTask ragTask = ragTaskService.createIngestTask(fileUpload, minioBucketName, objectKey, filePath);
        RagIngestTask task = new RagIngestTask(
                ragTask.getTaskId(),
                ragTask.getDocId(),
                ragTask.getVersion(),
                fileUpload.getFileName(),
                minioBucketName,
                objectKey,
                filePath,
                fileUpload.getUserId(),
                fileUpload.getOrgTag(),
                fileUpload.isPublic()
        );

        try {
            kafkaTemplate.send(kafkaConfig.getRagIngestTopic(), ragTask.getDocId(), task).get(10, TimeUnit.SECONDS);
        } catch (Exception e) {
            throw new RuntimeException("发送启动知识库入库任务失败", e);
        }

        logger.info("启动知识库入库任务已提交: taskId={}, fileMd5={}, topic={}",
                ragTask.getTaskId(), fileMd5, kafkaConfig.getRagIngestTopic());
    }

    private FileUpload upsertFileUpload(String fileMd5, String fileName, long totalSize, String ownerUserId) {
        FileUpload fileUpload = fileUploadRepository.findFirstByFileMd5AndUserIdOrderByCreatedAtDesc(fileMd5, ownerUserId)
                .orElseGet(FileUpload::new);
        fileUpload.setFileMd5(fileMd5);
        fileUpload.setFileName(fileName);
        fileUpload.setTotalSize(totalSize);
        fileUpload.setStatus(FileUpload.STATUS_COMPLETED);
        fileUpload.setUserId(ownerUserId);
        fileUpload.setOrgTag(bootstrapOrgTag);
        fileUpload.setPublic(bootstrapPublic);
        fileUpload.setMergedAt(LocalDateTime.now());
        return fileUploadRepository.save(fileUpload);
    }

    private void uploadToMinio(Path documentPath, String fileMd5) throws IOException {
        String objectName = "merged/" + fileMd5;
        String contentType = Files.probeContentType(documentPath);
        if (contentType == null || contentType.isBlank()) {
            contentType = "application/pdf";
        }
        try (InputStream inputStream = Files.newInputStream(documentPath)) {
            minioClient.putObject(
                    PutObjectArgs.builder()
                            .bucket(minioBucketName)
                            .object(objectName)
                            .stream(inputStream, Files.size(documentPath), -1)
                            .contentType(contentType)
                            .build()
            );
            logger.info("启动知识库文档已写入 MinIO: bucket={}, object={}", minioBucketName, objectName);
        } catch (Exception e) {
            throw new RuntimeException("写入 MinIO 失败", e);
        }
    }

    private void cleanupBootstrapData(String fileMd5, String ownerUserId) {
        try {
            minioClient.removeObject(
                    RemoveObjectArgs.builder()
                            .bucket(minioBucketName)
                            .object("merged/" + fileMd5)
                            .build()
            );
        } catch (Exception e) {
            logger.warn("清理启动知识库 MinIO 文件失败: fileMd5={}, error={}", fileMd5, e.getMessage());
        }

        try {
            elasticsearchService.deleteByFileMd5(fileMd5);
        } catch (Exception e) {
            logger.warn("清理启动知识库 ES 数据失败: fileMd5={}, error={}", fileMd5, e.getMessage());
        }

        try {
            documentVectorRepository.deleteByFileMd5(fileMd5);
        } catch (Exception e) {
            logger.warn("清理启动知识库分块数据失败: fileMd5={}, error={}", fileMd5, e.getMessage());
        }

        try {
            fileUploadRepository.deleteByFileMd5AndUserId(fileMd5, ownerUserId);
        } catch (Exception e) {
            logger.warn("清理启动知识库文件记录失败: fileMd5={}, error={}", fileMd5, e.getMessage());
        }

        try {
            ragTaskRepository.deleteByDocId(fileMd5);
        } catch (Exception e) {
            logger.warn("清理启动知识库任务记录失败: fileMd5={}, error={}", fileMd5, e.getMessage());
        }
    }

    private String resolveOwnerUserId() {
        Optional<User> adminUser = findAdminUser();
        if (adminUser.isPresent()) {
            String ownerUserId = String.valueOf(adminUser.get().getId());
            logger.info("启动知识库文档归属管理员账号: username={}, userId={}",
                    adminUser.get().getUsername(), ownerUserId);
            return ownerUserId;
        }

        logger.warn("未找到管理员账号，启动知识库文档回退使用 userId={}", bootstrapUserId);
        return bootstrapUserId;
    }

    private Optional<User> findAdminUser() {
        if (adminUsername != null && !adminUsername.isBlank()) {
            Optional<User> configuredAdmin = userRepository.findByUsername(adminUsername)
                    .filter(user -> User.Role.ADMIN.equals(user.getRole()));
            if (configuredAdmin.isPresent()) {
                return configuredAdmin;
            }
        }

        return userRepository.findAll().stream()
                .filter(user -> User.Role.ADMIN.equals(user.getRole()))
                .findFirst();
    }

    private Path resolveDocumentPath() {
        Path path = Path.of(bootstrapDocumentPath);
        if (path.isAbsolute()) {
            return path.normalize();
        }
        return Path.of(System.getProperty("user.dir")).resolve(path).normalize();
    }

    private String calculateMd5(Path documentPath) throws IOException {
        try (InputStream inputStream = Files.newInputStream(documentPath)) {
            return DigestUtils.md5Hex(inputStream);
        }
    }
}
