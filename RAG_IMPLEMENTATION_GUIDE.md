# RAG Implementation Quick Start Guide for Open WebUI

A practical, code-ready guide to implementing the research recommendations from the RAG Research Report.

---

## Quick Start: 30-Minute Setup

### Step 1: Configure ChromaDB (5 minutes)

```python
# backend/chromadb_config.py
import chromadb
from chromadb.config import Settings

def get_chroma_client():
    """Create ChromaDB client with optimal configuration"""
    return chromadb.HttpClient(
        host="localhost",
        port=8000,
        settings=Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory="/data/chroma",
            anonymized_telemetry=False
        )
    )

def create_or_get_collection(client, collection_name="documents"):
    """Create collection with cosine distance (CRITICAL)"""
    return client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space": "cosine",  # CRITICAL: Use cosine, not L2
            "hnsw:M": 16,
            "hnsw:ef_construction": 200,
        }
    )
```

### Step 2: Configure Embeddings (5 minutes)

```python
# backend/embedding_config.py
from langchain.embeddings import HuggingFaceEmbeddings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

def get_embeddings():
    """Get embeddings with proper normalization"""
    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cuda"},
        encode_kwargs={"normalize_embeddings": True}  # CRITICAL
    )

def get_chroma_embeddings():
    """Get embeddings for ChromaDB"""
    return SentenceTransformerEmbeddingFunction(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        normalize_embeddings=True  # CRITICAL
    )
```

### Step 3: Create RAG Retriever (10 minutes)

```python
# backend/rag_retriever.py
from langchain_chroma import Chroma
from langchain.embeddings import HuggingFaceEmbeddings

class RAGRetriever:
    """Production-ready RAG retriever"""

    def __init__(self, collection_name="documents"):
        self.embedding = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            encode_kwargs={"normalize_embeddings": True}
        )

        self.vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding,
            persist_directory="/data/chroma"
        )

    def retrieve(
        self,
        query: str,
        k: int = 5,
        relevance_threshold: float = 0.5,
        filter_metadata: dict = None
    ) -> list[tuple]:
        """
        Retrieve relevant documents with filtering

        Returns: List of (document, similarity_score) tuples
        """

        # Search with optional metadata filter
        results = self.vectorstore.similarity_search_with_score(
            query=query,
            k=k * 2,  # Retrieve more, filter later
            filter=filter_metadata
        )

        # Filter by relevance threshold
        # Note: ChromaDB returns distance, not similarity
        # With cosine distance: similarity = 1 - distance
        relevant = [
            (doc, 1 - score)  # Convert distance to similarity
            for doc, score in results
            if (1 - score) >= relevance_threshold
        ]

        return relevant

    def format_context(self, documents: list) -> str:
        """Format documents for LLM context injection"""
        formatted = []
        for i, (doc, similarity) in enumerate(documents, 1):
            formatted.append(
                f"[{i}] (Relevance: {similarity:.1%}) "
                f"Source: {doc.metadata.get('source', 'Unknown')}\n"
                f"{doc.page_content}"
            )
        return "\n\n---\n\n".join(formatted)
```

### Step 4: Create FastAPI Endpoint (10 minutes)

```python
# backend/routes/rag.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from rag_retriever import RAGRetriever

router = APIRouter(prefix="/api/rag", tags=["rag"])
retriever = RAGRetriever()

class RAGQuery(BaseModel):
    query: str
    k: int = 5
    relevance_threshold: float = 0.5

class RAGResponse(BaseModel):
    query: str
    context: str
    sources: list[dict]
    token_estimate: int

@router.post("/retrieve")
async def retrieve_context(request: RAGQuery) -> RAGResponse:
    """Retrieve relevant documents for RAG"""

    try:
        # Retrieve documents
        documents = retriever.retrieve(
            query=request.query,
            k=request.k,
            relevance_threshold=request.relevance_threshold
        )

        if not documents:
            raise HTTPException(
                status_code=404,
                detail="No relevant documents found"
            )

        # Format context for LLM
        context = retriever.format_context(documents)

        # Estimate tokens (roughly 4 chars = 1 token)
        token_estimate = len(context) // 4

        # Return response
        return RAGResponse(
            query=request.query,
            context=context,
            sources=[
                {
                    "source": doc.metadata.get("source"),
                    "relevance": float(sim)
                }
                for doc, sim in documents
            ],
            token_estimate=token_estimate
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## Configuration by Document Type

### For Text Documents (Emails, Articles, Books)

```python
from langchain.text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

