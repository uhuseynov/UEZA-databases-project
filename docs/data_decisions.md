# Topic and articles

We chose Artificial Intelligence on English Wikipedia. The articles link to each other a lot, are edited often (good for the "edited since" filter and for live sync), and have many categories, so the hybrid SQL + vector search has real data to work with.

# Selection (262 articles)

- 6 root categories plus one level of subcategories: Machine learning (50), Deep learning (50), Natural language processing (50), Philosophy of AI (50), Computer vision (25), Reinforcement learning (14).
- 23 core articles added by hand (for example Artificial intelligence, Supervised learning, Retrieval-augmented generation), because the root categories missed them.
- Stubs under 3000 characters, "List of..." pages and people/company/fiction subcategories were skipped.
- Each root has a cap of 50 so that no category dominates. Computer vision has a cap of 25 because its subcategories drift into 3D imaging and optics.
- Off-topic articles (products, films, optics, finite-state machines) were removed by hand in three rounds. The list is in the `remove` variable of `data/build_article_list.py`. The script repeats the method, not the data: it writes a new candidate list to `data/articles.generated.csv` and never touches `data/articles.csv`, the committed research snapshot. A rerun gives a different list, because categories, lengths and edit dates have changed since. How to run it, what it guarantees and how to regenerate safely: [Scripts and Experiments](./development/Scripts.md#building-the-article-list-databuild_article_listpy).

## Limitations

The cap favours long, broad articles. Reinforcement learning is small because the category itself is small. The `category` column in `articles.csv` only holds the first category found, so the full category list is loaded by the ingest.

# Metadata for SQL filters

To test hybrid search (vector + SQL), we store:

- `article_categories`: many-to-many table, so we can JOIN and filter by category.
- `article_links`: table for filtering articles linked from another article.
- `article_length`
- `last_edit_date`

# Cleaning strategy

Before chunking, we clean the raw Wikipedia text.

Keep: the lead section, body paragraphs and section headings.

Remove:

- Infoboxes (`{{Infobox ...}}`) and tables (`{| ... |}`)
- Sections like `== References ==`, `== External links ==` and `== See also ==`
- Image and file links (`[[File:...]]`, `[[Image:...]]`)
- Leftover HTML markup

Reason: these parts are not running text. They add noise to the embeddings and would make unrelated chunks look similar.

# Chunking options

We compare three setups. Every chunk starts with the article title, and splits are made at sentence boundaries.

| Config | Size | Overlap | Reason |
|---|---|---|---|
| A | 256 tokens | 32 | precise matches for small facts |
| B | 512 tokens | 64 | more context per chunk |
| C | paragraph / section, max 512 | 0 | follows the structure of the article |

We do not use 1024 tokens: the embedding models read about 512 tokens, so the rest of the chunk would be ignored.

# Embedding models to test

| Model | Dimension | Reason |
|---|---|---|
| `BAAI/bge-small-en-v1.5` | 384 | lightweight and fast |
| `BAAI/bge-base-en-v1.5` | 768 | better quality and precision, slower and bigger index |
| `intfloat/e5-base-v2` | 768 | strong baseline for search (needs "query: " / "passage: " prefixes) |

The vector dimension decides the size of the VECTOR column, so the final choice fixes the table: another dimension needs a table created for it ([Schema Management](./database/Schema.md)).

## Status

This page records the plan. Chunk configuration A and `BAAI/bge-base-en-v1.5` are what was measured; configurations B and C are implemented in the chunker but were not compared, and the other two models were not tried (each needs a full re-ingest). See the Status section of the [README](../README.md#status).
