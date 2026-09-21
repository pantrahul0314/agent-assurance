CREATE ROLE assure_migrate LOGIN PASSWORD 'migrate';
CREATE ROLE assure_app LOGIN PASSWORD 'app' NOSUPERUSER NOBYPASSRLS;

GRANT CONNECT ON DATABASE assure TO assure_migrate, assure_app;
GRANT CREATE ON DATABASE assure TO assure_migrate;
GRANT ALL ON SCHEMA public TO assure_migrate;