# Optimal for text: 1000 char chunks, 200 char overlap
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", " ", ""]
)

# Load and split documents
from langchain.document_loaders import TextLoader
loader = TextLoader("document.txt")
documents = loader.load()
chunks = text_splitter.split_documents(documents)

# Add to vector store
vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embedding,
    collection_metadata={"hnsw:space": "cosine"},
    persist_directory="/data/chroma"
)
```

### For Code Files

```python
# Code often has semantic structure (functions, classes)
# Use smaller chunks to preserve boundaries
code_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,      # Smaller for code
    chunk_overlap=100,
    separators=["\n\nclass ", "\n\ndef ", "\n\n", "\n", " ", ""]
)

# Use specialized language-aware loaders
from langchain.document_loaders.generic import GenericLoader
from langchain.document_loaders.parsers import LanguageParser

loader = GenericLoader.from_filesystem(
    "src/",
    glob="**/*.py",
    parser=LanguageParser(language="python")
)
documents = loader.load()
chunks = code_splitter.split_documents(documents)
```

### For PDFs

```python
from langchain.document_loaders import PyPDFLoader

loader = PyPDFLoader("document.pdf")
documents = loader.load()

# PDFs often have table boundaries
pdf_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,  # Larger for structured PDFs
    chunk_overlap=300,
    separators=["\n\n", "\n", " ", ""]
)

chunks = pdf_splitter.split_documents(documents)

# Important: Preserve page metadata
for i, chunk in enumerate(chunks):
    chunk.metadata["chunk_id"] = i
```

### For Mixed Content (Web, Markdown, etc.)

```python
# Use the standard RecursiveCharacterTextSplitter
mixed_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", " ", ""]  # Default, works well
)

# Add source metadata
for doc in documents:
    doc.metadata["indexed_at"] = datetime.now().isoformat()
    doc.metadata["source"] = doc.metadata.get("source", "unknown")
```

---

## Advanced: Dynamic Context Windowing

```python
# backend/context_manager.py
from typing import Optional
from langchain.schema import Document

