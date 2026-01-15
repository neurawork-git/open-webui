import logging
import os
import gc
from typing import Awaitable, Optional, Union

import requests
import aiohttp
import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
import time
import re

from urllib.parse import quote
from huggingface_hub import snapshot_download
from langchain_classic.retrievers import (
    ContextualCompressionRetriever,
    EnsembleRetriever,
)
# Note: We use custom ScoringBM25Retriever instead of langchain's BM25Retriever
# to expose normalized BM25 scores in document metadata for thresholds and display
from langchain_core.documents import Document

from open_webui.config import VECTOR_DB
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

# Import the unified RAG settings model
from open_webui.retrieval.models import RAGQuerySettings

from open_webui.models.users import UserModel
from open_webui.models.files import Files
from open_webui.models.knowledge import Knowledges

from open_webui.models.chats import Chats
from open_webui.models.notes import Notes
from open_webui.models.access_grants import AccessGrants

from open_webui.retrieval.vector.main import GetResult
from open_webui.utils.headers import include_user_info_headers
from open_webui.utils.misc import get_message_list

from open_webui.retrieval.web.utils import get_web_loader
from open_webui.retrieval.loaders.youtube import YoutubeLoader


####################
# RAG Settings Merge
####################


def merge_rag_settings(*settings_dicts: Optional[dict]) -> dict:
    """
    Merge RAG settings from multiple sources with priority cascade.
    Later arguments override earlier ones. None values are skipped.

    Priority order (pass in this order): global, user, model, chat, knowledge
    The last non-None value for each key wins.

    Args:
        *settings_dicts: Variable number of settings dictionaries

    Returns:
        Merged settings dict with all populated fields
    """
    merged = {}
    rag_keys = [
        "top_k",
        "top_k_reranker",
        "relevance_threshold",
        "enable_hybrid_search",
        "hybrid_bm25_weight",
        "full_context",
    ]

    for settings in settings_dicts:
        if settings is None:
            continue
        for key in rag_keys:
            if key in settings and settings[key] is not None:
                merged[key] = settings[key]

    return merged


####################
# BM25 Tokenization
####################


def tokenize_for_bm25(text: str) -> list[str]:
    """
    Tokenize text for BM25 scoring with proper punctuation handling.

    - Converts to lowercase
    - Removes punctuation from word boundaries
    - Preserves German umlauts and internal hyphens/periods
    - Filters empty tokens

    Args:
        text: The text to tokenize

    Returns:
        List of cleaned lowercase tokens
    """
    # Lowercase
    text = text.lower()

    # Split on whitespace
    tokens = text.split()

    # Strip punctuation from token boundaries
    # Keep internal characters (e.g., hyphenated words, decimal numbers)
    cleaned = []
    for token in tokens:
        # Remove leading/trailing non-word chars but keep internal ones
        # \w matches [a-zA-Z0-9_] plus Unicode letters (umlauts etc.)
        cleaned_token = re.sub(r'^[^\w]+|[^\w]+$', '', token, flags=re.UNICODE)
        if cleaned_token:
            cleaned.append(cleaned_token)

    return cleaned


def extract_matched_keywords(query: str, document_text: str) -> list[str]:
    """
    Extract which BM25 query tokens matched in the document.

    This is used for keyword highlighting in the citation UI.

    Args:
        query: User query string
        document_text: Document content to check against

    Returns:
        List of matched keyword tokens (lowercased), in original query order
    """
    query_tokens = tokenize_for_bm25(query)
    document_tokens = set(tokenize_for_bm25(document_text))

    # Find query tokens that appear in document
    # Return in original query order for consistent coloring
    matched = []
    seen = set()
    for token in query_tokens:
        if token in document_tokens and token not in seen:
            matched.append(token)
            seen.add(token)

    return matched


from open_webui.env import (
    AIOHTTP_CLIENT_TIMEOUT,
    OFFLINE_MODE,
    ENABLE_FORWARD_USER_INFO_HEADERS,
    AIOHTTP_CLIENT_SESSION_SSL,
    EMBEDDING_MAX_RETRIES,
    EMBEDDING_RETRY_INITIAL_DELAY,
    EMBEDDING_RETRY_MAX_DELAY,
    EMBEDDING_RETRY_BACKOFF_FACTOR,
)
from open_webui.config import (
    RAG_EMBEDDING_QUERY_PREFIX,
    RAG_EMBEDDING_CONTENT_PREFIX,
    RAG_EMBEDDING_PREFIX_FIELD_NAME,
)

log = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Custom exception for embedding generation errors."""
    pass


class PartialEmbeddingError(EmbeddingError):
    """Exception raised when API returns fewer embeddings than requested."""
    def __init__(self, expected: int, received: int, embeddings: list = None):
        self.expected = expected
        self.received = received
        self.embeddings = embeddings or []
        super().__init__(f"Expected {expected} embeddings, received {received}")


class RateLimitError(EmbeddingError):
    """Exception raised when API rate limit (429) is hit."""
    def __init__(self, retry_after: float = 1.0, message: str = "Rate limited"):
        self.retry_after = retry_after
        super().__init__(message)


def cleanup_memory():
    """
    Clean up memory after heavy operations like embedding generation or RAG searches.
    Triggers garbage collection and clears CUDA cache if available.
    """
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass  # torch not installed, skip CUDA cleanup


async def embedding_with_retry(
    embedding_func,
    texts: list[str],
    max_retries: int = None,
    initial_delay: float = None,
    max_delay: float = None,
    backoff_factor: float = None,
    tracker=None,
    **kwargs
) -> list[list[float]]:
    """
    Wrapper that adds retry logic and validation to embedding functions.

    Args:
        embedding_func: The async embedding function to call
        texts: List of texts to generate embeddings for
        max_retries: Maximum number of retry attempts (default from env)
        initial_delay: Initial delay between retries in seconds (default from env)
        max_delay: Maximum delay between retries in seconds (default from env)
        backoff_factor: Multiplier for exponential backoff (default from env)
        tracker: Optional ProcessingTaskTracker for cancellation checking
        **kwargs: Additional arguments to pass to embedding_func

    Returns:
        List of embeddings matching the input texts

    Raises:
        EmbeddingError: If all retries fail or validation fails
        ProcessingCancelledException: If task is cancelled during retry
    """
    from open_webui.models.processing import ProcessingCancelledException

    max_retries = max_retries if max_retries is not None else EMBEDDING_MAX_RETRIES
    initial_delay = initial_delay if initial_delay is not None else EMBEDDING_RETRY_INITIAL_DELAY
    max_delay = max_delay if max_delay is not None else EMBEDDING_RETRY_MAX_DELAY
    backoff_factor = backoff_factor if backoff_factor is not None else EMBEDDING_RETRY_BACKOFF_FACTOR

    expected_count = len(texts)
    last_error = None
    delay = initial_delay

    for attempt in range(max_retries + 1):
        # Check for cancellation before each attempt
        if tracker and tracker.is_cancelled():
            log.info(f"[Embedding] Cancelled at retry attempt {attempt}")
            raise ProcessingCancelledException("Processing cancelled during embedding retry")

        try:
            if attempt > 0:
                log.warning(f"[Embedding] Retry {attempt}/{max_retries} after {delay:.1f}s")
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)

            result = await embedding_func(texts=texts, **kwargs)

            if result is None:
                last_error = EmbeddingError("API returned None (likely rate limit or connection issue)")
                continue

            if len(result) != expected_count:
                raise PartialEmbeddingError(expected=expected_count, received=len(result), embeddings=result)

            return result

        except PartialEmbeddingError as e:
            last_error = e
            log.warning(f"[Embedding] Partial result: {e.received}/{e.expected}")

        except RateLimitError as e:
            last_error = e
            delay = min(e.retry_after, max_delay)
            log.warning(f"[Embedding] Rate limited, waiting {e.retry_after:.1f}s")

        except EmbeddingError:
            raise

        except aiohttp.ClientError as e:
            last_error = EmbeddingError(f"Connection error: {e}")
            log.warning(f"[Embedding] Connection error: {type(e).__name__}")

        except asyncio.TimeoutError:
            last_error = EmbeddingError("Timeout")
            log.warning("[Embedding] Request timeout")

        except Exception as e:
            log.exception(f"[Embedding] Unexpected error: {e}")
            raise EmbeddingError(f"Unexpected error: {e}") from e

    log.error(f"[Embedding] Failed after {max_retries + 1} attempts: {last_error}")
    raise last_error


from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever


def is_youtube_url(url: str) -> bool:
    youtube_regex = r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$"
    return re.match(youtube_regex, url) is not None


def get_loader(request, url: str):
    if is_youtube_url(url):
        return YoutubeLoader(
            url,
            language=request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            proxy_url=request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
        )
    else:
        return get_web_loader(
            url,
            verify_ssl=request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
            requests_per_second=request.app.state.config.WEB_LOADER_CONCURRENT_REQUESTS,
            trust_env=request.app.state.config.WEB_SEARCH_TRUST_ENV,
        )


def build_loader_from_config(request):
    """Build a Loader instance with the admin's configured extraction engine settings."""
    from open_webui.retrieval.loaders.main import Loader

    config = request.app.state.config
    return Loader(
        engine=config.CONTENT_EXTRACTION_ENGINE,
        DATALAB_MARKER_API_KEY=config.DATALAB_MARKER_API_KEY,
        DATALAB_MARKER_API_BASE_URL=config.DATALAB_MARKER_API_BASE_URL,
        DATALAB_MARKER_ADDITIONAL_CONFIG=config.DATALAB_MARKER_ADDITIONAL_CONFIG,
        DATALAB_MARKER_SKIP_CACHE=config.DATALAB_MARKER_SKIP_CACHE,
        DATALAB_MARKER_FORCE_OCR=config.DATALAB_MARKER_FORCE_OCR,
        DATALAB_MARKER_PAGINATE=config.DATALAB_MARKER_PAGINATE,
        DATALAB_MARKER_STRIP_EXISTING_OCR=config.DATALAB_MARKER_STRIP_EXISTING_OCR,
        DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION=config.DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION,
        DATALAB_MARKER_FORMAT_LINES=config.DATALAB_MARKER_FORMAT_LINES,
        DATALAB_MARKER_USE_LLM=config.DATALAB_MARKER_USE_LLM,
        DATALAB_MARKER_OUTPUT_FORMAT=config.DATALAB_MARKER_OUTPUT_FORMAT,
        EXTERNAL_DOCUMENT_LOADER_URL=config.EXTERNAL_DOCUMENT_LOADER_URL,
        EXTERNAL_DOCUMENT_LOADER_API_KEY=config.EXTERNAL_DOCUMENT_LOADER_API_KEY,
        TIKA_SERVER_URL=config.TIKA_SERVER_URL,
        DOCLING_SERVER_URL=config.DOCLING_SERVER_URL,
        DOCLING_API_KEY=config.DOCLING_API_KEY,
        DOCLING_PARAMS=config.DOCLING_PARAMS,
        PDF_EXTRACT_IMAGES=config.PDF_EXTRACT_IMAGES,
        PDF_LOADER_MODE=config.PDF_LOADER_MODE,
        DOCUMENT_INTELLIGENCE_ENDPOINT=config.DOCUMENT_INTELLIGENCE_ENDPOINT,
        DOCUMENT_INTELLIGENCE_KEY=config.DOCUMENT_INTELLIGENCE_KEY,
        DOCUMENT_INTELLIGENCE_MODEL=config.DOCUMENT_INTELLIGENCE_MODEL,
        MISTRAL_OCR_API_BASE_URL=config.MISTRAL_OCR_API_BASE_URL,
        MISTRAL_OCR_API_KEY=config.MISTRAL_OCR_API_KEY,
        MINERU_API_MODE=config.MINERU_API_MODE,
        MINERU_API_URL=config.MINERU_API_URL,
        MINERU_API_KEY=config.MINERU_API_KEY,
        MINERU_API_TIMEOUT=config.MINERU_API_TIMEOUT,
        MINERU_PARAMS=config.MINERU_PARAMS,
    )


