from __future__ import annotations

import asyncio
import gc
import hashlib
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Optional, Union
from urllib.parse import quote

import aiohttp
import requests
from huggingface_hub import snapshot_download
from langchain_classic.retrievers import (
    ContextualCompressionRetriever,
    EnsembleRetriever,
)
# Note: We use the custom ScoringBM25Retriever below instead of langchain's
# BM25Retriever so BM25 scores are exposed in document metadata (needed for
# relevance thresholds, display, and citation keyword highlighting).
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
from open_webui.config import (
    RAG_EMBEDDING_CONTENT_PREFIX,
    RAG_EMBEDDING_PREFIX_FIELD_NAME,
    RAG_EMBEDDING_QUERY_PREFIX,
    VECTOR_DB,
)
from open_webui.env import (
    AIOHTTP_CLIENT_ALLOW_REDIRECTS,
    AIOHTTP_CLIENT_SESSION_SSL,
    AIOHTTP_CLIENT_TIMEOUT,
    BYPASS_RETRIEVAL_ACCESS_CONTROL,
    EMBEDDING_MAX_RETRIES,
    EMBEDDING_RETRY_BACKOFF_FACTOR,
    EMBEDDING_RETRY_INITIAL_DELAY,
    EMBEDDING_RETRY_MAX_DELAY,
    ENABLE_FORWARD_USER_INFO_HEADERS,
    ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS,
    OFFLINE_MODE,
)
from open_webui.models.access_grants import AccessGrants
from open_webui.models.chats import Chats
from open_webui.models.files import Files
from open_webui.models.folders import Folders
from open_webui.models.knowledge import Knowledges
from open_webui.models.notes import Notes
from open_webui.models.config import Config
from open_webui.models.users import UserModel
from open_webui.retrieval.loaders.youtube import YoutubeLoader
# FORK: unified RAG settings model (per-KB / per-query settings overlay)
from open_webui.retrieval.models import RAGQuerySettings
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.retrieval.external import retrieve_external_knowledge
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.retrieval.vector.main import GetResult, SearchResult
from open_webui.retrieval.web.utils import get_web_loader
from open_webui.utils.access_control.files import get_owner_accessible_folder_files, has_access_to_file
from open_webui.utils.access_control.folders import has_folder_access
from open_webui.utils.headers import include_user_info_headers
from open_webui.utils.misc import get_content_from_message, get_message_list

log = logging.getLogger(__name__)


from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever


####################
# FORK: RAG settings merge + BM25 helpers
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
        'top_k',
        'top_k_reranker',
        'relevance_threshold',
        'enable_hybrid_search',
        'hybrid_bm25_weight',
        'full_context',
    ]

    for settings in settings_dicts:
        if settings is None:
            continue
        for key in rag_keys:
            if key in settings and settings[key] is not None:
                merged[key] = settings[key]

    return merged


####################
# BM25 tokenization
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
    text = text.lower()
    tokens = text.split()

    # Strip punctuation from token boundaries; keep internal characters
    # (e.g. hyphenated words, decimal numbers). \w matches [a-zA-Z0-9_] plus
    # Unicode letters (umlauts etc.).
    cleaned = []
    for token in tokens:
        cleaned_token = re.sub(r'^[^\w]+|[^\w]+$', '', token, flags=re.UNICODE)
        if cleaned_token:
            cleaned.append(cleaned_token)

    return cleaned


def extract_matched_keywords(query: str, document_text: str) -> list[str]:
    """
    Extract which BM25 query tokens matched in the document.

    Used for keyword highlighting in the citation UI.

    Args:
        query: User query string
        document_text: Document content to check against

    Returns:
        List of matched keyword tokens (lowercased), in original query order
    """
    query_tokens = tokenize_for_bm25(query)
    document_tokens = set(tokenize_for_bm25(document_text))

    matched = []
    seen = set()
    for token in query_tokens:
        if token in document_tokens and token not in seen:
            matched.append(token)
            seen.add(token)

    return matched


class EmbeddingError(Exception):
    """Custom exception for embedding generation errors."""

    pass


class PartialEmbeddingError(EmbeddingError):
    """Exception raised when API returns fewer embeddings than requested."""

    def __init__(self, expected: int, received: int, embeddings: list = None):
        self.expected = expected
        self.received = received
        self.embeddings = embeddings or []
        super().__init__(f'Expected {expected} embeddings, received {received}')


class RateLimitError(EmbeddingError):
    """Exception raised when API rate limit (429) is hit."""

    def __init__(self, retry_after: float = 1.0, message: str = 'Rate limited'):
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
    **kwargs,
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
        if tracker and tracker.is_cancelled():
            log.info(f'[Embedding] Cancelled at retry attempt {attempt}')
            raise ProcessingCancelledException('Processing cancelled during embedding retry')

        try:
            if attempt > 0:
                log.warning(f'[Embedding] Retry {attempt}/{max_retries} after {delay:.1f}s')
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)

            result = await embedding_func(texts=texts, **kwargs)

            if result is None:
                last_error = EmbeddingError('API returned None (likely rate limit or connection issue)')
                continue

            if len(result) != expected_count:
                raise PartialEmbeddingError(expected=expected_count, received=len(result), embeddings=result)

            return result

        except PartialEmbeddingError as e:
            last_error = e
            log.warning(f'[Embedding] Partial result: {e.received}/{e.expected}')

        except RateLimitError as e:
            last_error = e
            delay = min(e.retry_after, max_delay)
            log.warning(f'[Embedding] Rate limited, waiting {e.retry_after:.1f}s')

        except EmbeddingError:
            raise

        except aiohttp.ClientError as e:
            last_error = EmbeddingError(f'Connection error: {e}')
            log.warning(f'[Embedding] Connection error: {type(e).__name__}')

        except asyncio.TimeoutError:
            last_error = EmbeddingError('Timeout')
            log.warning('[Embedding] Request timeout')

        except Exception as e:
            log.exception(f'[Embedding] Unexpected error: {e}')
            raise EmbeddingError(f'Unexpected error: {e}') from e

    log.error(f'[Embedding] Failed after {max_retries + 1} attempts: {last_error}')
    raise last_error


def is_youtube_url(url: str) -> bool:
    youtube_regex = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
    return re.match(youtube_regex, url) is not None


LOADER_CONFIG_KEYS = {
    'youtube_language': 'rag.youtube_loader_language',
    'youtube_proxy_url': 'rag.youtube_loader_proxy_url',
    'web_loader_ssl_verification': 'web.loader.ssl_verification',
    'web_loader_concurrent_requests': 'web.loader.concurrent_requests',
    'web_search_trust_env': 'web.search.trust_env',
    'web_loader_engine': 'web.loader.engine',
    'web_loader_timeout': 'web.loader.timeout',
    'playwright_ws_url': 'web.loader.playwright_ws_url',
    'playwright_timeout': 'web.loader.playwright_timeout',
    'firecrawl_api_key': 'web.loader.firecrawl_api_key',
    'firecrawl_api_url': 'web.loader.firecrawl_api_url',
    'firecrawl_timeout': 'web.loader.firecrawl_timeout',
    'tavily_api_key': 'web.search.tavily_api_key',
    'tavily_extract_depth': 'web.search.tavily_extract_depth',
    'microsoft_web_iq_api_base_url': 'web.search.microsoft_web_iq_api_base_url',
    'microsoft_web_iq_api_key': 'web.search.microsoft_web_iq_api_key',
    'microsoft_web_iq_language': 'web.search.microsoft_web_iq_language',
    'external_web_loader_url': 'web.loader.external_web_loader_url',
    'external_web_loader_api_key': 'web.loader.external_web_loader_api_key',
    'CONTENT_EXTRACTION_ENGINE': 'rag.content_extraction_engine',
    'DATALAB_MARKER_API_KEY': 'rag.datalab_marker_api_key',
    'DATALAB_MARKER_API_BASE_URL': 'rag.datalab_marker_api_base_url',
    'DATALAB_MARKER_ADDITIONAL_CONFIG': 'rag.datalab_marker_additional_config',
    'DATALAB_MARKER_SKIP_CACHE': 'rag.datalab_marker_skip_cache',
    'DATALAB_MARKER_FORCE_OCR': 'rag.datalab_marker_force_ocr',
    'DATALAB_MARKER_PAGINATE': 'rag.datalab_marker_paginate',
    'DATALAB_MARKER_STRIP_EXISTING_OCR': 'rag.datalab_marker_strip_existing_ocr',
    'DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION': 'rag.datalab_marker_disable_image_extraction',
    'DATALAB_MARKER_FORMAT_LINES': 'rag.datalab_marker_format_lines',
    'DATALAB_MARKER_USE_LLM': 'rag.datalab_marker_use_llm',
    'DATALAB_MARKER_OUTPUT_FORMAT': 'rag.datalab_marker_output_format',
    'EXTERNAL_DOCUMENT_LOADER_URL': 'rag.external_document_loader_url',
    'EXTERNAL_DOCUMENT_LOADER_API_KEY': 'rag.external_document_loader_api_key',
    'EXTERNAL_DOCUMENT_LOADER_HEADERS': 'rag.external_document_loader_headers',
    'TIKA_SERVER_URL': 'rag.tika_server_url',
    'DOCLING_SERVER_URL': 'rag.docling_server_url',
    'DOCLING_API_KEY': 'rag.docling_api_key',
    'DOCLING_PARAMS': 'rag.docling_params',
    'PDF_EXTRACT_IMAGES': 'rag.pdf_extract_images',
    'PDF_LOADER_MODE': 'rag.pdf_loader_mode',
    'DOCUMENT_INTELLIGENCE_ENDPOINT': 'rag.document_intelligence_endpoint',
    'DOCUMENT_INTELLIGENCE_KEY': 'rag.document_intelligence_key',
    'DOCUMENT_INTELLIGENCE_MODEL': 'rag.document_intelligence_model',
    'MISTRAL_OCR_API_BASE_URL': 'rag.mistral_ocr_api_base_url',
    'MISTRAL_OCR_API_KEY': 'rag.mistral_ocr_api_key',
    'MISTRAL_OCR_USE_BASE64': 'rag.mistral_ocr_use_base64',
    'PADDLEOCR_VL_BASE_URL': 'rag.paddleocr_vl_base_url',
    'PADDLEOCR_VL_TOKEN': 'rag.paddleocr_vl_token',
    'MINERU_API_MODE': 'rag.mineru_api_mode',
    'MINERU_API_URL': 'rag.mineru_api_url',
    'MINERU_API_KEY': 'rag.mineru_api_key',
    'MINERU_API_TIMEOUT': 'rag.mineru_api_timeout',
    'MINERU_PARAMS': 'rag.mineru_params',
    'MINERU_FILE_EXTENSIONS': 'rag.mineru_file_extensions',
}


