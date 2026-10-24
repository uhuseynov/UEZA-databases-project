import csv
import pathlib
import random
import sys

import numpy as np

csv_path = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

DIM = 768        # must match VECTOR(768) in schema.sql
STRIDE = 850     # chunk size 1000 with overlap 150 (.env.example) -> new chunk every 850 characters
rng = np.random.default_rng(42)
random.seed(42)


def q(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


# 1. Real article metadata from data/articles.csv (one row per article and category).
articles: dict[int, dict] = {}
with open(csv_path, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        page_id = int(row["pageid"])
        article = articles.setdefault(page_id, {
            "title": row["title"],
            "length": int(row["length"]),
            "last_edit": row["last_edit"].replace("T", " ").rstrip("Z"),
            "root": row["root_category"],
            "categories": [],
        })
        if row["category"] not in article["categories"]:
            article["categories"].append(row["category"])

items = list(articles.items())
titles = [a["title"] for _, a in items]

# 2. SQL for articles, categories and links.
sql = ["SET NAMES utf8mb4;"]

rows = []
for i, (page_id, a) in enumerate(items, start=1):
    url = "https://en.wikipedia.org/wiki/" + a["title"].replace(" ", "_")
    rows.append(f"({i},{page_id},{q(a['title'])},{q(url)},{q(a['root'])},{a['length']},{page_id * 10},{q(a['last_edit'])})")
for start in range(0, len(rows), 200):
    sql.append("INSERT INTO articles (id,page_id,title,url,root_category,article_length,revision_id,last_edit_date) VALUES\n"
               + ",\n".join(rows[start:start + 200]) + ";")

rows = [f"({i},{q(c)})" for i, (_, a) in enumerate(items, start=1) for c in a["categories"]]
for start in range(0, len(rows), 500):
    sql.append("INSERT INTO article_categories (article_id,category) VALUES\n" + ",\n".join(rows[start:start + 500]) + ";")

rows = []
for i, (_, a) in enumerate(items, start=1):
    others = [t for t in titles if t != a["title"]]
    linked = random.sample(others, min(15, len(others))) + [f"Outside article {i}-{k}" for k in range(5)]
    rows += [f"({i},{q(t)})" for t in linked]
for start in range(0, len(rows), 500):
    sql.append("INSERT INTO article_links (article_id,linked_title) VALUES\n" + ",\n".join(rows[start:start + 500]) + ";")

(out / "load-meta.sql").write_text("\n".join(sql) + "\n", encoding="utf-8")

# 3. Chunks with generated vectors: root group centre + article centre + noise,
#    so chunks of one article and articles of one group are closer to each other.
root_centres = {}
total = 0
with open(out / "chunks.tsv", "w", encoding="utf-8") as f:
    for i, (_, a) in enumerate(items, start=1):
        centre = root_centres.setdefault(a["root"], rng.normal(size=DIM)) + rng.normal(size=DIM) * 0.7
        n = max(1, round(a["length"] / STRIDE))
        vectors = centre + rng.normal(size=(n, DIM)) * 0.6
        safe_title = a["title"].replace("\\", "").replace("\t", " ")
        for j in range(n):
            vec = ",".join(f"{x:.3f}" for x in vectors[j])
            f.write(f"{i}\t{j}\tSynthetic chunk {j + 1} of {safe_title}\t[{vec}]\n")
        total += n

print(f"articles: {len(items)}")
print(f"categories: {sum(len(a['categories']) for _, a in items)}")
print(f"chunks: {total}")