def _extract_text_from_binary_response(request, response: requests.Response, url: str) -> tuple[str, list]:
    """Download response body to a temp file and extract text using the Loader pipeline."""
    import mimetypes
    import tempfile
    import urllib.parse

    content_type = response.headers.get('Content-Type', '').split(';')[0].strip()

    # Derive filename from URL path, falling back to Content-Disposition or mime guess
    url_path = urllib.parse.urlparse(url).path
    filename = os.path.basename(url_path) if url_path else ''

    if not filename or '.' not in filename:
        # Try Content-Disposition header
        cd = response.headers.get('Content-Disposition', '')
        if 'filename=' in cd:
            filename = cd.split('filename=')[-1].strip('"\'')

    if not filename or '.' not in filename:
        ext = mimetypes.guess_extension(content_type) or ''
        filename = f'download{ext}'

    suffix = '.' + filename.split('.')[-1].lower() if '.' in filename else ''

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    try:
        loader = build_loader_from_config(request)
        docs = loader.load(filename, content_type, tmp_path)
        for doc in docs:
            doc.metadata['source'] = url
        content = ' '.join([doc.page_content for doc in docs])
        return content, docs
    finally:
        os.remove(tmp_path)


def _is_text_content_type(content_type: str) -> bool:
    """Return True if the content type should be handled by the web loader."""
    ct = content_type.split(';')[0].strip().lower()
    if ct.startswith('text/'):
        return True
    if any(t in ct for t in ['xml', 'json', 'javascript']):
        return True
    return not ct  # empty / missing → assume HTML


def get_content_from_url(request, url: str) -> str:
    from open_webui.retrieval.web.utils import validate_url

    # Validate URL before making any request (blocks private IPs, non-HTTP, filter list)
    validate_url(url)

    # Streamed GET to check Content-Type without downloading the body.
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
    except Exception:
        content_type = ''
        response = None

    # Text / HTML / unknown — use the configured web loader
    if response is None or _is_text_content_type(content_type):
        if response is not None:
            response.close()
        loader = get_loader(request, url)
        docs = loader.load()
        content = ' '.join([doc.page_content for doc in docs])
        return content, docs

    # Binary content (PDF, DOCX, XLSX, PPTX, etc.) — download and extract
    try:
        return _extract_text_from_binary_response(request, response, url)
    finally:
        response.close()


CHUNK_HASH_KEY = "_chunk_hash"


def _content_hash(text: str) -> str:
    """SHA-256 hash of text, used as a stable chunk identifier for RRF dedup."""
    return hashlib.sha256(text.encode()).hexdigest()


class VectorSearchRetriever(BaseRetriever):
    collection_name: Any
    embedding_function: Any
    top_k: int

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        """Get documents relevant to a query.

        Args:
            query: String to find relevant documents for.
            run_manager: The callback handler to use.

        Returns:
            List of relevant documents.
        """
        return []

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        log.debug(f"[HYBRID_DEBUG] VectorSearchRetriever: query='{query[:100]}...' collection={self.collection_name}")

        embedding = await self.embedding_function(query, RAG_EMBEDDING_QUERY_PREFIX)
        result = await ASYNC_VECTOR_DB_CLIENT.search(
            collection_name=self.collection_name,
            vectors=[embedding],
            limit=self.top_k,
        )

        if result is None:
            log.warning(
                f"VectorSearchRetriever: search returned None for collection '{self.collection_name}'. "
                "This may indicate the collection doesn't exist, is empty, or has a dimension mismatch."
            )
            return []

        ids = result.ids[0]
        metadatas = result.metadatas[0]
        documents = result.documents[0]

        # Log vector search results with distances
        log.debug(f"[HYBRID_DEBUG] VectorSearch returned {len(ids)} results:")
        for idx in range(min(len(ids), 10)):  # Log top 10
            doc_preview = documents[idx][:80].replace('\n', ' ') if documents[idx] else 'N/A'
            distance = result.distances[0][idx] if hasattr(result, 'distances') and result.distances else 'N/A'
            source = metadatas[idx].get('source', metadatas[idx].get('name', 'unknown'))
            log.debug(f"[HYBRID_DEBUG]   Vector #{idx+1}: distance={distance}, source={source}, preview='{doc_preview}...'")

        results = []
        for idx in range(len(ids)):
            metadata = metadatas[idx].copy()
            metadata[CHUNK_HASH_KEY] = _content_hash(documents[idx])
            # Include vector distance as score in metadata for downstream use
            if hasattr(result, 'distances') and result.distances and len(result.distances[0]) > idx:
                metadata["score"] = result.distances[0][idx]
            results.append(
                Document(
                    metadata=metadata,
                    page_content=documents[idx],
                )
            )
        return results


class ScoringBM25Retriever(BaseRetriever):
    """
    A BM25 retriever that stores normalized BM25 scores in document metadata.

    Unlike langchain's BM25Retriever which doesn't expose scores, this retriever
    normalizes BM25 scores to 0-1 range and stores them in metadata["score"]
    for compatibility with relevance thresholds and display.
    """
    texts: list[str]
    metadatas: list[dict]
    bm25_scores: list[float]  # Pre-computed BM25 scores for all documents
    k: int = 4

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        """Sync version - returns empty as we use async."""
        return []

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """
        Return top-k documents with normalized BM25 scores in metadata.

        BM25 scores are normalized to 0-1 range using min-max normalization
        to be comparable with vector similarity scores for threshold filtering.
        """
        # Pair documents with their BM25 scores
        scored_docs = list(zip(self.bm25_scores, self.texts, self.metadatas))

        # Sort by BM25 score descending and take top k
        scored_docs_sorted = sorted(scored_docs, key=lambda x: x[0], reverse=True)
        top_k_docs = scored_docs_sorted[:self.k]

        if not top_k_docs:
            return []

        # Normalize scores to 0-1 range
        # Use min-max normalization based on the top-k results
        scores_in_topk = [doc[0] for doc in top_k_docs]
        max_score = max(scores_in_topk) if scores_in_topk else 1.0
        min_score = min(scores_in_topk) if scores_in_topk else 0.0
        score_range = max_score - min_score if max_score > min_score else 1.0

        results = []
        for bm25_score, text, metadata in top_k_docs:
            meta_copy = metadata.copy() if metadata else {}

            # Normalize BM25 score to 0-1 range (0% to 100%)
            # No match = 0%, best match = 100%
            if bm25_score <= 0:
                normalized_score = 0.0
            elif max_score > 0:
                normalized_score = bm25_score / max_score
            else:
                normalized_score = 0.0

            meta_copy["score"] = normalized_score
            meta_copy["bm25_raw_score"] = bm25_score  # Keep raw score for debugging

            log.debug(
                f"[HYBRID_DEBUG] ScoringBM25: raw={bm25_score:.4f}, "
                f"normalized={normalized_score:.4f}, text='{text[:50]}...'"
            )

            results.append(Document(
                page_content=text,
                metadata=meta_copy,
            ))

        return results

    @classmethod
    def from_texts_and_scores(
        cls,
        texts: list[str],
        metadatas: list[dict],
        bm25_scores: list[float],
        k: int = 4,
    ) -> "ScoringBM25Retriever":
        """
        Create a ScoringBM25Retriever from texts, metadata, and pre-computed BM25 scores.

        Args:
            texts: Document texts
            metadatas: Document metadata dicts
            bm25_scores: Pre-computed BM25 scores (from BM25Okapi.get_scores())
            k: Number of documents to retrieve
        """
        return cls(
            texts=texts,
            metadatas=metadatas,
            bm25_scores=bm25_scores,
            k=k,
        )


def query_doc(
    collection_name: str, query_embedding: list[float], k: int, user: UserModel = None
):
    try:
        log.debug(f"query_doc:doc {collection_name}")
        result = VECTOR_DB_CLIENT.search(
            collection_name=collection_name,
            vectors=[query_embedding],
            limit=k,
        )

        if result:
            log.info(f"query_doc:result {result.ids} {result.metadatas}")

        return result
    except Exception as e:
        log.exception(f"Error querying doc {collection_name} with limit {k}: {e}")
        raise e


