-- Manual provisioning for PostgreSQL (run as a superuser). Defaults: database megacalendar, user admin / admin.
CREATE ROLE admin LOGIN PASSWORD 'admin';
CREATE DATABASE megacalendar OWNER admin ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE megacalendar TO admin;
\connect megacalendar
GRANT ALL ON SCHEMA public TO admin;
