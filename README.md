# UZA-Databases-Project

# Wikipedia RAG with MariaDB Vector Search

A project for area 4, "Vector search and RAG, natively" for the [MariaDB student database projects, 2026-09](https://mariadb.org/bachelor_hackathon_2026-09/).

A question-answering system built on Wikipedia articles. Instead of using a separate vector database, everything — the text, the metadata, and the search vectors — lives inside MariaDB, using its native `VECTOR` type.

## Table of Contents

- [What This Does](#what-this-does)
- [Team](#team)
- [Tech Stack](#tech-stack)
- [Setup](#setup)
- [Installing Podman on Windows](#installing-podman-on-windows)
- [Usage](#usage)
- [Database Schema](#database-schema)
- [Status](#status)

## What This Does

1. We take a set of Wikipedia articles and break them into small chunks of text.
2. Each chunk gets turned into a vector (a list of numbers that captures its meaning) using an embedding model.
3. All chunks and vectors are stored in MariaDB.
4. When someone asks a question, we turn the question into a vector too, and ask MariaDB to find the closest matching chunks.
5. We can also filter results with normal SQL at the same time — for example, only search articles in a certain category or after a certain date.
6. The matching chunks are handed to an LLM, which writes an answer based on them.
7. We measure how good the search is using a set of test questions we already know the answers to.

## Team

- **Aaryadeep** — Database setup, table design, vector search, SQL queries
- **Zeynalabidin** — Collecting and preparing the Wikipedia data, generating embeddings
- **Umid** (team lead) — Connecting everything into a working RAG pipeline, testing accuracy

## Tech Stack

- **MariaDB 11.8** — stores the data and does the vector search
- **Podman** — runs MariaDB in a container so setup is the same on every machine
- *(add your embedding model and LLM here once decided)*

## Setup

You need Podman installed. If you're on Windows, see the [Windows section](#installing-podman-on-windows) below first.

Run these commands to start the database:

```bash
podman pull docker.io/library/mariadb:11.8
podman volume create mariadb-data
podman run -d \
  --name mariadb-project \
  -e MARIADB_ROOT_PASSWORD=changeme \
  -e MARIADB_DATABASE=ragdb \
  -p 3306:3306 \
  -v mariadb-data:/var/lib/mysql \
  docker.io/library/mariadb:11.8
```

Or, easier: we included a `Makefile` that does this for you.

```bash
make create   # first time only: sets everything up
make start    # start the database (e.g. after restarting your computer)
make shell    # open a SQL prompt to run queries
make stop     # stop the database when you're done
make help     # see all available commands
```

## Installing Podman on Windows

Podman needs Linux to run containers, so on Windows it runs a small Linux system in the background using WSL2. Here's how to set it up:

```powershell
# 1. Turn on WSL2 (open PowerShell as Administrator)
wsl --install --no-distribution
# Restart your computer when it asks you to

# 2. Install Podman
winget install RedHat.Podman

# 3. Start Podman's background Linux system
podman machine init
podman machine start

# 4. Check that it worked
podman machine list
```

After this, every command in this README works the same on Windows as on Linux or Mac.

## Usage

Once the database is running, connect to it and run queries:

```bash
make shell
```

This opens a prompt where you can run SQL directly, for example:

```sql
SHOW TABLES;
SELECT * FROM articles LIMIT 5;
```

*(more usage instructions will go here once the RAG pipeline is connected)*

## Database Schema

Two tables: one for articles, one for the text chunks and their vectors.

```sql
CREATE TABLE articles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(255),
    category VARCHAR(100),
    url VARCHAR(500),
    edited_at DATE
);

CREATE TABLE article_chunks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    article_id INT,
    chunk_text TEXT,
    embedding VECTOR(768),
    FOREIGN KEY (article_id) REFERENCES articles(id)
);
```

**Why it's split this way:** `articles` holds the basic facts about each article, so we can filter by things like category or date using normal SQL. `article_chunks` holds the actual text pieces and their vectors, linked back to the article they came from. This split is what lets us combine a normal SQL filter and a vector search in one single query, for example:

```sql
SELECT c.id, c.chunk_text, a.title
FROM article_chunks c
JOIN articles a ON c.article_id = a.id
WHERE a.category = 'physics' AND a.edited_at > '2024-01-01'
ORDER BY VEC_DISTANCE_COSINE(c.embedding, @query_vector)
LIMIT 5;
```

We also added a `VECTOR INDEX` on the `embedding` column, so searches stay fast even as the amount of data grows:

```sql
ALTER TABLE article_chunks ADD VECTOR INDEX (embedding);
```

## Status

- [x] MariaDB set up and running, same setup works on every machine
- [x] Tables created
- [ ] Vector size confirmed and finalized
- [ ] Vector index added and tested
- [ ] Real Wikipedia data loaded in
- [ ] Search tested with real questions
- [ ] Connected to the RAG pipeline
- [ ] Accuracy and speed measured
