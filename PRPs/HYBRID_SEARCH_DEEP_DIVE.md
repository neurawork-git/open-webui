# Hybrid Search Deep Dive - INITIAL.md

## PROJEKT-KONTEXT

**Overall Project:** Open WebUI RAG Improvements
**This Component:** Understanding hybrid search internals, specifically BM25 keyword scoring
**Goal:** Create diagnostic tests to understand how BM25 scores chunks and how hybrid search combines vector + keyword results

## FUNKTIONALE ANFORDERUNGEN

### Primary Investigation Questions

1. **BM25 Scoring Mechanics**
   - How does BM25 score a German statistical table chunk for query "Bevölkerung Leipzig"?
   - What are the term frequencies (TF) and inverse document frequencies (IDF)?
   - How does document length normalization affect the score?

2. **Test Case**
   - **Query:** "Bevölkerung Leipzig"
   - **Chunk:** German city statistics table with population data
   - **Expected matches:** "Bevölkerung" in header, "Leipzig" in row 8

3. **Deliverables**
   - Standalone test script showing BM25 score calculation
   - Breakdown of score components (TF, IDF, length normalization)
   - Comparison with vector similarity score for same query/chunk

## TEST CHUNK

```
| Gebietsstand: 31.12.2023 | | | | | |
| Lfd. Nr. | Schlüsselnummer | | | Stadt | Post-leitzahl 1) | Fläche in km2 2) | Bevölkerung auf Grundlage ZENSUS20113) | | |
| | Land | RB | Kreis | Verb | Gem | | insgesamt | männlich | weiblich | je km2 | |
| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | |
| 1 | 11 | 0 | 00 | 0000 | 000 | Berlin, Stadt | 10178 | 891.12 | 3782202 | 1860115 | 1922087 | 4244 | |
| 2 | 02 | 0 | 00 | 0000 | 000 | Hamburg, Freie und Hansestadt | 20038 | 755.09 | 1910160 | 936740 | 973420 | 2530 | |
| 3 | 09 | 1 | 62 | 0000 | 000 | München, Landeshauptstadt | 80313 | 310.7 | 1510378 | 734925 | 775453 | 4861 | |
| 4 | 05 | 3 | 15 | 0000 | 000 | Köln, Stadt | 50667 | 405.02 | 1087353 | 527728 | 559625 | 2685 | |
| 5 | 06 | 4 | 12 | 0000 | 000 | Frankfurt am Main, Stadt | 60311 | 248.31 | 775790 | 382226 | 393564 | 3124 | |
| 6 | 08 | 1 | 11 | 0000 | 000 | Stuttgart, Landeshauptstadt | 70173 | 207.33 | 633484 | 316030 | 317454 | 3055 | |
| 7 | 05 | 1 | 11 | 0000 | 000 | Düsseldorf, Stadt | 40213 | 217.41 | 631217 | 304616 | 326601 | 2903 | |
| 8 | 14 | 7 | 13 | 0000 | 000 | Leipzig, Stadt | 04109 | 297.8 | 619879 | 305443 | 314436 | 2082 | |
| 9 | 05 | 9 | 13 | 0000 | 000 | Dortmund, Stadt | 44135 | 280.71 | 595471 | 292178 | 303293 | 2121 | |
| 10 | 05 | 1 | 13 | 0000 | 000 | Essen, Stadt | 45121 | 210.34 | 586608 | 285411 | 301197 | 2789 | |
| 11 | 04 | 0 | 11 | 0000 | 000 | Bremen, Stadt | 28195 | 318.2 | 577026 | 285270 | 291756 | 1813 | |
| 12 | 14 | 6 | 12 | 0000 | 000 | Dresden, Stadt | 01067 | 328.48 | 566222 | 281215 | 285007 | 1724 | |
| 13 | 03 | 2 | 41 | 0001 | 001 | Hannover, Landeshauptstadt | 30159 | 204.3 | 548186 | 268214 | 279972 | 2683 | |
| 14 | 09 | 5 | 64 | 0000 | 000 | Nürnberg | 90403 | 186.44 | 526091 | 257320 | 268771 | 2822 | |
| 15 | 05 | 1 | 12 | 0000 | 000 | Duisburg, Stadt | 47051 | 232.84 | 503707 | 249120 | 254587 | 2163 | |
| 16 | 05 | 9 | 11 | 0000 | 000 | Bochum, Stadt | 44787 | 145.66 | 366385 | 178896 | 187489 | 2515 | |
| 17 | 05 | 1 | 24 | 0000 | 000 | Wuppertal, Stadt | 42275 | 168.39 | 358938 | 176056 | 182882 | 2132 | |
| 18 | 05 | 7 | 11 | 0000 | 000 | Bielefeld, Stadt | 33602 | 258.83 | 338410 | 163288 | 175122 | 1307 | |
| 19 | 05 | 3 | 14 | 0000 | 000 | Bonn, Stadt | 53111 | 141.06 | 335789 | 160546 | 175243 | 2380 | |
| 20 | 05 | 5 | 15 | 0000 | 000 | Münster, Stadt | 48143 | 303.28 | 322904 | 155052 | 167852 | 1065 | |
| 21 | 08 | 2 | 22 | 0000 | 000 | Mannheim, Universitätsstadt | 68159 | 144.97 | 316877 | 158281 | 158596 | 2186 | |
```

## TECHNOLOGIE-STACK

- **BM25 Implementation:** `rank_bm25` library (used by Open WebUI)
- **Vector Search:** ChromaDB with sentence-transformers embeddings
- **Hybrid Combination:** Reciprocal Rank Fusion (RRF) or weighted combination

## INVESTIGATION TASKS

1. **Locate BM25 implementation** in Open WebUI codebase
2. **Create standalone test** that:
   - Indexes the test chunk
   - Queries with "Bevölkerung Leipzig"
   - Shows raw BM25 score and components
3. **Document findings** on how hybrid search weights are applied

## ABHÄNGIGKEITEN

- Understanding of `retrieval/utils.py` hybrid search logic
- Access to `rank_bm25` library internals

## RESSOURCEN

- Single developer investigation
- ~2-4 hours estimated

## RISIKEN

- BM25 implementation may be abstracted away
- Score normalization may obscure raw values
