-- Manual provisioning for MySQL 8 / MariaDB (run as root). Defaults: database megacalendar, user admin / admin.
CREATE DATABASE IF NOT EXISTS `megacalendar` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'admin'@'%' IDENTIFIED BY 'admin';
GRANT ALL PRIVILEGES ON `megacalendar`.* TO 'admin'@'%';
FLUSH PRIVILEGES;

-- Master application user (login master / password master). The application creates this account
-- automatically on first start; run the statement below only if you need to (re)create it by hand,
-- after the application has created the tables. Change the password afterwards (Profile > Password
-- or: python scripts/manage_users.py set-password master).
INSERT INTO users (username, password_hash, is_master, is_active, project_limit, created_at)
SELECT 'master', 'pbkdf2_sha256$600000$megacalendarmaster$7a8f219610735896eca7e94be5793b09bdfabc1782828c9a7d2fd33d93574525', 1, 1, NULL, NOW()
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'master');