class ContextWindowManager:
    """Manage context to respect token limits"""

    # Typical token budgets for different models
    TOKEN_BUDGETS = {
        "gpt-3.5-turbo": 4096,
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
    }

    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        self.budget = self.TOKEN_BUDGETS.get(model_name, 4096)
        self.reserved_tokens = 1500  # For response + overhead

    def available_context_tokens(self) -> int:
        """Get available tokens for context"""
        return self.budget - self.reserved_tokens

    def estimate_query_complexity(self, query: str) -> str:
        """Estimate query complexity"""
        word_count = len(query.split())
        question_count = query.count("?")

        if question_count > 2 or word_count > 50:
            return "complex"
        elif question_count > 1 or word_count > 20:
            return "medium"
        else:
            return "simple"

    def get_optimal_k(self, query: str) -> int:
        """Get optimal number of chunks to retrieve"""
        complexity = self.estimate_query_complexity(query)
        available = self.available_context_tokens()

        # Average tokens per chunk
        tokens_per_chunk = 250

        # Determine k based on complexity
        k_suggestions = {
            "simple": 3,      # ~750 tokens
            "medium": 6,      # ~1500 tokens
            "complex": 10     # ~2500 tokens
        }

        k = k_suggestions.get(complexity, 5)

        # Verify we have room
        if k * tokens_per_chunk > available:
            k = max(1, available // tokens_per_chunk)

        return k

    def truncate_context(
        self,
        documents: list[Document]
    ) -> list[Document]:
        """Truncate documents to fit token budget"""

        total_tokens = 0
        available = self.available_context_tokens()
        truncated = []

        for doc in documents:
            doc_tokens = len(doc.page_content) // 4

            if total_tokens + doc_tokens <= available:
                truncated.append(doc)
                total_tokens += doc_tokens
            else:
                # Truncate last doc
                remaining_chars = (available - total_tokens) * 4
                if remaining_chars > 100:
                    doc.page_content = doc.page_content[:remaining_chars]
                    truncated.append(doc)
                break

        return truncated
```

Usage:
```python
manager = ContextWindowManager(model_name="gpt-3.5-turbo")

# Determine how many chunks to retrieve
k = manager.get_optimal_k(user_query)
documents = retriever.retrieve(query=user_query, k=k)

# Ensure we don't exceed token limits
documents = manager.truncate_context(documents)
```

---

## Advanced: Two-Stage Retrieval (For Large Documents)

```python
# backend/two_stage_retriever.py
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain.storage import InMemoryStore

class TwoStageRetriever:
    """Two-stage retrieval: summaries for search, full docs for context"""

    def __init__(self, llm, documents):
        self.llm = llm
        self.documents = documents
        self.store = InMemoryStore()

    def create_summaries(self):
        """Create summaries for each document"""

        summaries = []

        for i, doc in enumerate(self.documents):
            # Generate summary using LLM
            prompt = f"""Create a concise but comprehensive summary (2-3 sentences)
            that captures all important information:

            {doc.page_content[:2000]}..."""

            summary = self.llm.invoke(prompt)
            summaries.append(summary)

            # Store original document
            self.store.mset([(str(i), doc)])

        return summaries

    def setup_retriever(self, embedding):
        """Setup multi-vector retriever"""

        summaries = self.create_summaries()

        # Create vector store from summaries
        vectorstore = Chroma.from_texts(
            texts=summaries,
            embedding=embedding,
            metadatas=[{"original_id": str(i)} for i in range(len(self.documents))],
            collection_metadata={"hnsw:space": "cosine"}
        )

        # Create retriever
        retriever = MultiVectorRetriever(
            vectorstore=vectorstore,
            docstore=self.store,
            id_key="original_id"
        )

        return retriever

    def retrieve(self, query: str, k: int = 3):
        """Retrieve documents selected by summary similarity"""
        return self.retriever.invoke(query, limit=k)
```

Usage:
```python
two_stage = TwoStageRetriever(llm=llm, documents=large_documents)
retriever = two_stage.setup_retriever(embedding=embedding)

# Retrieves full documents selected by summary relevance
relevant_docs = retriever.retrieve(query="Your question", k=3)
```

---

## Production Checklist: Before Deploying to Production

### Configuration
- [ ] Test ChromaDB migration to cosine distance
- [ ] Verify embedding normalization is enabled
- [ ] Test with sample documents from each document type
- [ ] Verify metadata filtering performance with production data size

### Functionality
- [ ] Test relevance threshold with various query types
- [ ] Verify context formatting works with target LLM
- [ ] Test token counting accuracy
- [ ] Verify chunk overlap prevents context loss
- [ ] Test metadata filtering doesn't degrade performance

### Performance
- [ ] Benchmark retrieval latency (target: <100ms for k=5)
- [ ] Load test with concurrent requests
- [ ] Monitor memory usage with full production corpus
- [ ] Test streaming endpoint performance

### Error Handling
- [ ] Test behavior when no relevant documents found
- [ ] Test with empty queries
- [ ] Test with very long documents
- [ ] Test with special characters in metadata
- [ ] Verify error messages are helpful

### Monitoring
- [ ] Set up logging for retrieval queries
- [ ] Monitor relevance score distributions
- [ ] Alert on empty retrieval results
- [ ] Track query latency percentiles (p50, p95, p99)
- [ ] Monitor token usage for cost estimation

---

## Troubleshooting

### Problem: Negative Similarity Scores
**Cause:** Using L2 distance instead of cosine
**Solution:**
```python
# Check collection configuration
collection = client.get_collection("documents")
print(collection.metadata)  # Should show: {'hnsw:space': 'cosine'}

# If not cosine, migrate collection (see RAG_RESEARCH_REPORT.md)
```

### Problem: Very Similar Scores for Different Documents
**Cause:** Embedding model or chunk size mismatch
**Solution:**
```python
# Verify normalization
embedding = SentenceTransformerEmbeddingFunction(
    model_name="...",
    normalize_embeddings=True  # Check this is True
)

# Verify chunk quality
print("Sample chunk length:", len(chunks[0].page_content))
# Should be around 1000 characters
```

### Problem: Slow Retrieval
**Cause:** Large collection with metadata filtering
**Solution:**
```python
# Option 1: Use separate collections per source
web_docs = client.get_collection("web_docs")
pdf_docs = client.get_collection("pdf_docs")
# Search only relevant collection

# Option 2: Add HNSW tuning
collection = client.get_collection("documents")
# Recreate with:
# metadata={"hnsw:space": "cosine", "hnsw:M": 32, "hnsw:ef_construction": 500}
```

### Problem: Token Limit Exceeded
**Cause:** Retrieved too many documents
**Solution:**
```python
manager = ContextWindowManager(model_name="gpt-3.5-turbo")
k = manager.get_optimal_k(query)  # Use dynamic k
documents = retriever.retrieve(query, k=k)
documents = manager.truncate_context(documents)  # Truncate if needed
```

---

## Common Configuration Mistakes

### Mistake 1: Forgetting to Normalize Embeddings
```python
# WRONG
embedding = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# RIGHT
embedding = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    encode_kwargs={"normalize_embeddings": True}
)
```

### Mistake 2: Using Default ChromaDB Distance Metric
```python
# WRONG
collection = client.create_collection(name="docs")  # Uses L2 by default!

