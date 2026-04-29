package com.yizhaoqi.smartpai.repository;

import com.yizhaoqi.smartpai.model.RagTask;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface RagTaskRepository extends JpaRepository<RagTask, Long> {
    Optional<RagTask> findByTaskId(String taskId);

    Optional<RagTask> findTopByDocIdAndOpTypeOrderByVersionDesc(String docId, RagTask.OpType opType);

    void deleteByDocId(String docId);
}
