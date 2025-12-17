"""
Hybrid Search Deep Dive Test

This test investigates how BM25 scoring works internally for the German city statistics table.
Query: "Bevölkerung Leipzig"
"""

import math
from rank_bm25 import BM25Okapi
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document


# The test chunk - German city statistics table
TEST_CHUNK = """| Gebietsstand: 31.12.2023 | | | | | |
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
| 21 | 08 | 2 | 22 | 0000 | 000 | Mannheim, Universitätsstadt | 68159 | 144.97 | 316877 | 158281 | 158596 | 2186 | |"""

# Additional test documents to see relative scoring
OTHER_CHUNKS = [
    "Berlin ist die Hauptstadt von Deutschland mit über 3 Millionen Einwohnern.",
    "Die Bevölkerung von Deutschland beträgt etwa 83 Millionen Menschen.",
    "Leipzig ist eine Stadt in Sachsen mit einer reichen kulturellen Geschichte.",
    "München hat die höchste Bevölkerungsdichte aller deutschen Großstädte.",
]

QUERY = "Bevölkerung Leipzig"


def test_bm25_raw_scoring():
    """Test raw BM25 scoring using rank_bm25 directly."""
    print("\n" + "=" * 80)
    print("TEST 1: Raw BM25 Scoring (rank_bm25 library)")
    print("=" * 80)

    # Combine all documents
    all_docs = [TEST_CHUNK] + OTHER_CHUNKS
    doc_labels = ["German Stats Table", "Berlin Capital", "Germany Population", "Leipzig Culture", "Munich Density"]

    # Tokenize documents (simple whitespace tokenization)
    tokenized_docs = [doc.lower().split() for doc in all_docs]

    # Create BM25 index
    bm25 = BM25Okapi(tokenized_docs)

    # Tokenize query
    query_tokens = QUERY.lower().split()
    print(f"\nQuery: '{QUERY}'")
    print(f"Query tokens: {query_tokens}")

    # Get scores for all documents
    scores = bm25.get_scores(query_tokens)

    print(f"\n{'Document':<25} {'BM25 Score':>12}")
    print("-" * 40)
    for i, (label, score) in enumerate(zip(doc_labels, scores)):
        print(f"{label:<25} {score:>12.4f}")

    # Show top-k retrieval
    print("\n--- Top-k Retrieval ---")
    top_k = bm25.get_top_n(query_tokens, all_docs, n=3)
    for i, doc in enumerate(top_k):
        print(f"\nRank {i + 1}:")
        print(f"  Preview: {doc[:100]}...")

    return scores[0]  # Return score for main test chunk


def test_bm25_score_breakdown():
    """Break down BM25 score components for the test chunk."""
    print("\n" + "=" * 80)
    print("TEST 2: BM25 Score Breakdown for Test Chunk")
    print("=" * 80)

    # Single document analysis
    doc = TEST_CHUNK.lower()
    tokens = doc.split()

    print(f"\nDocument Statistics:")
    print(f"  Total tokens: {len(tokens)}")
    print(f"  Unique tokens: {len(set(tokens))}")

    query_tokens = QUERY.lower().split()

    print(f"\nQuery Term Analysis:")
    for term in query_tokens:
        count = tokens.count(term)
        positions = [i for i, t in enumerate(tokens) if t == term]
        print(f"\n  Term: '{term}'")
        print(f"    Frequency in document: {count}")
        if positions:
            print(f"    Positions: {positions[:10]}{'...' if len(positions) > 10 else ''}")

            # Show context around first occurrence
            if positions:
                pos = positions[0]
                start = max(0, pos - 3)
                end = min(len(tokens), pos + 4)
                context = tokens[start:end]
                print(f"    Context: ...{' '.join(context)}...")

    # BM25 Okapi formula components
    print("\n--- BM25 Okapi Formula ---")
    print("score(D, Q) = SUM IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))")
    print("\nWhere:")
    print("  f(qi, D) = frequency of term qi in document D")
    print("  |D| = document length")
    print("  avgdl = average document length in corpus")
    print("  k1 = 1.5 (default), controls term frequency saturation")
    print("  b = 0.75 (default), controls length normalization")

    # Calculate components manually for single doc
    k1 = 1.5
    b = 0.75
    doc_len = len(tokens)
    avgdl = doc_len  # Only one doc, so avgdl = doc_len

    print(f"\nFor this document:")
    print(f"  |D| = {doc_len}")
    print(f"  avgdl = {avgdl}")
    print(f"  k1 = {k1}, b = {b}")

    for term in query_tokens:
        tf = tokens.count(term)
        # IDF for single document corpus is 0 if term exists, undefined otherwise
        # With multiple docs: IDF = log((N - n + 0.5) / (n + 0.5))
        if tf > 0:
            # Simplified score component
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_len / avgdl)
            score_component = numerator / denominator
            print(f"\n  Term '{term}':")
            print(f"    TF = {tf}")
            print(f"    Score component (without IDF) = {score_component:.4f}")


