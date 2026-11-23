# Results

[← Evaluation](./Home.md) | [Documentation Home](../Home.md)

The measured results of the project, from `make eval` and the `python -m src.evaluation` commands. The method, the metrics and the commands are in [Evaluation](./Home.md); the raw reports behind these numbers are listed in the [eval/results index](../../eval/results/README.md).

Measured on 30 October 2026 on our laptop (Windows 11, 12 logical CPUs, Docker Desktop) with MariaDB 12.3.3, the embedding model `BAAI/bge-base-en-v1.5` (768 dimensions), chunks of 256 tokens with 32 tokens overlap, `M=16`, `mhnsw_ef_search` 40 and a 64 MB index cache. The corpus is all 262 articles, 6,144 chunks. The questions are [data/ground_truth.csv](../../data/ground_truth.csv): 71 questions, 43 plain, 17 with SQL filters and 11 whose answer is not in the articles. The run embeds all questions first, discards one warm-up pass and then times 5 passes. It was taken after a restart of the database, the state a running service is in.

Raw output: the [run](../../eval/results/20261030-204715_final.md), the [`mhnsw_ef_search` sweep](../../eval/results/20261030-204644_final-ef-sweep.md), the [M sweep](../../eval/results/20261030-203723_m-sweep.md) and the [query plans](../../eval/results/20261030-195010_explain.md), with a JSON file next to each run that holds every question.

## Retrieval quality

Recall@k is the share of answerable questions where a chunk of a correct article is among the k closest chunks. MRR is the mean of 1 / rank of the first correct chunk.

| Questions | n | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| all answerable | 60 | 0.617 | 0.800 | 0.867 | 0.950 | 0.733 |
| plain | 43 | 0.605 | 0.837 | 0.907 | 0.977 | 0.744 |
| with filters | 17 | 0.647 | 0.706 | 0.765 | 0.882 | 0.703 |

These are exactly the numbers of the exact search over every chunk ([full scan](../../eval/results/20261030-195546_exact-binary.md)): the 5% of nearest chunks the index misses did not cost a correct article. Three questions miss at k = 10. Two of them are filtered (the ImageNet question behind "linked from Convolutional neural network" and the PCA question behind "Machine learning, longer than 100,000 characters"); for the third, the chunks of "Large language model" outrank the article "Hallucination (artificial intelligence)". When the right article is not first, the first result is usually a closely related article: SARSA for the Q-learning question, "Google DeepMind" for AlphaGo, "Decision tree learning" for the random forest question and "Cluster analysis" for k-means.

## Latency

Time of the MariaDB statement alone, in milliseconds, measured from Python (the question is embedded beforehand: 35 ms per question, in one batch).

| Questions | searches | mean | p50 | p95 |
| --- | --- | --- | --- | --- |
| plain | 270 | 8.4 | 7.4 | 11.7 |
| with filters | 85 | 11.8 | 9.6 | 24.4 |
| all | 355 | 9.2 | 7.7 | 19.6 |

The five timed passes averaged 8.5, 10.2, 8.6, 9.3 and 9.3 ms. The exact full scan took 19.3 ms per plain question. Inside MariaDB a plain search takes well under a millisecond (0.3 ms for one search under `ANALYZE`); most of the 8 ms is the round trip through the driver and Docker Desktop.

A filtered search never uses the vector index: MariaDB reads the chunks of the matching articles and computes every distance, so it is exact. Every filter in the ground truth averaged 8 to 21 ms; the slowest is "linked from Artificial intelligence", which covers 141 of the 262 articles.

The same questions on 28 October, before the changes described below, took 9.2 ms without a filter, but the index then returned only 92 to 94% of the exact top 10, and 68 ms with filters (p95 280 ms, "linked from" up to 297 ms).

## Not found

The distance of the closest chunk is 0.298 on average for the answerable questions (highest 0.461) and 0.438 for the unanswerable ones (lowest 0.309). With `RAG_MAX_DISTANCE=0.42`, 97% of the answerable questions keep their context and 8 of the 11 unanswerable ones are rejected before the language model is called. All seven football and tennis questions are rejected (0.437 to 0.536), and so is the AIBO question (0.439). Three questions about AI whose answer is not in the articles pass: Leela Chess Zero (0.309, closest article AlphaGo), PROSPECTOR (0.357, Expert system) and Xiaoice (0.389, History of artificial intelligence).

So the threshold filters out questions that are off topic, not questions that are close to the corpus. A lower threshold does not fix that: 0.356 rejects 10 of the 11, but it also takes the context away from 12% of the answerable questions. Those questions are left to the second check, the model answering `NOT_FOUND` when the passages do not contain the answer, measured below.

## Answers with the language model

All 71 questions through the same code as `POST /ask`, with `qwen2.5:3b` in Ollama on the laptop's CPU and the top 5 chunks, on 6 November ([report](../../eval/results/20261106-183004_answers.md)):

| Questions | n | answered | of those citing a correct article | `NOT_FOUND` | rejected by distance |
| --- | --- | --- | --- | --- | --- |
| answerable | 60 | 40 | 31 | 18 | 2 |
| unanswerable | 11 | 0 | – | 3 | 8 |

The model answered `NOT_FOUND` for the three unanswerable questions that pass the threshold, so together the two checks let no unanswerable question through. But it also refused 18 answerable questions, 14 of them with a chunk of the correct article among its 5 passages. Of its 40 answers, one was wrong ("AlphaFold" for Dendral) and two were only a citation. A 3-billion-parameter model on a CPU (33.5 s per answer at the median) is too cautious for this prompt; a larger model is the next thing to try. Details: [Evaluation](Home.md#answers-with-the-language-model).

## Live sync

`sync` asks MediaWiki for the latest revision of every stored article, 50 per request and without the text, and loads only the changed articles again, each in one transaction ([Ingestion](../ingestion/Home.md#live-sync)). On 6 November, 184 of the 262 articles had a newer revision than the snapshot; the check took 2.7 s. Syncing 5 of them replaced 300 chunks in 132 s, 26 s per article for fetching and embedding on the CPU. The evaluation stays on the snapshot, because the questions with an edit-date filter were written for its dates.