def get_doc(collection_name: str, user: UserModel = None):
    try:
        log.debug(f"get_doc:doc {collection_name}")
        result = VECTOR_DB_CLIENT.get(collection_name=collection_name)

        if result:
            log.info(f"query_doc:result {result.ids} {result.metadatas}")

        return result
    except Exception as e:
        log.exception(f"Error getting doc {collection_name}: {e}")
        raise e


def get_enriched_texts(collection_result: GetResult) -> list[str]:
    enriched_texts = []
    for idx, text in enumerate(collection_result.documents[0]):
        metadata = collection_result.metadatas[0][idx]
        metadata_parts = [text]

        # Add filename (repeat twice for extra weight in BM25 scoring)
        if metadata.get("name"):
            filename = metadata["name"]
            filename_tokens = (
                filename.replace("_", " ").replace("-", " ").replace(".", " ")
            )
            metadata_parts.append(
                f"Filename: {filename} {filename_tokens} {filename_tokens}"
            )

        # Add title if available
        if metadata.get("title"):
            metadata_parts.append(f"Title: {metadata['title']}")

        # Add document section headings if available (from markdown splitter)
        if metadata.get("headings") and isinstance(metadata["headings"], list):
            headings = " > ".join(str(h) for h in metadata["headings"])
            metadata_parts.append(f"Section: {headings}")

        # Add source URL/path if available
        if metadata.get("source"):
            metadata_parts.append(f"Source: {metadata['source']}")

        # Add snippet for web search results
        if metadata.get("snippet"):
            metadata_parts.append(f"Snippet: {metadata['snippet']}")

        enriched_texts.append(" ".join(metadata_parts))

    return enriched_texts


async def query_doc_with_hybrid_search(
    collection_name: str,
    collection_result: GetResult,
    query: str,
    embedding_function,
    k: int,
    reranking_function,
    k_reranker: int,
    r: float,
    hybrid_bm25_weight: float,
    enable_enriched_texts: bool = False,
    enable_reranking: bool = True,
) -> dict:
    try:
        # First check if collection_result has the required attributes
        if (
            not collection_result
            or not hasattr(collection_result, "documents")
            or not hasattr(collection_result, "metadatas")
        ):
            log.warning(f"query_doc_with_hybrid_search:no_docs {collection_name}")
            return {"documents": [], "metadatas": [], "distances": []}

        # Now safely check the documents content after confirming attributes exist
        if (
            not collection_result.documents
            or len(collection_result.documents) == 0
            or not collection_result.documents[0]
        ):
            log.warning(f"query_doc_with_hybrid_search:no_docs {collection_name}")
            return {"documents": [], "metadatas": [], "distances": []}

        log.debug(f"query_doc_with_hybrid_search:doc {collection_name}")

        original_texts = collection_result.documents[0]
        bm25_metadatas = [
            {**meta, CHUNK_HASH_KEY: _content_hash(original_texts[idx])}
            for idx, meta in enumerate(collection_result.metadatas[0])
        ]

        log.debug(f"[HYBRID_DEBUG] === HYBRID SEARCH START ===")
        log.debug(f"[HYBRID_DEBUG] Query: '{query}'")
        log.debug(f"[HYBRID_DEBUG] Collection: {collection_name}")
        log.debug(f"[HYBRID_DEBUG] Parameters: k={k}, k_reranker={k_reranker}, r={r}, bm25_weight={hybrid_bm25_weight}")
        log.debug(f"[HYBRID_DEBUG] Enriched texts: {enable_enriched_texts}")
        log.debug(f"[HYBRID_DEBUG] Total docs in collection: {len(collection_result.documents[0])}")

        bm25_texts = (
            get_enriched_texts(collection_result)
            if enable_enriched_texts
            else original_texts
        )

        # Filter out empty/whitespace-only texts to prevent embedding errors
        # Keep track of valid indices to maintain alignment with metadata
        valid_indices = []
        valid_texts = []
        valid_metadatas = []
        for i, (text, meta) in enumerate(zip(bm25_texts, bm25_metadatas)):
            if text and text.strip():
                valid_indices.append(i)
                valid_texts.append(text)
                valid_metadatas.append(meta)
            else:
                log.warning(f"[HYBRID_DEBUG] Filtering empty document at index {i}")

        if len(valid_texts) < len(bm25_texts):
            log.warning(
                f"[HYBRID_DEBUG] Filtered {len(bm25_texts) - len(valid_texts)} empty documents "
                f"(remaining: {len(valid_texts)})"
            )

        # If no valid documents remain, return empty results
        if not valid_texts:
            log.warning(f"[HYBRID_DEBUG] No valid documents in collection {collection_name} after filtering")
            return {"documents": [], "metadatas": [], "distances": []}

        # Use filtered texts and metadata
        bm25_texts = valid_texts
        filtered_metadatas = valid_metadatas

        # Compute BM25 scores using rank_bm25
        from rank_bm25 import BM25Okapi

        # Manually compute BM25 scores for logging
        # Use smart tokenization that strips punctuation from word boundaries
        tokenized_docs = [tokenize_for_bm25(doc) for doc in bm25_texts]
        bm25_index = BM25Okapi(tokenized_docs)
        query_tokens = tokenize_for_bm25(query)
        bm25_scores = bm25_index.get_scores(query_tokens)

        # Log BM25 scores for all docs
        log.debug(f"[HYBRID_DEBUG] BM25 Scoring (query tokens: {query_tokens}):")
        scored_docs = list(zip(bm25_scores, bm25_texts, filtered_metadatas))
        scored_docs_sorted = sorted(scored_docs, key=lambda x: x[0], reverse=True)

        for idx, (score, text, meta) in enumerate(scored_docs_sorted[:10]):  # Top 10
            doc_preview = text[:80].replace('\n', ' ') if text else 'N/A'
            source = meta.get('source', meta.get('name', 'unknown'))
            log.debug(f"[HYBRID_DEBUG]   BM25 #{idx+1}: score={score:.4f}, source={source}, preview='{doc_preview}...'")

        # Use ScoringBM25Retriever which stores normalized BM25 scores in metadata
        # This ensures BM25-matched documents have proper scores for thresholds and display
        bm25_retriever = ScoringBM25Retriever.from_texts_and_scores(
            texts=bm25_texts,
            metadatas=filtered_metadatas,
            bm25_scores=list(bm25_scores),
            k=k,
        )

        vector_search_retriever = VectorSearchRetriever(
            collection_name=collection_name,
            embedding_function=embedding_function,
            top_k=k,
        )

        # Use CHUNK_HASH_KEY for dedup so enriched BM25 texts don't defeat RRF
        if hybrid_bm25_weight <= 0:
            log.debug(f"[HYBRID_DEBUG] Mode: VECTOR ONLY (bm25_weight={hybrid_bm25_weight})")
            ensemble_retriever = EnsembleRetriever(
                retrievers=[vector_search_retriever],
                weights=[1.0],
                id_key=CHUNK_HASH_KEY,
            )
        elif hybrid_bm25_weight >= 1:
            log.debug(f"[HYBRID_DEBUG] Mode: BM25 ONLY (bm25_weight={hybrid_bm25_weight})")
            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever],
                weights=[1.0],
                id_key=CHUNK_HASH_KEY,
            )
        else:
            log.debug(f"[HYBRID_DEBUG] Mode: HYBRID (BM25={hybrid_bm25_weight:.2f}, Vector={1.0-hybrid_bm25_weight:.2f})")
            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_search_retriever],
                weights=[hybrid_bm25_weight, 1.0 - hybrid_bm25_weight],
                id_key=CHUNK_HASH_KEY,
            )

        compressor = RerankCompressor(
            embedding_function=embedding_function,
            top_n=k_reranker,
            reranking_function=reranking_function,
            r_score=r,
            enable_reranking=enable_reranking,
        )

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=ensemble_retriever
        )

        result = await compression_retriever.ainvoke(query)

        # Add BM25 matched keywords to each document's metadata for highlighting
        keywords_added_count = 0
        for doc in result:
            matched_keywords = extract_matched_keywords(query, doc.page_content)
            if matched_keywords:
                doc.metadata["bm25_matched_keywords"] = matched_keywords
                keywords_added_count += 1

        if keywords_added_count > 0:
            log.info(f"[BM25_KEYWORDS] Added matched keywords to {keywords_added_count}/{len(result)} docs for query: '{query}'")

        distances = [d.metadata.get("score") for d in result]
        documents = [d.page_content for d in result]
        metadatas = [d.metadata for d in result]

        # retrieve only min(k, k_reranker) items, sort and cut by distance if k < k_reranker
        if k < k_reranker:
            sorted_items = sorted(
                zip(distances, documents, metadatas), key=lambda x: x[0], reverse=True
            )
            sorted_items = sorted_items[:k]

            if sorted_items:
                distances, metadatas, documents = map(list, zip(*sorted_items))
            else:
                distances, documents, metadatas = [], [], []

        result = {
            "distances": [distances],
            "documents": [documents],
            "metadatas": [metadatas],
        }

        log.info(
            "query_doc_with_hybrid_search:result "
            + f'{result["metadatas"]} {result["distances"]}'
        )
        return result
    except Exception as e:
        log.exception(f"Error querying doc {collection_name} with hybrid search: {e}")
        raise e


