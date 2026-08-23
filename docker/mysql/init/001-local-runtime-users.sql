-- Local Compose identities only. Production credentials belong in a managed
-- secret store and production MySQL must require verified TLS.
CREATE USER IF NOT EXISTS 'incident_api'@'%' IDENTIFIED BY 'local-api-only';
CREATE USER IF NOT EXISTS 'incident_worker'@'%' IDENTIFIED BY 'local-worker-only';
CREATE USER IF NOT EXISTS 'incident_migrator'@'%' IDENTIFIED BY 'local-migrator-only';

GRANT SELECT, INSERT, UPDATE, DELETE ON incident_agent.* TO 'incident_api'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON incident_agent.* TO 'incident_worker'@'%';
GRANT ALL PRIVILEGES ON incident_agent.* TO 'incident_migrator'@'%';
FLUSH PRIVILEGES;
