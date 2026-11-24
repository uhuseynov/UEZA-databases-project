# UEZA Databases Project

Technical documentation for UEZA: Wikipedia question answering with native vector search in MariaDB. Start with the [README](../README.md) for the overview, the quick start and the main results.

## Start here

- [Architecture](./architecture/Home.md): the ingest and query flows, modules, dependency directions
- [Data decisions](./data_decisions.md): topic, the 262 articles, cleaning and chunking rules

## Architecture

- [Architecture Overview](./architecture/Home.md)
- [Configuration](./architecture/Configuration.md): every setting and where it is used
- [Dependency Injection](./architecture/Dependency-Injection.md)
- [Logging](./architecture/Logging.md)

## Database

- [Database Overview](./database/Home.md)
- [Data Model](./database/Data-Model.md)
- [Schema Management](./database/Schema.md): `schema.sql` as the schema definition, changing it, its limits
- [Connection and Sessions](./database/Connection.md)
- [Vector Search and Index Parameters](./database/Vector-Search.md)
- [Vector Index State](./database/Index-State.md)
- [Choosing M](./database/Choosing-M.md)
- [FAISS Baseline](./database/FAISS-Baseline.md)
- [Findings](./database/Findings.md): what we learned, why MariaDB, where it loses
- [Podman on Windows](./database/podman.md)

## Ingestion

- [Ingestion Overview](./ingestion/Home.md): pipeline, snapshot and live sync
- [Article Cache](./ingestion/Cache.md)
- [MediaWiki Integration](./ingestion/mediawiki/Home.md)

## Retrieval, RAG and Evaluation

- [Retrieval and RAG](./rag/Home.md): the search statement, not-found logic, prompt, API and web UI
- [Evaluation](./evaluation/Home.md): ground truth, metrics, method, index sweeps, FAISS, the language model's answers
- [Results](./evaluation/Results.md): the measured results
- [eval/results index](../eval/results/README.md): every recorded run and which experiment it belongs to

## Development

- [Development Workflow](./development/Home.md)
- [Docker and Compose](./development/Docker.md)
- [Continuous Integration](./development/Continuous-Integration.md)
- [Git Hooks and Commit Messages](./development/Git-Hooks.md)
- [Scripts and Experiments](./development/Scripts.md): helper scripts, `data/build_article_list.py`, `experiments/`