async def query_doc_with_hybrid_search_settings(
    collection_name: str,
    collection_result: GetResult,
    query: str,
    embedding_function,
    reranking_function,
    settings: RAGQuerySettings,
) -> dict:
    """
    Query a document collection using hybrid search with unified RAGQuerySettings.

    This is the new interface that accepts a RAGQuerySettings object instead of
    individual parameters. It delegates to the existing implementation.

    Args:
        collection_name: Name of the vector collection
        collection_result: Pre-fetched collection data
        query: Search query string
        embedding_function: Function to generate embeddings
        reranking_function: Function to rerank results (can be None)
        settings: Unified RAG query settings

    Returns:
        Dict with 'documents', 'metadatas', 'distances' keys
    """
    return await query_doc_with_hybrid_search(
        collection_name=collection_name,
        collection_result=collection_result,
        query=query,
        embedding_function=embedding_function,
        k=settings.top_k,
        reranking_function=reranking_function,
        k_reranker=settings.top_k_reranker,
        r=settings.relevance_threshold,
        hybrid_bm25_weight=settings.hybrid_bm25_weight,
        enable_enriched_texts=settings.enable_enriched_texts,
        enable_reranking=settings.enable_reranking,
    )


def merge_get_results(get_results: list[dict]) -> dict:
    # Initialize lists to store combined data
    combined_documents = []
    combined_metadatas = []
    combined_ids = []

    for data in get_results:
        combined_documents.extend(data["documents"][0])
        combined_metadatas.extend(data["metadatas"][0])
        combined_ids.extend(data["ids"][0])

    # Create the output dictionary
    result = {
        "documents": [combined_documents],
        "metadatas": [combined_metadatas],
        "ids": [combined_ids],
    }

    return result


def merge_and_sort_query_results(query_results: list[dict], k: int) -> dict:
    log.info(f"[HYBRID_DEBUG] === MERGE START: {len(query_results)} query results, k={k} ===")

    # Initialize lists to store combined data
    combined = dict()  # To store documents with unique document hashes

    for idx, data in enumerate(query_results):
        if (
            len(data.get("distances", [])) == 0
            or len(data.get("documents", [])) == 0
            or len(data.get("metadatas", [])) == 0
        ):
            log.info(f"[HYBRID_DEBUG]   Query {idx+1}: EMPTY result, skipping")
            continue

        distances = data["distances"][0]
        documents = data["documents"][0]
        metadatas = data["metadatas"][0]
        log.info(f"[HYBRID_DEBUG]   Query {idx+1}: {len(distances)} docs to merge")

        for distance, document, metadata in zip(distances, documents, metadatas):
            if isinstance(document, str):
                doc_hash = hashlib.sha256(
                    document.encode()
                ).hexdigest()  # Compute a hash for uniqueness

                if doc_hash not in combined.keys():
                    # Make a copy of metadata to avoid mutating the original
                    combined[doc_hash] = (distance, document, dict(metadata) if metadata else {})
                    continue  # if doc is new, no further comparison is needed

                existing_distance, existing_doc, existing_metadata = combined[doc_hash]

                # Merge bm25_matched_keywords regardless of which has higher score
                # Keywords come from hybrid search; we want to preserve them even if
                # vector search has a higher score for the same document
                keywords_to_preserve = None
                if metadata and metadata.get("bm25_matched_keywords"):
                    keywords_to_preserve = metadata["bm25_matched_keywords"]
                elif existing_metadata and existing_metadata.get("bm25_matched_keywords"):
                    keywords_to_preserve = existing_metadata["bm25_matched_keywords"]

                # if doc is already in, but new distance is better, update
                # Handle None distances (e.g., from pure BM25 search) by treating as 0
                dist_val = distance if distance is not None else 0
                existing_dist_val = existing_distance if existing_distance is not None else 0

                if dist_val > existing_dist_val:
                    merged_metadata = dict(metadata) if metadata else {}
                    if keywords_to_preserve and not merged_metadata.get("bm25_matched_keywords"):
                        merged_metadata["bm25_matched_keywords"] = keywords_to_preserve
                    combined[doc_hash] = (distance, document, merged_metadata)
                elif keywords_to_preserve and not existing_metadata.get("bm25_matched_keywords"):
                    # Keep existing (higher score) but add keywords from new result
                    existing_metadata["bm25_matched_keywords"] = keywords_to_preserve

    combined = list(combined.values())
    # Sort the list based on distances (treat None as 0 for sorting)
    combined.sort(key=lambda x: x[0] if x[0] is not None else 0, reverse=True)

    log.info(f"[HYBRID_DEBUG]   After dedup: {len(combined)} unique docs")

    # Slice to keep only the top k elements
    sorted_distances, sorted_documents, sorted_metadatas = (
        zip(*combined[:k]) if combined else ([], [], [])
    )

    # Log final merged results
    log.info(f"[HYBRID_DEBUG] === MERGE FINAL RESULTS (top {k}) ===")
    for i, (dist, doc, meta) in enumerate(zip(sorted_distances, sorted_documents, sorted_metadatas)):
        doc_preview = doc[:80].replace('\n', ' ') if doc else 'N/A'
        source = meta.get('source', meta.get('name', 'unknown')) if meta else 'unknown'
        if dist is not None and isinstance(dist, (int, float)):
            score_str = f"{dist:.4f}"
            pct_str = f"{float(dist)*100:.2f}%"
        else:
            score_str = str(dist)
            pct_str = "N/A"
        log.info(f"[HYBRID_DEBUG]   Final #{i+1}: score={score_str} ({pct_str}), source={source}, preview='{doc_preview}...'")

    # Create and return the output dictionary
    return {
        "distances": [list(sorted_distances)],
        "documents": [list(sorted_documents)],
        "metadatas": [list(sorted_metadatas)],
    }


def filter_results_by_relevance(query_result: dict, relevance_threshold: float) -> dict:
    """
    Filter query results by relevance threshold.
    Only keeps documents with distance/score >= relevance_threshold.

    Args:
        query_result: Dict with 'distances', 'documents', 'metadatas' keys
        relevance_threshold: Minimum score to keep (0.0-1.0)

    Returns:
        Filtered query result dict
    """
    if not query_result or not relevance_threshold or relevance_threshold <= 0:
        return query_result

    distances = query_result.get("distances", [[]])[0]
    documents = query_result.get("documents", [[]])[0]
    metadatas = query_result.get("metadatas", [[]])[0]

    if not distances:
        return query_result

    # Filter by threshold
    filtered = [
        (d, doc, meta)
        for d, doc, meta in zip(distances, documents, metadatas)
        if d >= relevance_threshold
    ]

    if not filtered:
        return {
            "distances": [[]],
            "documents": [[]],
            "metadatas": [[]],
        }

    filtered_distances, filtered_documents, filtered_metadatas = zip(*filtered)

    return {
        "distances": [list(filtered_distances)],
        "documents": [list(filtered_documents)],
        "metadatas": [list(filtered_metadatas)],
    }


def get_all_items_from_collections(collection_names: list[str]) -> dict:
    results = []

    for collection_name in collection_names:
        if collection_name:
            try:
                result = get_doc(collection_name=collection_name)
                if result is not None:
                    results.append(result.model_dump())
            except Exception as e:
                log.exception(f"Error when querying the collection: {e}")
        else:
            pass

    return merge_get_results(results)


async def query_collection(
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    k: int,
) -> dict:
    results = []
    error = False

    def process_query_collection(collection_name, query_embedding):
        try:
            if collection_name:
                result = query_doc(
                    collection_name=collection_name,
                    k=k,
                    query_embedding=query_embedding,
                )
                if result is not None:
                    return result.model_dump(), None
            return None, None
        except Exception as e:
            log.exception(f"Error when querying the collection: {e}")
            return None, e

    try:
        # Generate all query embeddings (in one call)
        query_embeddings = await embedding_function(
            queries, prefix=RAG_EMBEDDING_QUERY_PREFIX
        )
        log.debug(
            f"query_collection: processing {len(queries)} queries across {len(collection_names)} collections"
        )

        with ThreadPoolExecutor() as executor:
            future_results = []
            for query_embedding in query_embeddings:
                for collection_name in collection_names:
                    result = executor.submit(
                        process_query_collection, collection_name, query_embedding
                    )
                    future_results.append(result)
            task_results = [future.result() for future in future_results]

        for result, err in task_results:
            if err is not None:
                error = True
            elif result is not None:
                results.append(result)

        if error and not results:
            log.warning("All collection queries failed. No results returned.")

        return merge_and_sort_query_results(results, k=k)
    finally:
        # Clean up memory after RAG search to prevent accumulation
        cleanup_memory()


async def query_collection_with_hybrid_search(
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    k: int,
    reranking_function,
    k_reranker: int,
    r: float,
    hybrid_bm25_weight: float,
    enable_enriched_texts: bool = False,
    enable_reranking: bool = True,
) -> dict:
    results = []
    error = False
    # Fetch every collection's contents once up front so the
    # per-query/per-document loop below can reuse them. Each fetch
    # offloads to a worker thread, so run them concurrently with
    # `asyncio.gather` instead of awaiting them serially — otherwise
    # latency scales linearly with `len(collection_names)`.
    log.debug(
        'query_collection_with_hybrid_search: prefetching %d collections',
        len(collection_names),
    )

    async def _fetch_collection(name: str):
        try:
            log.debug(f'query_collection_with_hybrid_search:ASYNC_VECTOR_DB_CLIENT.get:collection {name}')
            return name, await ASYNC_VECTOR_DB_CLIENT.get(collection_name=name)
        except Exception as e:
            log.exception(f'Failed to fetch collection {name}: {e}')
            return name, None

    collection_results = dict(await asyncio.gather(*(_fetch_collection(name) for name in collection_names)))

    async def process_query(collection_name, query, collection_result):
        try:
            result = await query_doc_with_hybrid_search(
                collection_name=collection_name,
                collection_result=collection_result,
                query=query,
                embedding_function=embedding_function,
                k=k,
                reranking_function=reranking_function,
                k_reranker=k_reranker,
                r=r,
                hybrid_bm25_weight=hybrid_bm25_weight,
                enable_enriched_texts=enable_enriched_texts,
                enable_reranking=enable_reranking,
            )
            return result, None
        except Exception as e:
            log.exception(f"Error when querying the collection with hybrid_search: {e}")
            return None, e

    # Prepare tasks for all collections and queries
    # Avoid running any tasks for collections that:
    # - Failed to fetch data (have assigned None)
    # - Have no documents (empty collections)
    tasks = []
    for collection_name in collection_names:
        col_result = collection_results[collection_name]
        if col_result is None:
            log.warning(f"[HYBRID_DEBUG] Skipping collection {collection_name}: fetch failed")
            continue
        if not col_result.documents or not col_result.documents[0]:
            log.warning(f"[HYBRID_DEBUG] Skipping collection {collection_name}: no documents")
            continue
        for query in queries:
            tasks.append((collection_name, query))

        log.info(
            f"Starting hybrid search for {len(queries)} queries in {len(collection_names)} collections..."
        )

        # Prepare tasks for all collections and queries
        # Avoid running any tasks for collections that:
        # - Failed to fetch data (have assigned None)
        # - Have no documents (empty collections)
        tasks = []
        for collection_name in collection_names:
            col_result = collection_results[collection_name]
            if col_result is None:
                log.warning(f"[HYBRID_DEBUG] Skipping collection {collection_name}: fetch failed")
                continue
            if not col_result.documents or not col_result.documents[0]:
                log.warning(f"[HYBRID_DEBUG] Skipping collection {collection_name}: no documents")
                continue
            for query in queries:
                tasks.append((collection_name, query, col_result))

        # Run all queries in parallel using asyncio.gather
        task_results = await asyncio.gather(
            *[process_query(coll_name, q, col_res) for coll_name, q, col_res in tasks]
        )

        for result, err in task_results:
            if err is not None:
                error = True
            elif result is not None:
                results.append(result)

        if error and not results:
            raise Exception(
                "Hybrid search failed for all collections. Using Non-hybrid search as fallback."
            )

        return merge_and_sort_query_results(results, k=k)
    finally:
        # Clean up memory after hybrid search to prevent accumulation
        # This is especially important for BM25 which builds indexes in memory
        cleanup_memory()