async def get_loader_config():
    values = await Config.get_many(*LOADER_CONFIG_KEYS.values())
    return {name: values.get(key) for name, key in LOADER_CONFIG_KEYS.items()}


def get_loader(request, url: str, config: dict):
    if is_youtube_url(url):
        return YoutubeLoader(
            url,
            language=config.get('youtube_language'),
            proxy_url=config.get('youtube_proxy_url'),
        )
    return get_web_loader(
        url,
        verify_ssl=config.get('web_loader_ssl_verification'),
        requests_per_second=config.get('web_loader_concurrent_requests'),
        trust_env=config.get('web_search_trust_env'),
        loader_config=config,
    )


def build_loader_from_config(request, config: dict):
    """Build a Loader instance with the admin's configured extraction engine settings."""
    from open_webui.retrieval.loaders.main import Loader

    loader_config = {key: config.get(key) for key in LOADER_CONFIG_KEYS if key.isupper()}
    return Loader(
        engine=loader_config['CONTENT_EXTRACTION_ENGINE'],
        **{key: value for key, value in loader_config.items() if key != 'CONTENT_EXTRACTION_ENGINE'},
    )


def _extract_text_from_binary_response(
    request, response: requests.Response, url: str, loader_config: dict
) -> tuple[str, list]:
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
        loader = build_loader_from_config(request, loader_config)
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


async def get_content_from_url(request, url: str) -> str:
    loader_config = await get_loader_config()

    # The rest of this function performs synchronous, blocking work: an SSRF-guarded
    # `requests` probe and a synchronous document loader (`loader.load()`). Run it in a
    # worker thread so the event loop stays free while waiting on network/parsing.
    return await asyncio.to_thread(_get_content_from_url_sync, request, url, loader_config)


def _get_content_from_url_sync(request, url: str, loader_config):
    from open_webui.retrieval.web.utils import validate_url, _SSRFSafeAdapter

    # Validate URL before making any request (blocks private IPs, non-HTTP, filter list)
    validate_url(url)

    # YouTube URLs (including youtu.be short links) should go straight to
    # YoutubeLoader, which uses youtube-transcript-api and never needs the
    # HTTP response body.  Probing the URL first is harmful for short URLs:
    # youtu.be returns a 303 redirect with Content-Type: application/binary
    # when allow_redirects=False, causing the binary-content path to run
    # and produce empty docs → HTTP 400.
    if is_youtube_url(url):
        loader = get_loader(request, url, loader_config)
        docs = loader.load()
        content = ' '.join([doc.page_content for doc in docs])
        return content, docs

    # Streamed GET to check Content-Type without downloading the body.
    # allow_redirects=False prevents redirect-based SSRF: validate_url() above is
    # called on the originally-submitted URL only; following 3xx redirects without
    # re-validation would let an attacker reach private IPs (RFC1918, loopback,
    # cloud-metadata 169.254.169.254) via a public host that redirects internally.
    try:
        # Probe through the connect-time SSRF guard; bare requests.get re-resolves (DNS-rebinding gap).
        session = requests.Session()
        session.mount('http://', _SSRFSafeAdapter())
        session.mount('https://', _SSRFSafeAdapter())
        response = session.get(url, stream=True, timeout=30, allow_redirects=AIOHTTP_CLIENT_ALLOW_REDIRECTS)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
    except Exception:
        content_type = ''
        response = None

    # Text / HTML / unknown — use the configured web loader
    if response is None or _is_text_content_type(content_type):
        if response is not None:
            response.close()
        loader = get_loader(request, url, loader_config)
        docs = loader.load()
        content = ' '.join([doc.page_content for doc in docs])
        return content, docs

    # Binary content (PDF, DOCX, XLSX, PPTX, etc.) — download and extract
    try:
        return _extract_text_from_binary_response(request, response, url, loader_config)
    finally:
        response.close()


CHUNK_HASH_KEY = '_chunk_hash'


def _content_hash(text: str) -> str:
    """SHA-256 hash of text, used as a stable chunk identifier for RRF dedup."""
    return hashlib.sha256(text.encode()).hexdigest()


class VectorSearchRetriever(BaseRetriever):
    collection_name: Any
    embedding_function: Any
    top_k: int

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
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
        embedding = await self.embedding_function(query, RAG_EMBEDDING_QUERY_PREFIX)
        result = await ASYNC_VECTOR_DB_CLIENT.search(
            collection_name=self.collection_name,
            vectors=[embedding],
            limit=self.top_k,
        )

        return _search_result_to_documents(result)


class ScoringBM25Retriever(BaseRetriever):
    """
    A BM25 retriever that stores normalized BM25 scores in document metadata.

    Unlike langchain's BM25Retriever, which doesn't expose scores, this retriever
    normalizes BM25 scores to the 0-1 range and stores them in metadata['score']
    for compatibility with relevance thresholds and display.
    """

    texts: list[str]
    metadatas: list[dict]
    bm25_scores: list[float]  # Pre-computed BM25 scores for all documents
    k: int = 4

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        """Sync version — returns empty as we use async."""
        return []

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """
        Return top-k documents with normalized BM25 scores in metadata.

        BM25 scores are normalized to the 0-1 range using min-max normalization
        so they are comparable with vector similarity scores for threshold filtering.
        """
        scored_docs = list(zip(self.bm25_scores, self.texts, self.metadatas))
        scored_docs_sorted = sorted(scored_docs, key=lambda x: x[0], reverse=True)
        top_k_docs = scored_docs_sorted[: self.k]

        if not top_k_docs:
            return []

        # Normalize scores to 0-1 range based on the top-k results.
        # No match = 0%, best match = 100%.
        scores_in_topk = [doc[0] for doc in top_k_docs]
        max_score = max(scores_in_topk) if scores_in_topk else 1.0

        results = []
        for bm25_score, text, metadata in top_k_docs:
            meta_copy = metadata.copy() if metadata else {}

            if bm25_score <= 0:
                normalized_score = 0.0
            elif max_score > 0:
                normalized_score = bm25_score / max_score
            else:
                normalized_score = 0.0

            meta_copy['score'] = normalized_score
            meta_copy['bm25_raw_score'] = bm25_score  # Keep raw score for debugging

            results.append(Document(page_content=text, metadata=meta_copy))

        return results

    @classmethod
    def from_texts_and_scores(
        cls,
        texts: list[str],
        metadatas: list[dict],
        bm25_scores: list[float],
        k: int = 4,
    ) -> 'ScoringBM25Retriever':
        """Create a ScoringBM25Retriever from texts, metadata, and pre-computed BM25 scores."""
        return cls(
            texts=texts,
            metadatas=metadatas,
            bm25_scores=bm25_scores,
            k=k,
        )


