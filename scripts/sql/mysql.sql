-- Manual provisioning for MySQL 8 / MariaDB (run as root). Defaults: database megacalendar, user admin / admin.
CREATE DATABASE IF NOT EXISTS `megacalendar` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'admin'@'%' IDENTIFIED BY 'admin';
GRANT ALL PRIVILEGES ON `megacalendar`.* TO 'admin'@'%';
FLUSH PRIVILEGES;