# RIGHT
collection = client.create_collection(
    name="docs",
    metadata={"hnsw:space": "cosine"}
)
```

### Mistake 3: Not Converting Distance to Similarity
```python
# WRONG - distance is used directly
score = result["distances"][0][0]
if score > 0.5:  # WRONG logic
    print("Relevant")

# RIGHT - convert distance to similarity
distance = result["distances"][0][0]
similarity = 1 - distance
if similarity > 0.5:  # Correct logic
    print("Relevant")
```

### Mistake 4: Ignoring Context Window Limits
```python
# WRONG - no token management
context = vectorstore.similarity_search(query, k=20)  # Could be 10KB+

# RIGHT - manage context
manager = ContextWindowManager()
k = manager.get_optimal_k(query)
context = vectorstore.similarity_search(query, k=k)
context = manager.truncate_context(context)
```

---

## Performance Optimization Tips

### Tip 1: Use Appropriate k Values
```python
# Simple queries: retrieve less
if query_complexity == "simple":
    k = 3  # ~750 tokens

# Complex queries: retrieve more
elif query_complexity == "complex":
    k = 10  # ~2500 tokens
```

### Tip 2: Cache Embeddings
```python
# Don't re-embed the same query
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_embedding(text: str):
    return embedding.embed_query(text)
```

### Tip 3: Use Metadata Filtering to Reduce Search Space
```python
# Search only relevant subset
results = vectorstore.similarity_search_with_score(
    query=query,
    filter={"source": "documentation"},  # Reduces search space by 90%
    k=5
)
```

### Tip 4: Batch Index Operations
```python
# DON'T: Add documents one by one
for doc in documents:
    vectorstore.add_documents([doc])  # Slow!

# DO: Batch add
vectorstore.add_documents(documents)  # Fast!
```

---

## References for Implementation

- Full research available in: `RAG_RESEARCH_REPORT.md`
- ChromaDB docs: https://docs.trychroma.com/
- LangChain docs: https://docs.langchain.com/
- Best practices: Refer to "Gotchas" section in research report

