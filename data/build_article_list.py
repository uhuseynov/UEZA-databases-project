import csv
import time
import requests
URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "UZA-databases-project (zyusifli@constructor.university)"}
roots = [
    "Category:Machine learning",
    "Category:Deep learning",
    "Category:Natural language processing",
    "Category:Computer vision",
    "Category:Reinforcement learning",
    "Category:Philosophy of artificial intelligence",
]
min_length = 3000
max_per_root = 50
bad_starts = ["List of","Outline of","Index of","Timeline of","Glossary of"]
bad_words = ["companies", "researchers","people", "fiction","films", "books"]

#articlechecked by hand and decided are NOT about AI (products,films,
#geometry,optics,finite-state machines,fiction characters,laws)
remove = [
     "Kinect", "Folding@home", "Google Nest", "Aphelion (software)", "Kruskal count",
     "Julia (programming language)", "Stockfish (chess)",
     "The Flash (film)", "The Capture (TV series)", "The Heart Part 5", "Fall (2022 film)",
  "1999 (Charli XCX and Troye Sivan song)", "Kuaishou", "Deepfake pornography",
    "Generative AI pornography", "Grok sexual deepfake scandal",
    "Laws of Form", "Suffix automaton", "UML state machine", "Büchi automaton",
    "Finite-state machine", "Asymmetric numeral systems", "CarPlay", "Verbal overshadowing",
    "Speech repetition", "IBM optical mark and character readers",
    "Automatic number-plate recognition", "ReCAPTCHA", "Ancient text corpora",
    "Hapax legomenon", "Haptik",
    "3D film", "IMAX", "Virtual reality applications", "Closed-circuit television",
      "Traffic enforcement camera", "Red light camera", "3D scanning", "Manifold",
    "Holography", "Color vision", "Color", "Convex hull", "Anaglyph 3D", "Stereoscopy",
    "Lenticular printing", "Charge-coupled device", "Erika Blumenfeld", "Autostereogram",
   "Binocular vision", "Differential geometry", "MATLAB", "Lie algebroid",
   "Depth perception", "3D modeling", "Convolution", "Tensor operator", "Avizo (software)",
   "Augmented reality", "Noise reduction", "CAPTCHA", "Eye tracking", "Mobileye",
             "Robot Operating System", "Medical imaging",
     "Vilém Flusser", "Fanged Noumena", "Skynet (Terminator)", "Émile P. Torres",
     "Sermon on the 'Mount (South Park)", "Lightricks", "TAKE IT DOWN Act", "No Fakes Act",
     "Tagged Deterministic Finite Automaton", "Nondeterministic finite automaton",
  "Deterministic finite automaton", "Trie", "Regular language", "Haskins Laboratories",
  "Physics of optical holography", "Time-of-flight camera", "Opponent process",
  "Amira (software)", "Nonogram", "Discrete Laplace operator", "3D projection",
  "Pixel-art scaling algorithms", "Artec 3D", "4DX", "Stereopsis", "3D display",
  "Active shutter 3D system", "Salience (neuroscience)", "Image editing", "CrysTBox",
  "Image noise", "The Outer Limits (1995 TV series)", "Omega Point",
    "Taylor Swift deepfake pornography controversy", "Open Syllabus Project",
    "Glottochronology", "Voice user interface", "Luciano Floridi",
    "Moral circle expansion",
]

# Important core articles that the six roots dont contain
core = [
    "Artificial intelligence", "Supervised learning", "Unsupervised learning",
    "Recurrent neural network", "Word embedding", "Attention Is All You Need",
     "Retrieval-augmented generation", "Autoencoder", "Decision tree learning",
     "Random forest", "Gradient boosting", "Expert system", "Knowledge graph",
     "Symbolic artificial intelligence", "History of artificial intelligence",
     "Overfitting", "Backpropagation", "Gradient descent", "Transfer learning",
     "Self-supervised learning", "Vector database", "Semantic search",
     "BERT (language model)", "GPT-3", "ChatGPT",
]


def ask(params):
    params["format"] ="json"
    params["formatversion"] =2
    response = requests.get(URL, params=params, headers=HEADERS)
    time.sleep(0.2)
    return response.json()

def get_category(category):
    articles =[]
    subcats =[]
    data = ask({"action": "query", "list": "categorymembers",
                "cmtitle": category, "cmlimit": 500})
    for item in data["query"]["categorymembers"]:
        if item["ns"] == 0:
            articles.append(item["title"])
        if item["ns"] == 14:
            subcats.append(item["title"])
    return articles, subcats

def get_info(titles, follow_redirects=False):
    result ={}
    for i in range(0, len(titles), 50):
        part = titles[i:i + 50]
        params = {"action": "query", "titles": "|".join(part),
                  "prop": "info|revisions", "rvprop": "timestamp"}
        if follow_redirects:
            params["redirects"] = 1
        data = ask(params)
        for page in data["query"]["pages"]:
            if "revisions" not in page:
                print("  not found:", page["title"])
                continue
            result[page["title"]] = (page["pageid"], page["length"],
                                     page["revisions"][0]["timestamp"])
    return result
rows = []
used = []
#the six root category
for root in roots:
    print("Working on", root)
    found ={}

    articles, subcats = get_category(root)
    for a in articles:
        found[a] = root.replace("Category:", "")

    for sub in subcats:
        skip = False
        for word in bad_words:
            if word in sub.lower():
                skip = True
        if skip:
            continue
        sub_articles, other = get_category(sub)
        for a in sub_articles:
            if a not in found:
                found[a] = sub.replace("Category:", "")

    titles =[]
    for t in found:
        if t.startswith(tuple(bad_starts)):
            continue
        if t in remove:     
            continue
        if t in used:
            continue
        titles.append(t)

    info =get_info(titles)

    root_rows =[]
    for t in info:
        pageid, length, last_edit = info[t]
        if t not in found:   
            continue
        if length >= min_length:
            root_rows.append({
                "title": t, "pageid": pageid, "length": length,
                "last_edit": last_edit,
                "root_category": root.replace("Category:", ""),
                "category": found[t],
            })

    root_rows.sort(key=lambda r: r["length"], reverse=True)

    cap = max_per_root
    if root == "Category:Computer vision":
        cap = 25
    root_rows = root_rows[:cap]
    for r in root_rows:
        used.append(r["title"])
        rows.append(r)
    print("  kept", len(root_rows))

#core articles added by hand
print("Adding core articles")
info = get_info(core, follow_redirects=True)
added = 0
for t in info:
    if t in used:
        continue
    pageid, length, last_edit = info[t]
    rows.append({"title": t, "pageid": pageid, "length": length,
                 "last_edit": last_edit,
                 "root_category": "Core", "category": "Core"})
    used.append(t)
    added += 1
print("  added", added)

#save
f = open("data/articles.csv", "w", newline="", encoding="utf-8")
writer = csv.DictWriter(f, fieldnames=["title", "pageid", "length",
                        "last_edit", "root_category", "category"])
writer.writeheader()
writer.writerows(rows)
f.close()

print("Done, saved", len(rows), "articles")