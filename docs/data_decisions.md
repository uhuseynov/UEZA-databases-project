 Data & Dataset Decisions

*Topic and articles
We chose (Artificial Intelligence) on English Wikipedia. The articles link to each
other a lot, are edited often (good for the "edited since" filter and for live sync),
and have many categories, so the hybrid SQL + vector search has real data to work with.

*Selection (262 articles):
- 6 root categories plus one level of subcategories: Machine learning (50), Deep learning
  (50), Natural language processing (50), Philosophy of AI (50), Computer vision (25),
  Reinforcement learning (14).
- 23 core articles added by hand (for example Artificial intelligence, Supervised
  learning, Retrieval-augmented generation), because the root categories missed them.
- Stubs under 3000 characters, "List of..." pages and people/company/fiction
  subcategories were skipped.
- Each root has a cap of 50 so that no category dominates. Computer vision has a cap of 25
  because its subcategories drift into 3D imaging and optics.
- Off-topic articles (products, films, optics, finite-state machines) were removed by hand
  in three rounds. The list is in the `remove` variable of `data/build_article_list.py`.

**Limitations:** the cap favours long, broad articles. Reinforcement learning is small
because the category itself is small. The `category` column in `articles.csv` only holds
the first category found, so the full category list is loaded by the ingest.

*Metadata for SQL filters
To test hybrid search (vector + SQL), we store:
- `category`: own table (many-to-many), so we can JOIN and filter by category
- `outgoing_links`: own table, so we can filter "linked from another article"
- `article_length`
- `last_edit_date`

*Cleaning strategy
Before chunking, we clean the raw Wikipedia text.

Keep: the lead section, body paragraphs and section headings.

Remove:
- Infoboxes (`{{Infobox ...}}`) and tables (`{| ... |}`)
- Sections like `== References ==`, `== External links ==` and `== See also ==`
- Image and file links (`[[File:...]]`, `[[Image:...]]`)
- Leftover HTML markup

Reason: these parts are not running text. They add noise to the embeddings and would
make unrelated chunks look similar.

*Chunking options
We compare three setups. Every chunk starts with the article title, and splits are made at
sentence boundaries.

| Config | Size | Overlap | Reason |
|---|---|---|---|
| A | 256 tokens | 32 | precise matches for small facts |
| B | 512 tokens | 64 | more context per chunk |
| C | paragraph / section, max 512 | 0 | follows the structure of the article |

We do not use 1024 tokens: the embedding models read about 512 tokens, so the rest of
the chunk would be ignored.

*Embedding models to test
| Model | Dimension | Reason |
|---|---|---|
| `BAAI/bge-small-en-v1.5` | 384 | lightweight and fast |
| `BAAI/bge-base-en-v1.5` | 768 | better quality and precision, slower and bigger index |
| `intfloat/e5-base-v2` | 768 | strong baseline for search (needs "query: " / "passage: " prefixes) |

The vector dimension decides the size of the VECTOR column, so the final choice is shared
with the database part. The choice is made from the measured Recall@K and latency.
*Ground-truth set
`data/ground_truth.csv` has 59 questions:
- 35 plain factual questions (one correct article each)
- 17 filter questions (category, length, last edit date, linked from)
- 7 questions with no answer in the corpus, to test the "not found" behaviour
 Q53 was removed because two articles fit it equally well. Q49 to Q51 ("linked
from") must be confirmed with the links table once the ingest has loaded it.