async def query_collection_with_hybrid_search_settings(
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    reranking_function,
    settings: RAGQuerySettings,
) -> dict:
    """
    Query multiple collections using hybrid search with unified RAGQuerySettings.

    This is the new interface that accepts a RAGQuerySettings object instead of
    individual parameters. It delegates to the existing implementation.

    Args:
        collection_names: List of vector collection names
        queries: List of search queries
        embedding_function: Function to generate embeddings
        reranking_function: Function to rerank results (can be None)
        settings: Unified RAG query settings

    Returns:
        Dict with 'documents', 'metadatas', 'distances' keys
    """
    return await query_collection_with_hybrid_search(
        collection_names=collection_names,
        queries=queries,
        embedding_function=embedding_function,
        k=settings.top_k,
        reranking_function=reranking_function,
        k_reranker=settings.top_k_reranker,
        r=settings.relevance_threshold,
        hybrid_bm25_weight=settings.hybrid_bm25_weight,
        enable_enriched_texts=settings.enable_enriched_texts,
        enable_reranking=settings.enable_reranking,
    )


def generate_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str = "https://api.openai.com/v1",
    key: str = "",
    prefix: str = None,
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    try:
        log.debug(
            f"generate_openai_batch_embeddings:model {model} batch size: {len(texts)}"
        )
        json_data = {"input": texts, "model": model}
        if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
            json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        if ENABLE_FORWARD_USER_INFO_HEADERS and user:
            headers = include_user_info_headers(headers, user)

        r = requests.post(
            f"{url}/embeddings",
            headers=headers,
            json=json_data,
        )
        r.raise_for_status()
        data = r.json()
        if "data" in data:
            return [elem["embedding"] for elem in data["data"]]
        else:
            raise "Something went wrong :/"
    except Exception as e:
        log.exception(f"Error generating openai batch embeddings: {e}")
        return None