def test_langchain_bm25_retriever():
    """Test LangChain BM25Retriever (what Open WebUI uses)."""
    print("\n" + "=" * 80)
    print("TEST 3: LangChain BM25Retriever (Open WebUI Implementation)")
    print("=" * 80)

    # Create documents with metadata
    all_docs = [TEST_CHUNK] + OTHER_CHUNKS
    doc_labels = ["German Stats Table", "Berlin Capital", "Germany Population", "Leipzig Culture", "Munich Density"]

    documents = [
        Document(page_content=doc, metadata={"label": label, "source": f"doc_{i}"})
        for i, (doc, label) in enumerate(zip(all_docs, doc_labels))
    ]

    # Create BM25 retriever (same as Open WebUI)
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = 5  # Get all docs

    print(f"\nQuery: '{QUERY}'")
    print("\n--- Retrieved Documents (ranked by BM25) ---")

    results = retriever.invoke(QUERY)
    for i, doc in enumerate(results):
        label = doc.metadata.get("label", "Unknown")
        preview = doc.page_content[:80].replace("\n", " ")
        print(f"\nRank {i + 1}: {label}")
        print(f"  Preview: {preview}...")


def test_term_presence_analysis():
    """Analyze term presence in the test chunk."""
    print("\n" + "=" * 80)
    print("TEST 4: Term Presence Analysis")
    print("=" * 80)

    doc = TEST_CHUNK
    query_terms = ["bevölkerung", "leipzig"]

    for term in query_terms:
        print(f"\n--- Searching for '{term}' ---")

        # Case-insensitive search
        lower_doc = doc.lower()
        lower_term = term.lower()

        # Find all occurrences
        start = 0
        positions = []
        while True:
            pos = lower_doc.find(lower_term, start)
            if pos == -1:
                break
            positions.append(pos)
            start = pos + 1

        print(f"Found {len(positions)} occurrence(s)")

        # Show context for each occurrence
        for i, pos in enumerate(positions):
            # Extract context (50 chars before and after)
            context_start = max(0, pos - 50)
            context_end = min(len(doc), pos + len(term) + 50)
            context = doc[context_start:context_end].replace("\n", " ")

            # Highlight the term
            term_start = pos - context_start
            term_end = term_start + len(term)
            highlighted = (
                context[:term_start]
                + ">>>"
                + context[term_start:term_end]
                + "<<<"
                + context[term_end:]
            )
            print(f"\n  Occurrence {i + 1} at position {pos}:")
            print(f"    ...{highlighted}...")