def query_doc(collection_name: str, query_embedding: list[float], k: int, user: UserModel = None):
    try:
        log.debug(f'query_doc:doc {collection_name}')
        result = VECTOR_DB_CLIENT.search(
            collection_name=collection_name,
            vectors=[query_embedding],
            limit=k,
        )

        if result:
            log.info(f'query_doc:result {result.ids} {result.metadatas}')

        return result
    except Exception as e:
        log.exception(f'Error querying doc {collection_name} with limit {k}: {e}')
        raise e


def get_doc(collection_name: str, user: UserModel = None):
    try:
        log.debug(f'get_doc:doc {collection_name}')
        result = VECTOR_DB_CLIENT.get(collection_name=collection_name)

        if result:
            log.info(f'query_doc:result {result.ids} {result.metadatas}')

        return result
    except Exception as e:
        log.exception(f'Error getting doc {collection_name}: {e}')
        raise e


def get_enriched_texts(collection_result: GetResult) -> list[str]:
    enriched_texts = []
    for idx, text in enumerate(collection_result.documents[0]):
        metadata = collection_result.metadatas[0][idx]
        metadata_parts = [text]

        # Add filename (repeat twice for extra weight in BM25 scoring)
        if metadata.get('name'):
            filename = metadata['name']
            filename_tokens = filename.replace('_', ' ').replace('-', ' ').replace('.', ' ')
            metadata_parts.append(f'Filename: {filename} {filename_tokens} {filename_tokens}')

        # Add title if available
        if metadata.get('title'):
            metadata_parts.append(f'Title: {metadata["title"]}')

        # Add document section headings if available (from markdown splitter)
        if metadata.get('headings') and isinstance(metadata['headings'], list):
            headings = ' > '.join(str(h) for h in metadata['headings'])
            metadata_parts.append(f'Section: {headings}')

        # Add source URL/path if available
        if metadata.get('source'):
            metadata_parts.append(f'Source: {metadata["source"]}')

        # Add snippet for web search results
        if metadata.get('snippet'):
            metadata_parts.append(f'Snippet: {metadata["snippet"]}')

        enriched_texts.append(' '.join(metadata_parts))

    return enriched_texts


def _search_result_to_documents(result: SearchResult | None) -> list[Document]:
    ids = result.ids[0] if result and result.ids else []
    metadatas = result.metadatas[0] if result and result.metadatas else []
    documents = result.documents[0] if result and result.documents else []
    distances = result.distances[0] if result and result.distances else []

    docs = []
    for idx in range(len(ids)):
        document = documents[idx]
        metadata = dict(metadatas[idx] or {})
        metadata[CHUNK_HASH_KEY] = _content_hash(document)
        if idx < len(distances):
            metadata.setdefault('score', distances[idx])
        docs.append(Document(metadata=metadata, page_content=document))
    return docs


def _supports_native_hybrid_search() -> bool:
    supports_hybrid_search = getattr(ASYNC_VECTOR_DB_CLIENT, 'supports_hybrid_search', None)
    if supports_hybrid_search is not None:
        return bool(supports_hybrid_search)
    return callable(getattr(ASYNC_VECTOR_DB_CLIENT, 'hybrid_search', None))


async def query_doc_with_native_hybrid_search(
    collection_name: str,
    query: str,
    embedding_function,
    k: int,
    reranking_function,
    k_reranker: int,
    r: float,
    hybrid_bm25_weight: float,
    enable_reranking: bool = True,
) -> Optional[dict]:
    try:
        if not _supports_native_hybrid_search():
            return None

        query_vectors = []
        if hybrid_bm25_weight < 1:
            query_vectors = [await embedding_function(query, RAG_EMBEDDING_QUERY_PREFIX)]

        result = await ASYNC_VECTOR_DB_CLIENT.hybrid_search(
            collection_name=collection_name,
            query=query,
            vectors=query_vectors,
            limit=k,
            hybrid_bm25_weight=hybrid_bm25_weight,
        )
        if result is None:
            return None

        documents = _search_result_to_documents(result)
        if not documents:
            return {'distances': [[]], 'documents': [[]], 'metadatas': [[]]}

        compressor = RerankCompressor(
            embedding_function=embedding_function,
            top_n=k_reranker,
            reranking_function=reranking_function,
            r_score=r,
            enable_reranking=enable_reranking,
        )
        compressed = await compressor.acompress_documents(documents, query)

        distances = [d.metadata.get('score') for d in compressed]
        documents = [d.page_content for d in compressed]
        metadatas = [d.metadata for d in compressed]

        if k < k_reranker:
            sorted_items = sorted(zip(distances, documents, metadatas), key=lambda x: x[0], reverse=True)
            sorted_items = sorted_items[:k]

            if sorted_items:
                distances, documents, metadatas = map(list, zip(*sorted_items))
            else:
                distances, documents, metadatas = [], [], []

        return {
            'distances': [distances],
            'documents': [documents],
            'metadatas': [metadatas],
        }
    except Exception as e:
        log.debug(f'Native hybrid search failed for {collection_name}, falling back to legacy hybrid search: {e}')
        return None


async def query_doc_with_hybrid_search(
    collection_name: str,
    collection_result: Optional[GetResult],
    query: str,
    embedding_function,
    k: int,
    reranking_function,
    k_reranker: int,
    r: float,
    hybrid_bm25_weight: float,
    enable_enriched_texts: bool = False,
    native_hybrid_search: bool = True,
    enable_reranking: bool = True,
) -> dict:
    try:
        if native_hybrid_search and not enable_enriched_texts:
            native_result = await query_doc_with_native_hybrid_search(
                collection_name=collection_name,
                query=query,
                embedding_function=embedding_function,
                k=k,
                reranking_function=reranking_function,
                k_reranker=k_reranker,
                r=r,
                hybrid_bm25_weight=hybrid_bm25_weight,
                enable_reranking=enable_reranking,
            )
            if native_result is not None:
                return native_result

        if collection_result is None:
            collection_result = await ASYNC_VECTOR_DB_CLIENT.get(collection_name=collection_name)

        # First check if collection_result has the required attributes
        if (
            not collection_result
            or not hasattr(collection_result, 'documents')
            or not hasattr(collection_result, 'metadatas')
        ):
            log.warning(f'query_doc_with_hybrid_search:no_docs {collection_name}')
            return {'documents': [], 'metadatas': [], 'distances': []}

        # Now safely check the documents content after confirming attributes exist
        if (
            not collection_result.documents
            or len(collection_result.documents) == 0
            or not collection_result.documents[0]
        ):
            log.warning(f'query_doc_with_hybrid_search:no_docs {collection_name}')
            return {'documents': [], 'metadatas': [], 'distances': []}

        log.debug(f'query_doc_with_hybrid_search:doc {collection_name}')

        original_texts = collection_result.documents[0]
        bm25_metadatas = [
            {**meta, CHUNK_HASH_KEY: _content_hash(original_texts[idx])}
            for idx, meta in enumerate(collection_result.metadatas[0])
        ]

        bm25_texts = get_enriched_texts(collection_result) if enable_enriched_texts else original_texts

        # Filter out empty/whitespace-only texts to prevent BM25Okapi/embedding errors,
        # keeping bm25_texts/bm25_metadatas aligned by index.
        valid_bm25_texts = []
        valid_bm25_metadatas = []
        for text, meta in zip(bm25_texts, bm25_metadatas):
            if text and text.strip():
                valid_bm25_texts.append(text)
                valid_bm25_metadatas.append(meta)

        if not valid_bm25_texts:
            log.warning(f'query_doc_with_hybrid_search:no_valid_docs {collection_name}')
            return {'documents': [], 'metadatas': [], 'distances': []}

        # Compute BM25 scores via rank_bm25 using the same tokenizer as
        # extract_matched_keywords, so scoring and citation highlighting agree.
        tokenized_docs = [tokenize_for_bm25(doc) for doc in valid_bm25_texts]
        bm25_index = BM25Okapi(tokenized_docs)
        bm25_scores = bm25_index.get_scores(tokenize_for_bm25(query))

        bm25_retriever = ScoringBM25Retriever.from_texts_and_scores(
            texts=valid_bm25_texts,
            metadatas=valid_bm25_metadatas,
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
            ensemble_retriever = EnsembleRetriever(
                retrievers=[vector_search_retriever],
                weights=[1.0],
                id_key=CHUNK_HASH_KEY,
            )
        elif hybrid_bm25_weight >= 1:
            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever],
                weights=[1.0],
                id_key=CHUNK_HASH_KEY,
            )
        else:
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

        # Record which BM25 query tokens matched each document, for citation highlighting.
        for doc in result:
            matched_keywords = extract_matched_keywords(query, doc.page_content)
            if matched_keywords:
                doc.metadata['bm25_matched_keywords'] = matched_keywords

        distances = [d.metadata.get('score') for d in result]
        documents = [d.page_content for d in result]
        metadatas = [d.metadata for d in result]

        # retrieve only min(k, k_reranker) items, sort and cut by distance if k < k_reranker
        if k < k_reranker:
            sorted_items = sorted(zip(distances, documents, metadatas), key=lambda x: x[0], reverse=True)
            sorted_items = sorted_items[:k]

            if sorted_items:
                distances, documents, metadatas = map(list, zip(*sorted_items))
            else:
                distances, documents, metadatas = [], [], []

        result = {
            'distances': [distances],
            'documents': [documents],
            'metadatas': [metadatas],
        }

        log.info('query_doc_with_hybrid_search:result ' + f'{result["metadatas"]} {result["distances"]}')
        return result
    except Exception as e:
        log.exception(f'Error querying doc {collection_name} with hybrid search: {e}')
        raise e