async def agenerate_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str = "https://api.openai.com/v1",
    key: str = "",
    prefix: str = None,
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    """
    Generate embeddings using OpenAI API.

    Rate limiting (429) is handled by raising RateLimitError, which is caught
    by embedding_with_retry for centralized retry logic.
    """
    log.debug(
        f"agenerate_openai_batch_embeddings: model={model}, batch_size={len(texts)}"
    )

    form_data = {"input": texts, "model": model}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        form_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    try:
        async with aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
        ) as session:
            async with session.post(
                f"{url}/embeddings",
                headers=headers,
                json=form_data,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as r:
                if r.status == 429:
                    retry_after_str = r.headers.get("Retry-After", "1")
                    try:
                        retry_after = float(retry_after_str)
                    except ValueError:
                        retry_after = 1.0
                    raise RateLimitError(retry_after=retry_after)

                if r.status != 200:
                    error_text = await r.text()
                    log.debug(f"[Embedding] HTTP {r.status}: {error_text[:100]}")
                    return None

                data = await r.json()
                if "data" not in data:
                    return None

                embeddings = [item["embedding"] for item in data["data"]]
                if len(embeddings) != len(texts):
                    return None

                return embeddings

    except RateLimitError:
        raise
    except aiohttp.ClientResponseError:
        return None
    except aiohttp.ClientError:
        return None
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        log.exception(f"[Embedding] Unexpected error: {e}")
        return None


def generate_azure_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = "",
    version: str = "",
    prefix: str = None,
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    try:
        log.debug(
            f"generate_azure_openai_batch_embeddings:deployment {model} batch size: {len(texts)}"
        )
        json_data = {"input": texts}
        if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
            json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

        url = f"{url}/openai/deployments/{model}/embeddings?api-version={version}"

        for _ in range(5):
            headers = {
                "Content-Type": "application/json",
                "api-key": key,
            }
            if ENABLE_FORWARD_USER_INFO_HEADERS and user:
                headers = include_user_info_headers(headers, user)

            r = requests.post(
                url,
                headers=headers,
                json=json_data,
            )
            if r.status_code == 429:
                retry = float(r.headers.get("Retry-After", "1"))
                time.sleep(retry)
                continue
            r.raise_for_status()
            data = r.json()
            if "data" in data:
                return [elem["embedding"] for elem in data["data"]]
            else:
                raise Exception("Something went wrong :/")
        return None
    except Exception as e:
        log.exception(f"Error generating azure openai batch embeddings: {e}")
        return None


async def agenerate_azure_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = "",
    version: str = "",
    prefix: str = None,
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    """Generate embeddings using Azure OpenAI."""
    form_data = {"input": texts}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        form_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    full_url = f"{url}/openai/deployments/{model}/embeddings?api-version={version}"

    headers = {"Content-Type": "application/json", "api-key": key}
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    try:
        async with aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
        ) as session:
            async with session.post(
                full_url,
                headers=headers,
                json=form_data,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as r:
                if r.status == 429:
                    retry_after_str = r.headers.get("Retry-After", "1")
                    try:
                        retry_after = float(retry_after_str)
                    except ValueError:
                        retry_after = 1.0
                    raise RateLimitError(retry_after=retry_after)

                if r.status != 200:
                    error_text = await r.text()
                    log.debug(f"[Embedding] HTTP {r.status}: {error_text[:100]}")
                    return None

                data = await r.json()
                if "data" not in data:
                    return None

                embeddings = [item["embedding"] for item in data["data"]]
                if len(embeddings) != len(texts):
                    return None

                return embeddings

    except RateLimitError:
        raise
    except aiohttp.ClientResponseError:
        return None
    except aiohttp.ClientError:
        return None
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        log.exception(f"[Embedding] Unexpected error: {e}")
        return None


def generate_ollama_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = "",
    prefix: str = None,
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    try:
        log.debug(
            f"generate_ollama_batch_embeddings:model {model} batch size: {len(texts)}"
        )
        json_data = {"input": texts, "model": model}
        if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
            json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        if ENABLE_FORWARD_USER_INFO_HEADERS and user:
            headers = include_user_info_headers(headers, user)

        r = requests.post(
            f"{url}/api/embed",
            headers=headers,
            json=json_data,
        )
        r.raise_for_status()
        data = r.json()

        if "embeddings" in data:
            return data["embeddings"]
        else:
            raise "Something went wrong :/"
    except Exception as e:
        log.exception(f"Error generating ollama batch embeddings: {e}")
        return None


async def agenerate_ollama_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = "",
    prefix: str = None,
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    try:
        log.debug(
            f"agenerate_ollama_batch_embeddings:model {model} batch size: {len(texts)}"
        )
        form_data = {"input": texts, "model": model}
        if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
            form_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        if ENABLE_FORWARD_USER_INFO_HEADERS and user:
            headers = include_user_info_headers(headers, user)

        async with aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
        ) as session:
            async with session.post(
                f"{url}/api/embed",
                headers=headers,
                json=form_data,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as r:
                r.raise_for_status()
                data = await r.json()
                if "embeddings" in data:
                    return data["embeddings"]
                else:
                    raise Exception("Something went wrong :/")
    except Exception as e:
        log.exception(f"Error generating ollama batch embeddings: {e}")
        return None


def get_embedding_function(
    embedding_engine,
    embedding_model,
    embedding_function,
    url,
    key,
    embedding_batch_size,
    azure_api_version=None,
    enable_async=True,
    concurrent_requests=0,
) -> Awaitable:
    if embedding_engine == "":
        # Sentence transformers: CPU-bound sync operation
        async def async_embedding_function(query, prefix=None, user=None):
            return await asyncio.to_thread(
                (
                    lambda query, prefix=None: embedding_function.encode(
                        query,
                        batch_size=int(embedding_batch_size),
                        **({"prompt": prefix} if prefix else {}),
                    ).tolist()
                ),
                query,
                prefix,
            )

        return async_embedding_function
    elif embedding_engine in ["ollama", "openai", "azure_openai"]:
        embedding_function = lambda query, prefix=None, user=None, tracker=None: generate_embeddings(
            engine=embedding_engine,
            model=embedding_model,
            text=query,
            prefix=prefix,
            tracker=tracker,
            url=url,
            key=key,
            user=user,
            azure_api_version=azure_api_version,
        )

        async def async_embedding_function(query, prefix=None, user=None, doc_name=None):
            if isinstance(query, list):
                total_items = len(query)
                batches = [
                    query[i : i + embedding_batch_size]
                    for i in range(0, len(query), embedding_batch_size)
                ]
                num_batches = len(batches)

                # Log start of embedding generation
                doc_label = f"'{doc_name}'" if doc_name else "document"
                log.info(f"[Embedding] {doc_label}: {total_items} chunks in {num_batches} batches")

                if enable_async:
                    # Use semaphore to limit concurrent embedding API requests
                    # 0 = unlimited (no semaphore)
                    if concurrent_requests:
                        semaphore = asyncio.Semaphore(concurrent_requests)

                        async def generate_batch_with_semaphore(batch):
                            async with semaphore:
                                return await embedding_function(
                                    batch, prefix=prefix, user=user, tracker=tracker
                                )

                        tasks = [
                            generate_batch_with_semaphore(batch) for batch in batches
                        ]
                    else:
                        tasks = [
                            embedding_function(batch, prefix=prefix, user=user, tracker=tracker)
                            for batch in batches
                        ]
                    batch_results = await asyncio.gather(*tasks, return_exceptions=False)
                else:
                    # Sequential processing with progress logging
                    batch_results = []
                    for i, batch in enumerate(batches):
                        result = await embedding_function(batch, prefix=prefix, user=user)
                        batch_results.append(result)
                        # Log progress every 5 batches or on last batch
                        if (i + 1) % 5 == 0 or i == num_batches - 1:
                            embedded_count = sum(len(r) for r in batch_results if r)
                            log.info(f"[Embedding] {doc_label}: {embedded_count}/{total_items} chunks")

                # Flatten results with validation
                embeddings = []
                for i, batch_embeddings in enumerate(batch_results):
                    if batch_embeddings is None:
                        raise EmbeddingError(f"Batch {i + 1}/{num_batches} failed")
                    if not isinstance(batch_embeddings, list):
                        raise EmbeddingError(f"Batch {i + 1}/{num_batches} invalid type")
                    embeddings.extend(batch_embeddings)

                if len(embeddings) != total_items:
                    raise PartialEmbeddingError(
                        expected=total_items,
                        received=len(embeddings),
                        embeddings=embeddings
                    )

                log.info(f"[Embedding] {doc_label}: completed {len(embeddings)} chunks")
                return embeddings
            else:
                return await embedding_function(query, prefix, user, tracker)

        return async_embedding_function
    else:
        raise ValueError(f"Unknown embedding engine: {embedding_engine}")


async def generate_embeddings(
    engine: str,
    model: str,
    text: Union[str, list[str]],
    prefix: Union[str, None] = None,
    tracker=None,
    **kwargs,
):
    """
    Generate embeddings with automatic retry logic for transient errors.

    This function wraps the underlying embedding APIs with retry logic to handle:
    - Connection errors (network issues, DNS failures)
    - Timeout errors
    - Partial results (API returns fewer embeddings than requested)

    Args:
        engine: The embedding engine (ollama, openai, azure_openai)
        model: The model name/deployment ID
        text: Single string or list of strings to embed
        prefix: Optional prefix to prepend to texts
        tracker: Optional ProcessingTaskTracker for cancellation checking
        **kwargs: Additional arguments (url, key, user, azure_api_version)

    Returns:
        Single embedding (if text is str) or list of embeddings (if text is list)

    Raises:
        EmbeddingError: If all retry attempts fail
        ProcessingCancelledException: If task is cancelled
    """
    url = kwargs.get("url", "")
    key = kwargs.get("key", "")
    user = kwargs.get("user")

    if prefix is not None and RAG_EMBEDDING_PREFIX_FIELD_NAME is None:
        if isinstance(text, list):
            text = [f"{prefix}{text_element}" for text_element in text]
        else:
            text = f"{prefix}{text}"

    texts_list = text if isinstance(text, list) else [text]
    is_single = isinstance(text, str)

    # Filter out empty/whitespace-only strings to prevent API errors
    non_empty_indices = []
    non_empty_texts = []
    for i, t in enumerate(texts_list):
        if t and t.strip():
            non_empty_indices.append(i)
            non_empty_texts.append(t)

    # If all texts are empty, return zero embeddings
    if not non_empty_texts:
        log.debug(f"[Embedding] All {len(texts_list)} texts empty, returning zeros")
        zero_embedding = [0.0] * 1536
        return zero_embedding if is_single else [zero_embedding] * len(texts_list)

    try:
        if engine == "ollama":
            non_empty_embeddings = await embedding_with_retry(
                embedding_func=agenerate_ollama_batch_embeddings,
                texts=non_empty_texts,
                model=model,
                url=url,
                key=key,
                prefix=prefix,
                user=user,
            )
        elif engine == "openai":
            non_empty_embeddings = await embedding_with_retry(
                embedding_func=agenerate_openai_batch_embeddings,
                texts=non_empty_texts,
                model=model,
                url=url,
                key=key,
                prefix=prefix,
                user=user,
            )
        elif engine == "azure_openai":
            azure_api_version = kwargs.get("azure_api_version", "")
            non_empty_embeddings = await embedding_with_retry(
                embedding_func=agenerate_azure_openai_batch_embeddings,
                texts=non_empty_texts,
                model=model,
                url=url,
                key=key,
                version=azure_api_version,
                prefix=prefix,
                user=user,
            )
        else:
            raise EmbeddingError(f"Unknown embedding engine: {engine}")

        # Reconstruct full embeddings list with zeros for empty texts
        if len(non_empty_texts) == len(texts_list):
            # No empty texts, return as-is
            embeddings = non_empty_embeddings
        else:
            # Get embedding dimension from first non-empty result
            embedding_dim = len(non_empty_embeddings[0]) if non_empty_embeddings else 1536
            zero_embedding = [0.0] * embedding_dim

            # Reconstruct full list with zeros for empty indices
            embeddings = []
            non_empty_idx = 0
            for i in range(len(texts_list)):
                if i in non_empty_indices:
                    embeddings.append(non_empty_embeddings[non_empty_idx])
                    non_empty_idx += 1
                else:
                    embeddings.append(zero_embedding)

            log.debug(
                f"[Embedding] Reconstructed {len(embeddings)} embeddings "
                f"({len(non_empty_texts)} real, {len(texts_list) - len(non_empty_texts)} zeros)"
            )

        return embeddings[0] if is_single else embeddings

    except EmbeddingError:
        # Re-raise embedding errors as-is
        raise
    except Exception as e:
        log.exception(f"Unexpected error in generate_embeddings: {e}")
        raise EmbeddingError(f"Failed to generate embeddings: {e}") from e


def get_reranking_function(reranking_engine, reranking_model, reranking_function, reranking_batch_size=32):
    if reranking_function is None:
        return None
    if reranking_engine == "external":
        return lambda query, documents, user=None: reranking_function.predict(
            [(query, doc.page_content) for doc in documents], user=user
        )
    else:
        return lambda query, documents, user=None: reranking_function.predict(
            [(query, doc.page_content) for doc in documents], batch_size=int(reranking_batch_size)
        )


async def filter_accessible_collections(
    collection_names: set[str],
    user: UserModel,
    access_type: str = 'read',
) -> set[str]:
    """
    Return only the collection names the user is allowed to access.
    Admins bypass all checks.  For non-admins the policy is:

      - file-*          → validated via has_access_to_file
      - user-memory-*   → must match user's own memory collection
      - web-search-*    → ephemeral per-query collections, always allowed
      - knowledge-bases → always denied (system meta-collection)
      - everything else → if the name matches a knowledge base, validated
                          via Knowledges.check_access_by_user_id; if no
                          such KB exists, the name is treated as an
                          ephemeral/legacy collection and allowed
    """
    if user.role == 'admin':
        return collection_names

    validated = set()
    for name in collection_names:
        if name == 'knowledge-bases':
            # System meta-collection — never exposed to non-admins.
            continue
        elif name.startswith('file-'):
            file_id = name[len('file-') :]
            if await has_access_to_file(file_id=file_id, access_type=access_type, user=user):
                validated.add(name)
        elif name.startswith('user-memory-'):
            if name == f'user-memory-{user.id}':
                validated.add(name)
        elif name.startswith('web-search-'):
            # Ephemeral collections created by process_web_search — safe
            # to allow because they contain only transient web-search
            # results scoped to the requesting user's session.
            validated.add(name)
        else:
            # May be a knowledge-base ID or a legacy/ephemeral collection.
            # If it IS a KB, enforce access control.  If no such KB
            # exists, treat it as a non-sensitive collection (e.g. legacy
            # model knowledge, process_text SHA256 collections) and allow.
            if await Knowledges.check_access_by_user_id(name, user.id, permission=access_type):
                validated.add(name)
            elif not await Knowledges.get_knowledge_by_id(name):
                # Not a KB at all — legacy/ephemeral collection, allow
                validated.add(name)
    return validated


async def get_sources_from_items(
    request,
    items,
    queries,
    embedding_function,
    k,
    reranking_function,
    k_reranker,
    r,
    hybrid_bm25_weight,
    hybrid_search,
    full_context=False,
    enable_reranking=True,
    user: Optional[UserModel] = None,
    per_knowledge_settings: Optional[dict] = None,
    base_settings: Optional[dict] = None,
):
    log.debug(
        f"items: {items} {queries} {embedding_function} {reranking_function} {full_context}"
    )

    extracted_collections = []
    query_results = []

    for item in items:
        query_result = None
        collection_names = []

        if item.get("type") == "text":
            # Raw Text
            # Used during temporary chat file uploads or web page & youtube attachements

            if item.get("context") == "full":
                if item.get("file"):
                    # if item has file data, use it
                    query_result = {
                        "documents": [
                            [item.get("file", {}).get("data", {}).get("content")]
                        ],
                        "metadatas": [[item.get("file", {}).get("meta", {})]],
                    }

            if query_result is None:
                # Fallback
                if item.get("collection_name"):
                    # If item has a collection name, use it
                    collection_names.append(item.get("collection_name"))
                elif item.get("file"):
                    # If item has file data, use it
                    query_result = {
                        "documents": [
                            [item.get("file", {}).get("data", {}).get("content")]
                        ],
                        "metadatas": [[item.get("file", {}).get("meta", {})]],
                    }
                else:
                    # Fallback to item content
                    query_result = {
                        "documents": [[item.get("content")]],
                        "metadatas": [
                            [{"file_id": item.get("id"), "name": item.get("name")}]
                        ],
                    }

        elif item.get("type") == "note":
            # Note Attached
            note = await Notes.get_note_by_id(item.get('id'))

            if note and (
                user.role == "admin"
                or note.user_id == user.id
                or await AccessGrants.has_access(
                    user_id=user.id,
                    resource_type="note",
                    resource_id=note.id,
                    permission="read",
                )
            ):
                # User has access to the note
                query_result = {
                    "documents": [[note.data.get("content", {}).get("md", "")]],
                    "metadatas": [[{"file_id": note.id, "name": note.title}]],
                }

        elif item.get("type") == "chat":
            # Chat Attached
            chat = await Chats.get_chat_by_id(item.get('id'))

            if chat and (user.role == "admin" or chat.user_id == user.id):
                messages_map = chat.chat.get("history", {}).get("messages", {})
                message_id = chat.chat.get("history", {}).get("currentId")

                if messages_map and message_id:
                    # Reconstruct the message list in order
                    message_list = get_message_list(messages_map, message_id)
                    message_history = "\n".join(
                        [
                            f"#### {m.get('role', 'user').capitalize()}\n{m.get('content')}\n"
                            for m in message_list
                        ]
                    )

                    # User has access to the chat
                    query_result = {
                        "documents": [[message_history]],
                        "metadatas": [[{"file_id": chat.id, "name": chat.title}]],
                    }

        elif item.get("type") == "url":
            content, docs = get_content_from_url(request, item.get("url"))
            if docs:
                query_result = {
                    "documents": [[content]],
                    "metadatas": [[{"url": item.get("url"), "name": item.get("url")}]],
                }
        elif item.get("type") == "file":
            if (
                item.get("context") == "full"
                or request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
            ):
                if item.get("file", {}).get("data", {}).get("content", ""):
                    # Manual Full Mode Toggle
                    # Used from chat file modal, we can assume that the file content will be available from item.get("file").get("data", {}).get("content")
                    query_result = {
                        "documents": [
                            [item.get("file", {}).get("data", {}).get("content", "")]
                        ],
                        "metadatas": [
                            [
                                {
                                    "file_id": item.get("id"),
                                    "name": item.get("name"),
                                    **item.get("file")
                                    .get("data", {})
                                    .get("metadata", {}),
                                }
                            ]
                        ],
                    }
                elif item.get('id'):
                    file_object = await Files.get_file_by_id(item.get('id'))
                    if file_object and (
                        user.role == 'admin'
                        or file_object.user_id == user.id
                        or await has_access_to_file(item.get('id'), 'read', user)
                    ):
                        query_result = {
                            "documents": [[file_object.data.get("content", "")]],
                            "metadatas": [
                                [
                                    {
                                        "file_id": item.get("id"),
                                        "name": file_object.filename,
                                        "source": file_object.filename,
                                    }
                                ]
                            ],
                        }
            else:
                # Fallback to collection names
                if item.get("legacy"):
                    collection_names.append(f"{item['id']}")
                else:
                    collection_names.append(f"file-{item['id']}")

        elif item.get('type') == 'collection':
            # Knowledge Base Collection
            knowledge_id = item.get('id')
            knowledge_base = await Knowledges.get_knowledge_by_id(knowledge_id)

            if knowledge_base and (
                user.role == "admin"
                or knowledge_base.user_id == user.id
                or await AccessGrants.has_access(
                    user_id=user.id,
                    resource_type="knowledge",
                    resource_id=knowledge_base.id,
                    permission="read",
                )
            ):
                # Get per-KB settings FIRST - BEFORE deciding which branch to take
                # This ensures each KB's full_context setting is respected independently
                kb_settings = {}
                if per_knowledge_settings and knowledge_id in per_knowledge_settings:
                    kb_settings = per_knowledge_settings[knowledge_id]
                    log.debug(f"Using per-KB settings for {knowledge_id}: {kb_settings}")

                # Determine effective full_context for THIS KB specifically:
                # Priority: UI toggle > per-KB setting > function parameter default
                ui_full_context = item.get("context") == "full"
                kb_full_context = kb_settings.get("full_context")  # None if not set

                # UI toggle overrides everything; otherwise use KB setting; otherwise use default
                if ui_full_context:
                    effective_full_context = True
                elif kb_full_context is not None:
                    effective_full_context = kb_full_context
                else:
                    effective_full_context = full_context

                # Compute ALL effective parameters for this KB
                effective_r = kb_settings.get("relevance_threshold", r)
                effective_k = kb_settings.get("top_k", k)
                effective_k_reranker = kb_settings.get("top_k_reranker", k_reranker)
                effective_hybrid_search = kb_settings.get("enable_hybrid_search", hybrid_search)
                effective_hybrid_bm25_weight = kb_settings.get("hybrid_bm25_weight", hybrid_bm25_weight)
                effective_enable_reranking = kb_settings.get("enable_reranking", enable_reranking)

                # Log ALL retrieval parameters for this KB
                log.info(
                    f"=== KB RETRIEVAL START: {knowledge_base.name} ({knowledge_id}) ===\n"
                    f"  FULL_CONTEXT: ui_toggle={ui_full_context}, kb_setting={kb_full_context}, "
                    f"global_param={full_context}, EFFECTIVE={effective_full_context}\n"
                    f"  OTHER PARAMS: k={effective_k}, k_reranker={effective_k_reranker}, "
                    f"r={effective_r}, hybrid={effective_hybrid_search}, bm25_weight={effective_hybrid_bm25_weight}, "
                    f"reranking={effective_enable_reranking}\n"
                    f"  RAW kb_settings={kb_settings}"
                )

                if (
                    effective_full_context
                    or request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
                ):
                    if knowledge_base and (
                        user.role == "admin"
                        or knowledge_base.user_id == user.id
                        or await AccessGrants.has_access(
                            user_id=user.id,
                            resource_type="knowledge",
                            resource_id=knowledge_base.id,
                            permission="read",
                        )
                    ):
                        files = await Knowledges.get_files_by_id(knowledge_base.id)

                        documents = []
                        metadatas = []
                        for file in files:
                            documents.append(file.data.get("content", ""))
                            metadatas.append(
                                {
                                    "file_id": file.id,
                                    "name": file.filename,
                                    "source": file.filename,
                                }
                            )

                        query_result = {
                            "documents": [documents],
                            "metadatas": [metadatas],
                        }
                else:
                    # Vector search mode - query this KB independently with its own settings
                    if item.get("legacy"):
                        kb_collection_names = item.get("collection_names", [])
                    else:
                        kb_collection_names = [knowledge_id]

                    # Query this KB's collections with its own settings
                    kb_collection_names_set = set(kb_collection_names).difference(extracted_collections)
                    if kb_collection_names_set:
                        try:
                            if effective_hybrid_search:
                                query_result = await query_collection_with_hybrid_search(
                                    collection_names=list(kb_collection_names_set),
                                    queries=queries,
                                    embedding_function=embedding_function,
                                    k=effective_k,
                                    reranking_function=reranking_function,
                                    k_reranker=effective_k_reranker,
                                    r=effective_r,
                                    hybrid_bm25_weight=effective_hybrid_bm25_weight,
                                    enable_enriched_texts=request.app.state.config.ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS,
                                    enable_reranking=effective_enable_reranking,
                                )
                            else:
                                query_result = await query_collection(
                                    collection_names=list(kb_collection_names_set),
                                    queries=queries,
                                    embedding_function=embedding_function,
                                    k=effective_k,
                                )
                                # Apply relevance filtering for non-hybrid search
                                if query_result and effective_r and effective_r > 0:
                                    query_result = filter_results_by_relevance(query_result, effective_r)

                            extracted_collections.extend(kb_collection_names_set)
                        except Exception as e:
                            log.exception(f"Error querying KB {knowledge_id}: {e}")

                    # Skip the generic collection processing below since we handled it here
                    if query_result:
                        if "data" in item:
                            del item["data"]
                        query_results.append({**query_result, "file": item})
                    continue

        elif item.get("docs"):
            # BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
            query_result = {
                "documents": [[doc.get("content") for doc in item.get("docs")]],
                "metadatas": [[doc.get("metadata") for doc in item.get("docs")]],
            }
        elif item.get("collection_name"):
            # Direct Collection Name
            collection_names.append(item["collection_name"])
        elif item.get("collection_names"):
            # Collection Names List
            collection_names.extend(item["collection_names"])

        # If query_result is None
        # Fallback to collection names and vector search the collections
        if query_result is None and collection_names:
            collection_names = set(collection_names).difference(extracted_collections)
            if not collection_names:
                log.debug(f"skipping {item} as it has already been extracted")
                continue

            # Filter out collections the user cannot read
            if user:
                collection_names = await filter_accessible_collections(collection_names, user)
                if not collection_names:
                    log.debug(f'access denied for all collections in item {item}')
                    continue

            try:
                if full_context:
                    # Sync helper makes blocking VECTOR_DB_CLIENT calls;
                    # offload so the async caller's event loop stays free.
                    query_result = await asyncio.to_thread(get_all_items_from_collections, collection_names)
                else:
                    if hybrid_search:
                        query_result = await query_collection_with_hybrid_search(
                            collection_names=collection_names,
                            queries=queries,
                            embedding_function=embedding_function,
                            k=k,
                            reranking_function=reranking_function,
                            k_reranker=k_reranker,
                            r=r,
                            hybrid_bm25_weight=hybrid_bm25_weight,
                            enable_enriched_texts=request.app.state.config.ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS,
                            enable_reranking=enable_reranking,
                        )
                    else:
                        query_result = await query_collection(
                            collection_names=collection_names,
                            queries=queries,
                            embedding_function=embedding_function,
                            k=k,
                        )
            except Exception as e:
                log.exception(e)

            extracted_collections.extend(collection_names)

        if query_result:
            if "data" in item:
                del item["data"]
            query_results.append({**query_result, "file": item})

    sources = []
    for query_result in query_results:
        try:
            if "documents" in query_result:
                if "metadatas" in query_result:
                    source = {
                        "source": query_result["file"],
                        "document": query_result["documents"][0],
                        "metadata": query_result["metadatas"][0],
                    }
                    if "distances" in query_result and query_result["distances"]:
                        source["distances"] = query_result["distances"][0]

                    sources.append(source)
        except Exception as e:
            log.exception(e)
    return sources


async def get_sources_from_items_with_settings(
    request,
    items,
    queries,
    embedding_function,
    reranking_function,
    settings: RAGQuerySettings,
    user: Optional[UserModel] = None,
    per_knowledge_settings: Optional[dict[str, RAGQuerySettings]] = None,
):
    """
    Retrieve sources from items using unified RAGQuerySettings.

    This is the new interface that accepts a RAGQuerySettings object instead of
    individual parameters. It delegates to the existing implementation.

    Args:
        request: FastAPI request object
        items: List of items to retrieve sources from
        queries: List of search queries
        embedding_function: Function to generate embeddings
        reranking_function: Function to rerank results (can be None)
        settings: Unified RAG query settings (base/global settings)
        user: Optional user model for access control
        per_knowledge_settings: Optional dict mapping knowledge_id to RAGQuerySettings overrides

    Returns:
        List of source dicts with 'source', 'document', 'metadata', 'distances' keys
    """
    # Convert per_knowledge_settings from RAGQuerySettings to dict format for backward compat
    per_kb_dict = None
    if per_knowledge_settings:
        per_kb_dict = {
            kb_id: kb_settings.model_dump() if isinstance(kb_settings, RAGQuerySettings) else kb_settings
            for kb_id, kb_settings in per_knowledge_settings.items()
        }

    return await get_sources_from_items(
        request=request,
        items=items,
        queries=queries,
        embedding_function=embedding_function,
        k=settings.top_k,
        reranking_function=reranking_function,
        k_reranker=settings.top_k_reranker,
        r=settings.relevance_threshold,
        hybrid_bm25_weight=settings.hybrid_bm25_weight,
        hybrid_search=settings.enable_hybrid_search,
        full_context=settings.full_context,
        enable_reranking=settings.enable_reranking,
        user=user,
        per_knowledge_settings=per_kb_dict,
        base_settings=settings.model_dump(),
    )


def get_model_path(model: str, update_model: bool = False):
    # Construct huggingface_hub kwargs with local_files_only to return the snapshot path
    cache_dir = os.getenv("SENTENCE_TRANSFORMERS_HOME")

    local_files_only = not update_model

    if OFFLINE_MODE:
        local_files_only = True

    snapshot_kwargs = {
        "cache_dir": cache_dir,
        "local_files_only": local_files_only,
    }

    log.debug(f"model: {model}")
    log.debug(f"snapshot_kwargs: {snapshot_kwargs}")

    # Inspiration from upstream sentence_transformers
    if (
        os.path.exists(model)
        or ("\\" in model or model.count("/") > 1)
        and local_files_only
    ):
        # If fully qualified path exists, return input, else set repo_id
        return model
    elif "/" not in model:
        # Set valid repo_id for model short-name
        model = "sentence-transformers" + "/" + model

    snapshot_kwargs["repo_id"] = model

    # Attempt to query the huggingface_hub library to determine the local path and/or to update
    try:
        model_repo_path = snapshot_download(**snapshot_kwargs)
        log.debug(f"model_repo_path: {model_repo_path}")
        return model_repo_path
    except Exception as e:
        log.exception(f"Cannot determine model snapshot path: {e}")
        if OFFLINE_MODE:
            raise
        return model


import operator
from typing import Optional, Sequence

from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document


class RerankCompressor(BaseDocumentCompressor):
    embedding_function: Any
    top_n: int
    reranking_function: Any
    r_score: float
    enable_reranking: bool = True  # When False, pass through with original ensemble scores

    class Config:
        extra = "forbid"
        arbitrary_types_allowed = True

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        """Compress retrieved documents given the query context.

        Args:
            documents: The retrieved documents.
            query: The query context.
            callbacks: Optional callbacks to run during compression.

        Returns:
            The compressed documents.

        """
        return []

    async def acompress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        # If reranking is disabled, pass through documents with original scores
        if not self.enable_reranking:
            log.debug(f"[HYBRID_DEBUG] === RERANKING DISABLED - PASS-THROUGH ===")
            log.debug(f"[HYBRID_DEBUG] Returning top {self.top_n} documents with original scores")

            # Pass through documents preserving existing scores from vector search,
            # or assign rank-based scores for BM25-only results
            result_docs = []
            docs_to_process = list(documents[: self.top_n])
            total_docs = len(docs_to_process)

            for idx, doc in enumerate(docs_to_process):
                metadata = doc.metadata.copy()
                # If document has a score from vector search, use it
                # Otherwise, assign a rank-based score (higher rank = higher score)
                if "score" not in metadata or metadata["score"] is None:
                    # Rank-based score: position 0 gets 1.0, position n gets decreasing score
                    # Using formula: 1 / (rank + 1) to mimic RRF-style scoring
                    metadata["score"] = 1.0 / (idx + 1)
                    log.debug(f"[HYBRID_DEBUG]   Pass-through #{idx+1}: assigned rank-based score={metadata['score']:.4f}")
                else:
                    log.debug(f"[HYBRID_DEBUG]   Pass-through #{idx+1}: preserved original score={metadata['score']:.4f}")

                result_docs.append(Document(
                    page_content=doc.page_content,
                    metadata=metadata
                ))

            return result_docs

        reranking = self.reranking_function is not None

        log.debug(f"[HYBRID_DEBUG] === RERANKING/SCORING START ===")
        log.debug(f"[HYBRID_DEBUG] Reranking function: {'YES' if reranking else 'NO (using cosine similarity)'}")
        log.debug(f"[HYBRID_DEBUG] Documents to score: {len(documents)}")
        log.debug(f"[HYBRID_DEBUG] Top N to return: {self.top_n}")
        log.debug(f"[HYBRID_DEBUG] Relevance threshold (r_score): {self.r_score}")

        # Filter out documents with empty/whitespace-only content to prevent embedding errors
        original_count = len(documents)
        documents = [doc for doc in documents if doc.page_content and doc.page_content.strip()]
        if len(documents) < original_count:
            log.warning(
                f"[HYBRID_DEBUG] Filtered out {original_count - len(documents)} empty documents "
                f"(remaining: {len(documents)})"
            )

        # If no valid documents remain, return empty list
        if not documents:
            log.warning("[HYBRID_DEBUG] No valid documents after filtering empty content")
            return []

        # Log incoming documents from ensemble (before reranking)
        log.debug(f"[HYBRID_DEBUG] Documents from Ensemble (before reranking):")
        for idx, doc in enumerate(documents[:10]):
            doc_preview = doc.page_content[:80].replace('\n', ' ') if doc.page_content else 'N/A'
            source = doc.metadata.get('source', doc.metadata.get('name', 'unknown'))
            log.debug(f"[HYBRID_DEBUG]   Ensemble #{idx+1}: source={source}, preview='{doc_preview}...'")

        scores = None
        if reranking:
            scores = await asyncio.to_thread(self.reranking_function, query, documents)
        else:
            from sentence_transformers import util

            query_embedding = await self.embedding_function(
                query, RAG_EMBEDDING_QUERY_PREFIX
            )
            document_embedding = await self.embedding_function(
                [doc.page_content for doc in documents], RAG_EMBEDDING_CONTENT_PREFIX
            )
            scores = util.cos_sim(query_embedding, document_embedding)[0]

        if scores is not None:
            docs_with_scores = list(
                zip(
                    documents,
                    scores.tolist() if not isinstance(scores, list) else scores,
                )
            )

            # Log all scores before filtering
            log.debug(f"[HYBRID_DEBUG] Reranking/Similarity Scores (before r_score filter):")
            sorted_for_log = sorted(docs_with_scores, key=lambda x: x[1], reverse=True)
            for idx, (doc, score) in enumerate(sorted_for_log[:10]):
                doc_preview = doc.page_content[:80].replace('\n', ' ') if doc.page_content else 'N/A'
                source = doc.metadata.get('source', doc.metadata.get('name', 'unknown'))
                log.debug(f"[HYBRID_DEBUG]   Rerank #{idx+1}: score={score:.4f}, source={source}, preview='{doc_preview}...'")

            if self.r_score:
                before_count = len(docs_with_scores)
                docs_with_scores = [
                    (d, s) for d, s in docs_with_scores if s >= self.r_score
                ]
                after_count = len(docs_with_scores)
                log.debug(f"[HYBRID_DEBUG] Relevance filter: {before_count} -> {after_count} docs (threshold={self.r_score})")

            result = sorted(docs_with_scores, key=operator.itemgetter(1), reverse=True)
            final_results = []
            for doc, doc_score in result[: self.top_n]:
                metadata = doc.metadata
                metadata["score"] = doc_score
                doc = Document(
                    page_content=doc.page_content,
                    metadata=metadata,
                )
                final_results.append(doc)

            # Log final results
            log.debug(f"[HYBRID_DEBUG] === FINAL RESULTS ({len(final_results)} docs) ===")
            for idx, doc in enumerate(final_results):
                doc_preview = doc.page_content[:80].replace('\n', ' ') if doc.page_content else 'N/A'
                source = doc.metadata.get('source', doc.metadata.get('name', 'unknown'))
                score = doc.metadata.get('score', 'N/A')
                score_str = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
                log.debug(f"[HYBRID_DEBUG]   Final #{idx+1}: score={score_str}, source={source}, preview='{doc_preview}...'")

            return final_results
        else:
            log.warning(
                "No valid scores found, check your reranking function. Returning original documents."
            )
            return documents
