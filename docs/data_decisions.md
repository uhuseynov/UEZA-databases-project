Data & Dataset Decisions

*Topic & Articles
We chose the **Artificial Intelligence** category from Wikipedia (around 300 articles). It gives us good inter-connected articles with rich metadata like dates, lengths, and links.

*Metadata for SQL Filters
To test hybrid search (Vector + SQL), we extract:
- `category`
- `article_length`
- `last_edit_date`
- `outgoing_links`

*Cleaning Strategy
Before chunking, we need to clean the raw Wikipedia text:
-Remove Infoboxes (`{{Infobox ...}}`) and Tables (`{| ... |}`)
-Remove sections like `== References ==`, `== External links ==`, and `== See also ==`
-Remove image and file links (`[[File:...]]`, `[[Image:...]]`)
-Clean up remaining HTML markup

*Chunking Options
We will compare a few chunking setups:
1. 512 tokens with 64 overlap (good for small facts)
2.1024 tokens with 128 overlap (good for bigger context)
3.Paragraph / Section-based splits (`\n\n`, `==`)

*Embedding Models to Test
-`BAAI/bge-small-en-v1.5` (384-dim) - Lightweight and fast
- `BAAI/bge-base-en-v1.5` (768-dim) - Better quality/precision
- `intfloat/e5-base-v2` (768-dim) - Strong baseline for search