-- =====================================================================
-- Stored Procedure: sp_truncate_all_except_users
-- Purpose: Truncates all transactional, project, workflow, and evidence tables
--          while preserving user login authentication and RBAC roles/permissions.
-- 
-- Usage:
--   1. Keep ALL current login users & roles:
--      CALL sp_truncate_all_except_users(NULL);
--
--   2. Keep ONLY a specific login user (e.g., 'admin@tdd.local'):
--      CALL sp_truncate_all_except_users('admin@tdd.local');
-- =====================================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_truncate_all_except_users$$

CREATE PROCEDURE sp_truncate_all_except_users(
    IN p_keep_specific_user_email VARCHAR(255)
)
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE target_table VARCHAR(128);
    
    -- Select all tables in current database except user, RBAC, and AI config definitions
    DECLARE table_cursor CURSOR FOR
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_type = 'BASE TABLE'
          AND table_name NOT IN (
              'users',
              'roles',
              'permissions',
              'role_permissions',
              'user_roles',
              'model_configurations',
              'prompt_versions',
              'tool_schemas'
          );
          
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

    -- Disable foreign key checks for safe truncation
    SET FOREIGN_KEY_CHECKS = 0;

    -- Iterate and truncate all application tables
    OPEN table_cursor;
    table_loop: LOOP
        FETCH table_cursor INTO target_table;
        IF done THEN
            LEAVE table_loop;
        END IF;

        SET @truncate_sql = CONCAT('TRUNCATE TABLE `', target_table, '`');
        PREPARE stmt FROM @truncate_sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END LOOP;
    CLOSE table_cursor;

    -- If a specific user email was requested to be kept, prune all other users
    IF p_keep_specific_user_email IS NOT NULL AND p_keep_specific_user_email != '' THEN
        -- Delete user_roles for non-matching users
        DELETE FROM user_roles 
        WHERE user_id NOT IN (
            SELECT id FROM (SELECT id FROM users WHERE email = p_keep_specific_user_email) AS keep_u
        );

        -- Delete other users
        DELETE FROM users 
        WHERE email != p_keep_specific_user_email;
    END IF;

    -- Re-enable foreign key checks
    SET FOREIGN_KEY_CHECKS = 1;

    SELECT 'Truncation complete. All tables truncated except login users / RBAC data.' AS result;
END$$

DELIMITER ;