async def query_doc_with_hybrid_search_settings(
    collection_name: str,
    collection_result: Optional[GetResult],
    query: str,
    embedding_function,
    reranking_function,
    settings: RAGQuerySettings,
) -> dict:
    """
    Query a document collection using hybrid search with unified RAGQuerySettings.

    This is the settings-object interface; it delegates to query_doc_with_hybrid_search.

    Args:
        collection_name: Name of the vector collection
        collection_result: Pre-fetched collection data (may be None to fetch lazily)
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
        combined_documents.extend(data['documents'][0])
        combined_metadatas.extend(data['metadatas'][0])
        combined_ids.extend(data['ids'][0])

    # Create the output dictionary
    result = {
        'documents': [combined_documents],
        'metadatas': [combined_metadatas],
        'ids': [combined_ids],
    }

    return result


def merge_and_sort_query_results(query_results: list[dict], k: int) -> dict:
    # Initialize lists to store combined data
    combined = dict()  # To store documents with unique document hashes

    for data in query_results:
        if (
            len(data.get('distances', [])) == 0
            or len(data.get('documents', [])) == 0
            or len(data.get('metadatas', [])) == 0
        ):
            continue

        distances = data['distances'][0]
        documents = data['documents'][0]
        metadatas = data['metadatas'][0]

        for distance, document, metadata in zip(distances, documents, metadatas):
            if isinstance(document, str):
                doc_hash = (metadata or {}).get(CHUNK_HASH_KEY) or _content_hash(document)

                if doc_hash not in combined.keys():
                    # Copy metadata to avoid mutating the caller's original dict.
                    combined[doc_hash] = (distance, document, dict(metadata) if metadata else {})
                    continue  # if doc is new, no further comparison is needed

                existing_distance, existing_document, existing_metadata = combined[doc_hash]

                # bm25_matched_keywords comes from the hybrid-search path; preserve it
                # across dedup even if the winning (higher-score) result is from a
                # keyword-less vector-only result for the same document.
                keywords_to_preserve = None
                if metadata and metadata.get('bm25_matched_keywords'):
                    keywords_to_preserve = metadata['bm25_matched_keywords']
                elif existing_metadata and existing_metadata.get('bm25_matched_keywords'):
                    keywords_to_preserve = existing_metadata['bm25_matched_keywords']

                # Treat None distances (e.g. pure-BM25-only legacy paths) as 0 for
                # comparison so they never crash the '>' comparison below.
                dist_val = distance if distance is not None else 0
                existing_dist_val = existing_distance if existing_distance is not None else 0

                if dist_val > existing_dist_val:
                    merged_metadata = dict(metadata) if metadata else {}
                    if keywords_to_preserve and not merged_metadata.get('bm25_matched_keywords'):
                        merged_metadata['bm25_matched_keywords'] = keywords_to_preserve
                    combined[doc_hash] = (distance, document, merged_metadata)
                elif keywords_to_preserve and not existing_metadata.get('bm25_matched_keywords'):
                    # Keep the existing (higher-score) entry but backfill keywords.
                    existing_metadata['bm25_matched_keywords'] = keywords_to_preserve

    combined = list(combined.values())
    # Sort the list based on distances (None-safe: treat as 0)
    combined.sort(key=lambda x: x[0] if x[0] is not None else 0, reverse=True)

    # Slice to keep only the top k elements
    sorted_distances, sorted_documents, sorted_metadatas = zip(*combined[:k]) if combined else ([], [], [])

    # Create and return the output dictionary
    return {
        'distances': [list(sorted_distances)],
        'documents': [list(sorted_documents)],
        'metadatas': [list(sorted_metadatas)],
    }


def filter_results_by_relevance(query_result: dict, relevance_threshold: float) -> dict:
    """
    Filter query results by relevance threshold.
    Only keeps documents with distance/score >= relevance_threshold.

    Used for non-hybrid (pure vector) search paths, where
    query_doc_with_hybrid_search's RerankCompressor.r_score filtering doesn't apply.

    Args:
        query_result: Dict with 'distances', 'documents', 'metadatas' keys
        relevance_threshold: Minimum score to keep (0.0-1.0)

    Returns:
        Filtered query result dict
    """
    if not query_result or not relevance_threshold or relevance_threshold <= 0:
        return query_result

    distances = query_result.get('distances', [[]])[0]
    documents = query_result.get('documents', [[]])[0]
    metadatas = query_result.get('metadatas', [[]])[0]

    if not distances:
        return query_result

    filtered = [
        (d, doc, meta) for d, doc, meta in zip(distances, documents, metadatas) if d >= relevance_threshold
    ]

    if not filtered:
        return {
            'distances': [[]],
            'documents': [[]],
            'metadatas': [[]],
        }

    filtered_distances, filtered_documents, filtered_metadatas = zip(*filtered)

    return {
        'distances': [list(filtered_distances)],
        'documents': [list(filtered_documents)],
        'metadatas': [list(filtered_metadatas)],
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
                log.exception(f'Error when querying the collection: {e}')
        else:
            pass

    return merge_get_results(results)


async def query_collection(
    request,
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    k: int,
) -> dict:
    config = await Config.get_many(
        'rag.enable_hybrid_search',
        'rag.top_k_reranker',
        'rag.relevance_threshold',
        'rag.hybrid_bm25_weight',
        'rag.enable_hybrid_search_enriched_texts',
        'rag.enable_reranking',
    )
    # When request is provided, try hybrid search + reranking if enabled
    if request and config.get('rag.enable_hybrid_search'):
        try:
            reranking_function = (
                (lambda query, documents: request.app.state.RERANKING_FUNCTION(query, documents))
                if request.app.state.RERANKING_FUNCTION
                else None
            )
            return await query_collection_with_hybrid_search(
                collection_names=collection_names,
                queries=queries,
                embedding_function=embedding_function,
                k=k,
                reranking_function=reranking_function,
                k_reranker=config.get('rag.top_k_reranker'),
                r=config.get('rag.relevance_threshold'),
                hybrid_bm25_weight=config.get('rag.hybrid_bm25_weight'),
                enable_enriched_texts=config.get('rag.enable_hybrid_search_enriched_texts'),
                enable_reranking=config.get('rag.enable_reranking', True),
            )
        except Exception as e:
            log.debug(f'Hybrid search failed, falling back to vector search: {e}')

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
            log.exception(f'Error when querying the collection: {e}')
            return None, e

    # Sanitize: filter out None/empty queries to prevent embedding crashes
    # (e.g. when get_last_user_message returns None)
    queries = [q for q in queries if q]
    if not queries:
        log.warning('query_collection: all queries were None or empty, returning empty results')
        return {'distances': [[]], 'documents': [[]], 'metadatas': [[]]}

    try:
        # Generate all query embeddings (in one call)
        query_embeddings = await embedding_function(queries, prefix=RAG_EMBEDDING_QUERY_PREFIX)
        log.debug(f'query_collection: processing {len(queries)} queries across {len(collection_names)} collections')

        with ThreadPoolExecutor() as executor:
            future_results = []
            for query_embedding in query_embeddings:
                for collection_name in collection_names:
                    result = executor.submit(process_query_collection, collection_name, query_embedding)
                    future_results.append(result)
            task_results = [future.result() for future in future_results]

        for result, err in task_results:
            if err is not None:
                error = True
            elif result is not None:
                results.append(result)

        if error and not results:
            log.warning('All collection queries failed. No results returned.')

        return merge_and_sort_query_results(results, k=k)
    finally:
        # Clean up memory after RAG search to prevent accumulation across requests.
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

    try:
        if not enable_enriched_texts:

            async def process_native_query(collection_name, query):
                result = await query_doc_with_native_hybrid_search(
                    collection_name=collection_name,
                    query=query,
                    embedding_function=embedding_function,
                    k=k,
                    reranking_function=reranking_function,
                    k_reranker=k_reranker,
                    r=r,
                    hybrid_bm25_weight=hybrid_bm25_weight,
                    enable_reranking=enable_reranking,
                )
                return result

            native_task_results = await asyncio.gather(
                *[
                    process_native_query(collection_name, query)
                    for collection_name in collection_names
                    for query in queries
                ]
            )
            if native_task_results and all(result is not None for result in native_task_results):
                return merge_and_sort_query_results(native_task_results, k=k)

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
                return name, await ASYNC_VECTOR_DB_CLIENT.get(collection_name=name)
            except Exception as e:
                log.exception(f'Failed to fetch collection {name}: {e}')
                return name, None

        collection_results = dict(await asyncio.gather(*(_fetch_collection(name) for name in collection_names)))

        log.info(f'Starting hybrid search for {len(queries)} queries in {len(collection_names)} collections...')

        async def process_query(collection_name, query):
            try:
                result = await query_doc_with_hybrid_search(
                    collection_name=collection_name,
                    collection_result=collection_results[collection_name],
                    query=query,
                    embedding_function=embedding_function,
                    k=k,
                    reranking_function=reranking_function,
                    k_reranker=k_reranker,
                    r=r,
                    hybrid_bm25_weight=hybrid_bm25_weight,
                    enable_enriched_texts=enable_enriched_texts,
                    native_hybrid_search=False,
                    enable_reranking=enable_reranking,
                )
                return result, None
            except Exception as e:
                log.exception(f'Error when querying the collection with hybrid_search: {e}')
                return None, e

        # Prepare tasks for all collections and queries
        # Avoid running any tasks for collections that failed to fetch data (have assigned None)
        tasks = [
            (collection_name, query)
            for collection_name in collection_names
            if collection_results[collection_name] is not None
            for query in queries
        ]

        # Run all queries in parallel using asyncio.gather
        task_results = await asyncio.gather(
            *[process_query(collection_name, query) for collection_name, query in tasks]
        )

        for result, err in task_results:
            if err is not None:
                error = True
            elif result is not None:
                results.append(result)

        if error and not results:
            raise Exception('Hybrid search failed for all collections. Using Non-hybrid search as fallback.')

        return merge_and_sort_query_results(results, k=k)
    finally:
        # Clean up memory after hybrid search to prevent accumulation. This matters
        # especially for BM25, which builds an in-memory index per query.
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

    This is the settings-object interface; it delegates to query_collection_with_hybrid_search.

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
    url: str = 'https://api.openai.com/v1',
    key: str = '',
    prefix: str = None,
    user: UserModel = None,
) -> list[list[float]]:
    log.debug(f'generate_openai_batch_embeddings:model {model} batch size: {len(texts)}')
    json_data = {'input': texts, 'model': model}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    }
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    r = requests.post(
        f'{url}/embeddings',
        headers=headers,
        json=json_data,
    )
    r.raise_for_status()
    data = r.json()
    if 'data' in data:
        return [elem['embedding'] for elem in data['data']]
    else:
        raise ValueError("Unexpected OpenAI embeddings response: missing 'data' key")


async def agenerate_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str = 'https://api.openai.com/v1',
    key: str = '',
    prefix: str = None,
    user: UserModel = None,
) -> list[list[float]]:
    log.debug(f'agenerate_openai_batch_embeddings:model {model} batch size: {len(texts)}')
    form_data = {'input': texts, 'model': model}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        form_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    }
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    async with aiohttp.ClientSession(
        trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
    ) as session:
        async with session.post(
            f'{url}/embeddings',
            headers=headers,
            json=form_data,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as r:
            r.raise_for_status()
            data = await r.json()
            if 'data' in data:
                return [item['embedding'] for item in data['data']]
            else:
                raise ValueError("Unexpected OpenAI embeddings response: missing 'data' key")


def generate_azure_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = '',
    version: str = '',
    prefix: str = None,
    user: UserModel = None,
) -> list[list[float]]:
    log.debug(f'generate_azure_openai_batch_embeddings:deployment {model} batch size: {len(texts)}')
    json_data = {'input': texts}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    url = f'{url}/openai/deployments/{model}/embeddings?api-version={version}'

    for _ in range(5):
        headers = {
            'Content-Type': 'application/json',
            'api-key': key,
        }
        if ENABLE_FORWARD_USER_INFO_HEADERS and user:
            headers = include_user_info_headers(headers, user)

        r = requests.post(
            url,
            headers=headers,
            json=json_data,
        )
        if r.status_code == 429:
            retry = float(r.headers.get('Retry-After', '1'))
            time.sleep(retry)
            continue
        r.raise_for_status()
        data = r.json()
        if 'data' in data:
            return [elem['embedding'] for elem in data['data']]
        else:
            raise ValueError("Unexpected Azure OpenAI embeddings response: missing 'data' key")
    raise Exception('Azure OpenAI embedding request failed: max retries (429) exceeded')


async def agenerate_azure_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = '',
    version: str = '',
    prefix: str = None,
    user: UserModel = None,
) -> list[list[float]]:
    log.debug(f'agenerate_azure_openai_batch_embeddings:deployment {model} batch size: {len(texts)}')
    form_data = {'input': texts}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        form_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    full_url = f'{url}/openai/deployments/{model}/embeddings?api-version={version}'

    headers = {
        'Content-Type': 'application/json',
        'api-key': key,
    }
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    async with aiohttp.ClientSession(
        trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
    ) as session:
        async with session.post(
            full_url,
            headers=headers,
            json=form_data,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as r:
            r.raise_for_status()
            data = await r.json()
            if 'data' in data:
                return [item['embedding'] for item in data['data']]
            else:
                raise ValueError("Unexpected Azure OpenAI embeddings response: missing 'data' key")


def generate_ollama_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = '',
    prefix: str = None,
    user: UserModel = None,
) -> list[list[float]]:
    log.debug(f'generate_ollama_batch_embeddings:model {model} batch size: {len(texts)}')
    json_data = {'input': texts, 'model': model, 'truncate': True}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    }
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    r = requests.post(
        f'{url}/api/embed',
        headers=headers,
        json=json_data,
    )
    if r.status_code != 200:
        error_detail = r.json().get('error', r.text)
        raise Exception(f'Ollama embed error ({r.status_code}): {error_detail}')
    data = r.json()

    if 'embeddings' in data:
        return data['embeddings']
    else:
        raise ValueError("Unexpected Ollama embeddings response: missing 'embeddings' key")


async def agenerate_ollama_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = '',
    prefix: str = None,
    user: UserModel = None,
) -> list[list[float]]:
    log.debug(f'agenerate_ollama_batch_embeddings:model {model} batch size: {len(texts)}')
    form_data = {'input': texts, 'model': model, 'truncate': True}
    if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
        form_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    }
    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)

    async with aiohttp.ClientSession(
        trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
    ) as session:
        async with session.post(
            f'{url}/api/embed',
            headers=headers,
            json=form_data,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as r:
            if r.status != 200:
                error_data = await r.json()
                error_detail = error_data.get('error', str(error_data))
                raise Exception(f'Ollama embed error ({r.status}): {error_detail}')
            data = await r.json()
            if 'embeddings' in data:
                return data['embeddings']
            else:
                raise ValueError("Unexpected Ollama embeddings response: missing 'embeddings' key")


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
    if embedding_engine == '':
        # Sentence transformers: CPU-bound sync operation
        async def async_embedding_function(query, prefix=None, user=None):
            # Deferred so a missing local model degrades RAG instead of crashing boot.
            if embedding_function is None:
                raise ValueError(
                    'No embedding model is loaded. Set RAG_EMBEDDING_MODEL to a valid '
                    'SentenceTransformer model name, or configure an external '
                    'RAG_EMBEDDING_ENGINE (ollama, openai, azure_openai).'
                )
            return await asyncio.to_thread(
                (
                    lambda query, prefix=None: embedding_function.encode(
                        query,
                        batch_size=int(embedding_batch_size),
                        **({'prompt': prefix} if prefix else {}),
                    ).tolist()
                ),
                query,
                prefix,
            )

        return async_embedding_function
    elif embedding_engine in ['ollama', 'openai', 'azure_openai']:
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

        async def async_embedding_function(query, prefix=None, user=None, tracker=None):
            if isinstance(query, list):
                # Create batches
                batches = [query[i : i + embedding_batch_size] for i in range(0, len(query), embedding_batch_size)]

                if enable_async:
                    log.debug(f'generate_multiple_async: Processing {len(batches)} batches in parallel')
                    # Use semaphore to limit concurrent embedding API requests
                    # 0 = unlimited (no semaphore)
                    if concurrent_requests:
                        semaphore = asyncio.Semaphore(concurrent_requests)

                        async def generate_batch_with_semaphore(batch):
                            async with semaphore:
                                return await embedding_function(batch, prefix=prefix, user=user, tracker=tracker)

                        tasks = [generate_batch_with_semaphore(batch) for batch in batches]
                    else:
                        tasks = [
                            embedding_function(batch, prefix=prefix, user=user, tracker=tracker) for batch in batches
                        ]
                    batch_results = await asyncio.gather(*tasks)
                else:
                    log.debug(f'generate_multiple_async: Processing {len(batches)} batches sequentially')
                    batch_results = []
                    for batch in batches:
                        batch_results.append(await embedding_function(batch, prefix=prefix, user=user, tracker=tracker))

                # Flatten results — raise if any batch failed
                embeddings = []
                for i, batch_embeddings in enumerate(batch_results):
                    if batch_embeddings is None:
                        raise EmbeddingError(f'Embedding generation failed for batch {i + 1}/{len(batches)}')
                    embeddings.extend(batch_embeddings)

                log.debug(
                    f'generate_multiple_async: Generated {len(embeddings)} embeddings from {len(batches)} parallel batches'
                )
                return embeddings
            else:
                return await embedding_function(query, prefix, user, tracker)

        return async_embedding_function
    else:
        raise ValueError(f'Unknown embedding engine: {embedding_engine}')


async def generate_embeddings(
    engine: str,
    model: str,
    text: Union[str, list[str]],
    prefix: Union[str, None] = None,
    tracker=None,
    **kwargs,
):
    """
    Generate embeddings, retrying transient errors (connection issues, timeouts,
    partial API results) via embedding_with_retry.

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
    """
    url = kwargs.get('url', '')
    key = kwargs.get('key', '')
    user = kwargs.get('user')

    if prefix is not None and RAG_EMBEDDING_PREFIX_FIELD_NAME is None:
        if isinstance(text, list):
            text = [f'{prefix}{text_element}' for text_element in text]
        else:
            text = f'{prefix}{text}'

    texts_list = text if isinstance(text, list) else [text]
    is_single = isinstance(text, str)

    # Filter out empty/whitespace-only strings to prevent API errors, and
    # reconstruct the full (zero-padded) list afterwards so callers still get
    # one embedding per input text.
    non_empty_indices = [i for i, t in enumerate(texts_list) if t and t.strip()]
    non_empty_texts = [texts_list[i] for i in non_empty_indices]

    if not non_empty_texts:
        log.debug(f'[Embedding] All {len(texts_list)} texts empty, returning zero-vectors')
        zero_embedding = [0.0] * 1536
        return zero_embedding if is_single else [zero_embedding] * len(texts_list)

    if engine == 'ollama':
        non_empty_embeddings = await embedding_with_retry(
            embedding_func=agenerate_ollama_batch_embeddings,
            texts=non_empty_texts,
            tracker=tracker,
            model=model,
            url=url,
            key=key,
            prefix=prefix,
            user=user,
        )
    elif engine == 'openai':
        non_empty_embeddings = await embedding_with_retry(
            embedding_func=agenerate_openai_batch_embeddings,
            texts=non_empty_texts,
            tracker=tracker,
            model=model,
            url=url,
            key=key,
            prefix=prefix,
            user=user,
        )
    elif engine == 'azure_openai':
        azure_api_version = kwargs.get('azure_api_version', '')
        non_empty_embeddings = await embedding_with_retry(
            embedding_func=agenerate_azure_openai_batch_embeddings,
            texts=non_empty_texts,
            tracker=tracker,
            model=model,
            url=url,
            key=key,
            version=azure_api_version,
            prefix=prefix,
            user=user,
        )
    else:
        raise ValueError(f'Unknown embedding engine: {engine}')

    if len(non_empty_texts) == len(texts_list):
        embeddings = non_empty_embeddings
    else:
        # Reconstruct the full list, filling empty-text slots with zero-vectors.
        embedding_dim = len(non_empty_embeddings[0]) if non_empty_embeddings else 1536
        zero_embedding = [0.0] * embedding_dim
        non_empty_set = set(non_empty_indices)
        embeddings = []
        non_empty_idx = 0
        for i in range(len(texts_list)):
            if i in non_empty_set:
                embeddings.append(non_empty_embeddings[non_empty_idx])
                non_empty_idx += 1
            else:
                embeddings.append(zero_embedding)

    return embeddings[0] if is_single else embeddings


def get_reranking_function(reranking_engine, reranking_model, reranking_function, reranking_batch_size=32):
    if reranking_function is None:
        return None
    if reranking_engine == 'external':
        return lambda query, documents, user=None: reranking_function.predict(
            [(query, doc.page_content) for doc in documents], user=user
        )
    else:
        return lambda query, documents, user=None: reranking_function.predict(
            [(query, doc.page_content) for doc in documents], batch_size=int(reranking_batch_size)
        )


# UUIDs, SHA-256 digests, and prefixed variants thereof all fit [A-Za-z0-9_-].
# Anything else cannot be a real Open WebUI collection and could break out of
# a Milvus expression literal.
_SAFE_COLLECTION_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,255}$')


def _is_safe_collection_name(name: str) -> bool:
    return isinstance(name, str) and bool(_SAFE_COLLECTION_NAME_RE.match(name))


async def filter_accessible_collections(
    collection_names: set[str],
    user: UserModel,
    access_type: str = 'read',
) -> set[str]:
    """
    Return only the collection names the user is allowed to access.
    Admins bypass all checks.  For non-admins the policy is:

      - any name with characters outside [A-Za-z0-9_-] → rejected
      - file-*          → validated via has_access_to_file
      - user-memory-*   → must match user's own memory collection
      - web-search-*    → ephemeral per-query collections, owner-bound to web-search-{user.id}-*
      - knowledge-bases → always denied (system meta-collection)
      - everything else → if the name matches a knowledge base, validated
                          via Knowledges.check_access_by_user_id; if no
                          such KB exists, denied by default.  When
                          ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS is True,
                          the name is treated as a legacy/ephemeral
                          collection and allowed.
    """
    # Applied before the admin bypass — malformed names should never reach the vector store.
    safe_names = {n for n in collection_names if _is_safe_collection_name(n)}
    rejected = collection_names - safe_names
    if rejected:
        log.warning(
            'filter_accessible_collections: rejected %d collection name(s) with unsafe characters (user_id=%s)',
            len(rejected),
            getattr(user, 'id', '<unknown>'),
        )

    if user.role == 'admin':
        return safe_names

    validated = set()
    for name in safe_names:
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
            # Ephemeral per-query collections, owner-bound: process_web_search mints
            # them as web-search-{user.id}-<hash>, so only the creator may read/write.
            if name.startswith(f'web-search-{user.id}-'):
                validated.add(name)
        else:
            # May be a knowledge-base ID or a legacy/ephemeral collection.
            # If it IS a KB, enforce access control.  If no such KB
            # exists, the behaviour depends on
            # ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS:
            #   False (default) — deny (closes the unscoped namespace)
            #   True  — allow (preserves legacy behaviour)
            if await Knowledges.check_access_by_user_id(name, user.id, permission=access_type):
                validated.add(name)
            elif ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS and not await Knowledges.get_knowledge_by_id(name):
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
    # FORK: per-KB / per-query RAG settings overlay (all defaulted so the
    # base call signature stays backward-compatible).
    enable_reranking=True,
    user: UserModel | None = None,
    per_knowledge_settings: Optional[dict] = None,
    base_settings: Optional[dict] = None,
):
    log.debug('items: %s %s %s %s %s', items, queries, embedding_function, reranking_function, full_context)

    bypass_embedding_and_retrieval = await Config.get('rag.bypass_embedding_and_retrieval')
    extracted_collections = []
    query_results = []
    folder_items = set()
    expanded_folders = set()

    items = list(items)
    for item in items:
        if item.get('type') != 'folder' or not user:
            continue
        folder_id = item.get('id')
        if not folder_id or folder_id in expanded_folders:
            continue
        expanded_folders.add(folder_id)

        folder = await Folders.get_folder_by_id(folder_id)
        if folder and (user.role == 'admin' or await has_folder_access(user.id, folder, 'read', db=None)):
            files = await get_owner_accessible_folder_files(folder)
            folder_items.update((entry.get('type'), entry.get('id')) for entry in files if isinstance(entry, dict))
            items.extend(files)

    for item in items:
        query_result = None
        collection_names = []

        if item.get('type') == 'text':
            # Raw Text
            # Used during temporary chat file uploads or web page & youtube attachements

            if item.get('context') == 'full':
                if item.get('file'):
                    # if item has file data, use it
                    query_result = {
                        'documents': [[item.get('file', {}).get('data', {}).get('content')]],
                        'metadatas': [[item.get('file', {}).get('meta', {})]],
                    }

            if query_result is None:
                # Fallback
                if item.get('collection_name'):
                    # If item has a collection name, use it
                    collection_names.append(item.get('collection_name'))
                elif item.get('file'):
                    # If item has file data, use it
                    query_result = {
                        'documents': [[item.get('file', {}).get('data', {}).get('content')]],
                        'metadatas': [[item.get('file', {}).get('meta', {})]],
                    }
                else:
                    # Fallback to item content
                    query_result = {
                        'documents': [[item.get('content')]],
                        'metadatas': [[{'file_id': item.get('id'), 'name': item.get('name')}]],
                    }

        elif item.get('type') == 'note':
            # Note Attached
            note = await Notes.get_note_by_id(item.get('id'))

            if note and (
                user.role == 'admin'
                or note.user_id == user.id
                or await AccessGrants.has_access(
                    user_id=user.id,
                    resource_type='note',
                    resource_id=note.id,
                    permission='read',
                )
            ):
                # User has access to the note
                query_result = {
                    'documents': [[note.data.get('content', {}).get('md', '')]],
                    'metadatas': [[{'file_id': note.id, 'name': note.title}]],
                }

        elif item.get('type') == 'chat':
            # Chat Attached
            chat = await Chats.get_chat_by_id(item.get('id'))

            if chat and (user.role == 'admin' or chat.user_id == user.id):
                messages_map = chat.chat.get('history', {}).get('messages', {})
                message_id = chat.chat.get('history', {}).get('currentId')

                if messages_map and message_id:
                    # Reconstruct the message list in order
                    message_list = get_message_list(messages_map, message_id)
                    message_history = '\n'.join(
                        [
                            f'#### {m.get("role", "user").capitalize()}\n{get_content_from_message(m) or ""}\n'
                            for m in message_list
                        ]
                    )

                    # User has access to the chat
                    query_result = {
                        'documents': [[message_history]],
                        'metadatas': [[{'file_id': chat.id, 'name': chat.title}]],
                    }

        elif item.get('type') == 'url':
            content, docs = await get_content_from_url(request, item.get('url'))
            if docs:
                query_result = {
                    'documents': [[content]],
                    'metadatas': [[{'url': item.get('url'), 'name': item.get('url')}]],
                }
        elif item.get('type') == 'file':
            if item.get('context') == 'full' or bypass_embedding_and_retrieval:
                if item.get('file', {}).get('data', {}).get('content', ''):
                    # Manual Full Mode Toggle
                    # Used from chat file modal, we can assume that the file content will be available from item.get("file").get("data", {}).get("content")
                    query_result = {
                        'documents': [[item.get('file', {}).get('data', {}).get('content', '')]],
                        'metadatas': [
                            [
                                {
                                    'file_id': item.get('id'),
                                    'name': item.get('name'),
                                    **item.get('file').get('data', {}).get('metadata', {}),
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
                        or ('file', item.get('id')) in folder_items
                    ):
                        query_result = {
                            'documents': [[file_object.data.get('content', '')]],
                            'metadatas': [
                                [
                                    {
                                        'file_id': item.get('id'),
                                        'name': file_object.filename,
                                        'source': file_object.filename,
                                    }
                                ]
                            ],
                        }
            else:
                # Chunked-retrieval fallback — verify read access before
                # exposing the file's vector collection (same posture as the
                # full-context branch above).
                file_id = item.get('id')
                if file_id:
                    if BYPASS_RETRIEVAL_ACCESS_CONTROL:
                        if item.get('legacy'):
                            collection_names.append(f'{file_id}')
                        else:
                            collection_names.append(f'file-{file_id}')
                    else:
                        file_object = await Files.get_file_by_id(file_id)
                        if file_object and (
                            user.role == 'admin'
                            or file_object.user_id == user.id
                            or await has_access_to_file(file_id, 'read', user)
                            or ('file', file_id) in folder_items
                        ):
                            if item.get('legacy'):
                                collection_names.append(f'{file_id}')
                            else:
                                collection_names.append(f'file-{file_id}')

        elif item.get('type') == 'collection':
            # Knowledge Base Collection
            knowledge_id = item.get('id')
            knowledge_base = await Knowledges.get_knowledge_by_id(knowledge_id)

            if knowledge_base and (
                user.role == 'admin'
                or knowledge_base.user_id == user.id
                or await AccessGrants.has_access(
                    user_id=user.id,
                    resource_type='knowledge',
                    resource_id=knowledge_base.id,
                    permission='read',
                )
                or ('collection', item.get('id')) in folder_items
            ):
                if (knowledge_base.meta or {}).get('source') == 'external':
                    query_result = await retrieve_external_knowledge(
                        request,
                        knowledge_base,
                        queries=queries,
                        count=k,
                        user=user,
                    )
                    extracted_collections.append(knowledge_base.id)

                else:
                    # FORK: per-KB RAG settings overlay. Resolve this KB's effective
                    # settings BEFORE deciding full-context vs. vector-search, so each
                    # KB's full_context/threshold/top_k/... overrides are respected
                    # independently of other KBs in the same request.
                    kb_settings = (per_knowledge_settings or {}).get(knowledge_id, {})

                    ui_full_context = item.get('context') == 'full'
                    kb_full_context = kb_settings.get('full_context')  # None if not overridden
                    if ui_full_context:
                        effective_full_context = True
                    elif kb_full_context is not None:
                        effective_full_context = kb_full_context
                    else:
                        effective_full_context = full_context

                    effective_r = kb_settings.get('relevance_threshold', r)
                    effective_k = kb_settings.get('top_k', k)
                    effective_k_reranker = kb_settings.get('top_k_reranker', k_reranker)
                    effective_hybrid_search = kb_settings.get('enable_hybrid_search', hybrid_search)
                    effective_hybrid_bm25_weight = kb_settings.get('hybrid_bm25_weight', hybrid_bm25_weight)
                    effective_enable_reranking = kb_settings.get('enable_reranking', enable_reranking)

                    if effective_full_context or bypass_embedding_and_retrieval:
                        if knowledge_base and (
                            user.role == 'admin'
                            or knowledge_base.user_id == user.id
                            or await AccessGrants.has_access(
                                user_id=user.id,
                                resource_type='knowledge',
                                resource_id=knowledge_base.id,
                                permission='read',
                            )
                            or ('collection', item.get('id')) in folder_items
                        ):
                            files = await Knowledges.get_files_by_id(knowledge_base.id)

                            documents = []
                            metadatas = []
                            for file in files:
                                documents.append(file.data.get('content', ''))
                                metadatas.append(
                                    {
                                        'file_id': file.id,
                                        'name': file.filename,
                                        'source': file.filename,
                                    }
                                )

                            query_result = {
                                'documents': [documents],
                                'metadatas': [metadatas],
                            }
                    else:
                        # Cross-tenant legacy collection-name validation guard is
                        # preserved as-is (must not regress to an unguarded body).
                        if item.get('legacy'):
                            if BYPASS_RETRIEVAL_ACCESS_CONTROL:
                                kb_collection_names = item.get('collection_names', [])
                            else:
                                # Legacy KB: item.collection_names is client-supplied.
                                # Validate against the KB's actual files to prevent
                                # cross-tenant collection name substitution.
                                files = await Knowledges.get_files_by_id(knowledge_base.id)
                                owned_names = {f'file-{f.id}' for f in files}
                                owned_names.add(knowledge_base.id)
                                valid_names = [n for n in (item.get('collection_names') or []) if n in owned_names]
                                kb_collection_names = valid_names if valid_names else [knowledge_base.id]
                        else:
                            kb_collection_names = [knowledge_id]

                        # Query this KB's collections independently, with its own
                        # effective settings.
                        kb_collection_names_set = set(kb_collection_names).difference(extracted_collections)
                        if kb_collection_names_set:
                            try:
                                if effective_hybrid_search:
                                    enriched_texts_cfg = await Config.get(
                                        'rag.enable_hybrid_search_enriched_texts'
                                    )
                                    query_result = await query_collection_with_hybrid_search(
                                        collection_names=list(kb_collection_names_set),
                                        queries=queries,
                                        embedding_function=embedding_function,
                                        k=effective_k,
                                        reranking_function=reranking_function,
                                        k_reranker=effective_k_reranker,
                                        r=effective_r,
                                        hybrid_bm25_weight=effective_hybrid_bm25_weight,
                                        enable_enriched_texts=enriched_texts_cfg,
                                        enable_reranking=effective_enable_reranking,
                                    )
                                else:
                                    # request=None: this KB's effective_hybrid_search is
                                    # False, so skip query_collection's own (global-config
                                    # driven) hybrid-search branch — otherwise a global
                                    # ENABLE_RAG_HYBRID_SEARCH=True would silently override
                                    # this KB's explicit opt-out.
                                    query_result = await query_collection(
                                        request=None,
                                        collection_names=list(kb_collection_names_set),
                                        queries=queries,
                                        embedding_function=embedding_function,
                                        k=effective_k,
                                    )
                                    if query_result and effective_r and effective_r > 0:
                                        query_result = filter_results_by_relevance(query_result, effective_r)

                                extracted_collections.extend(kb_collection_names_set)
                            except Exception as e:
                                log.exception(f'Error querying KB {knowledge_id}: {e}')

                        # This KB has already been queried above; skip the generic
                        # collection_names handling below for this item.
                        if query_result:
                            if 'data' in item:
                                del item['data']
                            query_results.append({**query_result, 'file': item})
                        continue

        elif item.get('docs'):
            # BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
            query_result = {
                'documents': [[doc.get('content') for doc in item.get('docs')]],
                'metadatas': [[doc.get('metadata') for doc in item.get('docs')]],
            }
        elif item.get('type') == 'web_search' and item.get('collection_name'):
            # Trusted server-generated collection; authorized by
            # filter_accessible_collections below (allowlists web-search-*).
            collection_names.append(item['collection_name'])
        elif item.get('collection_name'):
            if BYPASS_RETRIEVAL_ACCESS_CONTROL:
                collection_names.append(item['collection_name'])
            else:
                log.debug(
                    "get_sources_from_items: ignoring untrusted direct collection_name '%s' on item without type",
                    item.get('collection_name'),
                )
        elif item.get('collection_names'):
            if BYPASS_RETRIEVAL_ACCESS_CONTROL:
                collection_names.extend(item['collection_names'])
            else:
                log.debug(
                    'get_sources_from_items: ignoring untrusted direct collection_names on item without type',
                )

        # If query_result is None
        # Fallback to collection names and vector search the collections
        if query_result is None and collection_names:
            collection_names = set(collection_names).difference(extracted_collections)
            if not collection_names:
                log.debug(f'skipping {item} as it has already been extracted')
                continue

            # Filter out collections the user cannot read
            if user and (item.get('type'), item.get('id')) not in folder_items:
                collection_names = await filter_accessible_collections(collection_names, user)
                if not collection_names:
                    log.debug(f'access denied for all collections in item {item}')
                    continue

            try:
                if full_context:
                    # Sync helper makes blocking VECTOR_DB_CLIENT calls;
                    # offload so the async caller's event loop stays free.
                    query_result = await asyncio.to_thread(get_all_items_from_collections, collection_names)
                elif hybrid_search:
                    enriched_texts_cfg = await Config.get('rag.enable_hybrid_search_enriched_texts')
                    query_result = await query_collection_with_hybrid_search(
                        collection_names=collection_names,
                        queries=queries,
                        embedding_function=embedding_function,
                        k=k,
                        reranking_function=reranking_function,
                        k_reranker=k_reranker,
                        r=r,
                        hybrid_bm25_weight=hybrid_bm25_weight,
                        enable_enriched_texts=enriched_texts_cfg,
                        enable_reranking=enable_reranking,
                    )
                else:
                    query_result = await query_collection(
                        request=None,
                        collection_names=collection_names,
                        queries=queries,
                        embedding_function=embedding_function,
                        k=k,
                    )
                    if query_result and r and r > 0:
                        query_result = filter_results_by_relevance(query_result, r)
            except Exception as e:
                log.exception(e)

            extracted_collections.extend(collection_names)

        if query_result:
            if 'data' in item:
                del item['data']
            query_results.append({**query_result, 'file': item})

    sources = []
    for query_result in query_results:
        try:
            if 'documents' in query_result:
                if 'metadatas' in query_result:
                    source = {
                        'source': query_result['file'],
                        'document': query_result['documents'][0],
                        'metadata': query_result['metadatas'][0],
                    }
                    if 'distances' in query_result and query_result['distances']:
                        source['distances'] = query_result['distances'][0]

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

    This is the settings-object interface; it delegates to get_sources_from_items.

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
    per_kb_dict = None
    if per_knowledge_settings:
        per_kb_dict = {
            kb_id: (kb_settings.model_dump() if isinstance(kb_settings, RAGQuerySettings) else kb_settings)
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
    cache_dir = os.getenv('SENTENCE_TRANSFORMERS_HOME')

    local_files_only = not update_model

    if OFFLINE_MODE:
        local_files_only = True

    snapshot_kwargs = {
        'cache_dir': cache_dir,
        'local_files_only': local_files_only,
    }

    log.debug(f'model: {model}')
    log.debug(f'snapshot_kwargs: {snapshot_kwargs}')

    # Inspiration from upstream sentence_transformers
    if os.path.exists(model) or ('\\' in model or model.count('/') > 1) and local_files_only:
        # If fully qualified path exists, return input, else set repo_id
        return model
    elif '/' not in model:
        # Set valid repo_id for model short-name
        model = 'sentence-transformers' + '/' + model

    snapshot_kwargs['repo_id'] = model

    # Attempt to query the huggingface_hub library to determine the local path and/or to update
    try:
        model_repo_path = snapshot_download(**snapshot_kwargs)
        log.debug(f'model_repo_path: {model_repo_path}')
        return model_repo_path
    except Exception as e:
        log.exception(f'Cannot determine model snapshot path: {e}')
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
        extra = 'forbid'
        arbitrary_types_allowed = True

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
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
        callbacks: Callbacks | None = None,
    ) -> Sequence[Document]:
        if not self.enable_reranking:
            # Pass through documents unranked, preserving any existing vector/BM25
            # score in metadata, or assigning a rank-based score (RRF-style) for
            # results that don't carry one (e.g. BM25-only matches).
            result_docs = []
            for idx, doc in enumerate(list(documents[: self.top_n])):
                metadata = doc.metadata.copy()
                if metadata.get('score') is None:
                    metadata['score'] = 1.0 / (idx + 1)
                result_docs.append(Document(page_content=doc.page_content, metadata=metadata))
            return result_docs

        reranking = self.reranking_function is not None

        scores = None
        if reranking:
            scores = await asyncio.to_thread(self.reranking_function, query, documents)
        else:
            from sentence_transformers import util as st_util

            query_embedding = await self.embedding_function(query, RAG_EMBEDDING_QUERY_PREFIX)
            doc_texts = [doc.page_content for doc in documents]
            document_embedding = await self.embedding_function(doc_texts, RAG_EMBEDDING_CONTENT_PREFIX)
            scores = st_util.cos_sim(query_embedding, document_embedding)[0]

        if scores is not None:
            docs_with_scores = list(
                zip(
                    documents,
                    scores.tolist() if not isinstance(scores, list) else scores,
                )
            )
            if self.r_score:
                docs_with_scores = [(d, s) for d, s in docs_with_scores if s >= self.r_score]

            result = sorted(docs_with_scores, key=operator.itemgetter(1), reverse=True)
            final_results = []
            for doc, doc_score in result[: self.top_n]:
                metadata = doc.metadata
                metadata['score'] = doc_score
                doc = Document(
                    page_content=doc.page_content,
                    metadata=metadata,
                )
                final_results.append(doc)
            return final_results
        else:
            log.warning('No valid scores found, check your reranking function. Returning original documents.')
            return documents