def test_tokenization_comparison():
    """Compare different tokenization strategies."""
    print("\n" + "=" * 80)
    print("TEST 5: Tokenization Strategy Comparison")
    print("=" * 80)

    doc = TEST_CHUNK

    # Strategy 1: Simple whitespace split
    tokens_whitespace = doc.lower().split()
    print(f"\n1. Whitespace tokenization: {len(tokens_whitespace)} tokens")

    # Strategy 2: Word-based (alphanumeric only)
    import re

    tokens_word = re.findall(r"\b\w+\b", doc.lower())
    print(f"2. Word tokenization (\\w+): {len(tokens_word)} tokens")

    # Check for query terms in each
    query_terms = ["bevölkerung", "leipzig"]
    print("\nQuery term presence:")
    for term in query_terms:
        ws_count = tokens_whitespace.count(term)
        word_count = tokens_word.count(term)
        print(f"  '{term}': whitespace={ws_count}, word={word_count}")

    # The issue: "Bevölkerung" might be part of a larger token
    print("\n--- Tokens containing 'bevölkerung' ---")
    for token in set(tokens_whitespace):
        if "bevölkerung" in token:
            print(f"  '{token}'")

    print("\n--- Tokens containing 'leipzig' ---")
    for token in set(tokens_whitespace):
        if "leipzig" in token:
            print(f"  '{token}'")


def test_bm25_with_multiple_chunks():
    """Test BM25 with realistic chunked documents."""
    print("\n" + "=" * 80)
    print("TEST 6: BM25 Scoring with Multiple Chunks")
    print("=" * 80)

    # Simulate a corpus with multiple chunks
    chunks = [
        TEST_CHUNK,  # Main statistics table
        "Die Bevölkerung Deutschlands wächst langsam. Im Jahr 2023 lebten 84 Millionen Menschen in Deutschland.",
        "Leipzig hat eine Bevölkerung von etwa 620.000 Einwohnern und ist damit die größte Stadt in Sachsen.",
        "Berlin ist mit 3,7 Millionen Einwohnern die bevölkerungsreichste Stadt Deutschlands.",
        "München, Frankfurt und Hamburg folgen auf den Plätzen zwei bis vier der Bevölkerungsstatistik.",
    ]
    chunk_labels = [
        "Stats Table (contains both terms)",
        "Germany Population (Bevölkerung only)",
        "Leipzig Focus (both terms, specific)",
        "Berlin Population (Bevölkerung only)",
        "Top Cities (Bevölkerungsstatistik)",
    ]

    # Tokenize
    tokenized_chunks = [chunk.lower().split() for chunk in chunks]
    bm25 = BM25Okapi(tokenized_chunks)

    query_tokens = QUERY.lower().split()
    scores = bm25.get_scores(query_tokens)

    print(f"\nQuery: '{QUERY}'")
    print(f"\n{'Chunk':<45} {'Score':>10}")
    print("-" * 60)

    # Sort by score
    scored_chunks = sorted(zip(chunk_labels, scores, chunks), key=lambda x: x[1], reverse=True)
    for label, score, chunk in scored_chunks:
        print(f"{label:<45} {score:>10.4f}")


def run_all_tests():
    """Run all hybrid search investigation tests."""
    print("\n" + "#" * 80)
    print("# HYBRID SEARCH DEEP DIVE - BM25 Investigation")
    print(f"# Query: '{QUERY}'")
    print("#" * 80)

    test_term_presence_analysis()
    test_tokenization_comparison()
    test_bm25_raw_scoring()
    test_bm25_score_breakdown()
    test_langchain_bm25_retriever()
    test_bm25_with_multiple_chunks()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("""
Key Findings:
1. BM25 uses simple tokenization (whitespace or word-based)
2. German compound words might not be properly handled
3. The score depends on:
   - Term Frequency (TF): How often each query term appears
   - Inverse Document Frequency (IDF): How rare the term is across corpus
   - Document Length Normalization: Longer docs are slightly penalized

For query "Bevölkerung Leipzig":
- "Bevölkerung" appears in the header row
- "Leipzig" appears in the data row 8
- Both terms are relatively rare, giving high IDF
- The table is long, which slightly reduces the score

The actual BM25 score depends on the corpus composition!
""")


if __name__ == "__main__":
    run_all_tests()
