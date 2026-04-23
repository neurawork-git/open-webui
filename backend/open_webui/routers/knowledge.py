from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, UploadFile
from fastapi.responses import StreamingResponse

import logging
import io
import time
import uuid
import zipfile
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from open_webui.internal.db import get_async_session
from open_webui.models.groups import Groups
from open_webui.models.knowledge import (
    KnowledgeFileListResponse,
    Knowledges,
    KnowledgeForm,
    KnowledgeResponse,
    KnowledgeUserResponse,
)
from open_webui.models.files import Files, FileModel, FileMetadataResponse
from open_webui.models.oauth_sessions import OAuthSessions
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.routers.retrieval import (
    process_file,
    ProcessFileForm,
    process_files_batch,
    BatchProcessFilesForm,
)
from open_webui.routers.files import upload_file_handler
from open_webui.storage.provider import Storage
from open_webui.utils.graph_client import (
    GraphChildItem,
    GraphChildrenListing,
    GraphClient,
    GraphFileItem,
    GraphFolderListing,
    GraphSiteListing,
)

from open_webui.constants import ERROR_MESSAGES
from open_webui.utils.auth import get_verified_user, get_admin_user
from open_webui.utils.access_control import has_permission, filter_allowed_access_grants
from open_webui.models.access_grants import AccessGrants


from open_webui.config import BYPASS_ADMIN_ACCESS_CONTROL
from open_webui.models.models import Models, ModelForm

log = logging.getLogger(__name__)

router = APIRouter()

############################
# getKnowledgeBases
############################

PAGE_ITEM_COUNT = 30

############################
# Knowledge Base Embedding
############################

# Knowledge that sits unread serves no one. Let what is
# stored here find the ones who need it.
KNOWLEDGE_BASES_COLLECTION = 'knowledge-bases'


async def embed_knowledge_base_metadata(
    request: Request,
    knowledge_base_id: str,
    name: str,
    description: str,
) -> bool:
    """Generate and store embedding for knowledge base."""
    try:
        content = f'{name}\n\n{description}' if description else name
        embedding = await request.app.state.EMBEDDING_FUNCTION(content)
        await ASYNC_VECTOR_DB_CLIENT.upsert(
            collection_name=KNOWLEDGE_BASES_COLLECTION,
            items=[
                {
                    'id': knowledge_base_id,
                    'text': content,
                    'vector': embedding,
                    'metadata': {
                        'knowledge_base_id': knowledge_base_id,
                    },
                }
            ],
        )
        return True
    except Exception as e:
        log.error(f'Failed to embed knowledge base {knowledge_base_id}: {e}')
        return False


async def remove_knowledge_base_metadata_embedding(knowledge_base_id: str) -> bool:
    """Remove knowledge base embedding."""
    try:
        await ASYNC_VECTOR_DB_CLIENT.delete(
            collection_name=KNOWLEDGE_BASES_COLLECTION,
            ids=[knowledge_base_id],
        )
        return True
    except Exception as e:
        log.debug(f'Failed to remove embedding for {knowledge_base_id}: {e}')
        return False


class KnowledgeAccessResponse(KnowledgeUserResponse):
    write_access: Optional[bool] = False


class KnowledgeAccessListResponse(BaseModel):
    items: list[KnowledgeAccessResponse]
    total: int


@router.get('/', response_model=KnowledgeAccessListResponse)
async def get_knowledge_bases(
    page: Optional[int] = 1,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    page = max(page, 1)
    limit = PAGE_ITEM_COUNT
    skip = (page - 1) * limit

    filter = {}
    groups = await Groups.get_groups_by_member_id(user.id, db=db)
    user_group_ids = {group.id for group in groups}

    if not user.role == 'admin' or not BYPASS_ADMIN_ACCESS_CONTROL:
        if groups:
            filter['group_ids'] = [group.id for group in groups]

        filter['user_id'] = user.id

    result = await Knowledges.search_knowledge_bases(user.id, filter=filter, skip=skip, limit=limit, db=db)

    # Batch-fetch writable knowledge IDs in a single query instead of N has_access calls
    knowledge_base_ids = [knowledge_base.id for knowledge_base in result.items]
    writable_knowledge_base_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user.id,
        resource_type='knowledge',
        resource_ids=knowledge_base_ids,
        permission='write',
        user_group_ids=user_group_ids,
        db=db,
    )

    return KnowledgeAccessListResponse(
        items=[
            KnowledgeAccessResponse(
                **knowledge_base.model_dump(),
                write_access=(
                    user.id == knowledge_base.user_id
                    or (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
                    or knowledge_base.id in writable_knowledge_base_ids
                ),
            )
            for knowledge_base in result.items
        ],
        total=result.total,
    )


@router.get('/search', response_model=KnowledgeAccessListResponse)
async def search_knowledge_bases(
    query: Optional[str] = None,
    view_option: Optional[str] = None,
    page: Optional[int] = 1,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    page = max(page, 1)
    limit = PAGE_ITEM_COUNT
    skip = (page - 1) * limit

    filter = {}
    if query:
        filter['query'] = query
    if view_option:
        filter['view_option'] = view_option

    groups = await Groups.get_groups_by_member_id(user.id, db=db)
    user_group_ids = {group.id for group in groups}

    if not user.role == 'admin' or not BYPASS_ADMIN_ACCESS_CONTROL:
        if groups:
            filter['group_ids'] = [group.id for group in groups]

        filter['user_id'] = user.id

    result = await Knowledges.search_knowledge_bases(user.id, filter=filter, skip=skip, limit=limit, db=db)

    # Batch-fetch writable knowledge IDs in a single query instead of N has_access calls
    knowledge_base_ids = [knowledge_base.id for knowledge_base in result.items]
    writable_knowledge_base_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user.id,
        resource_type='knowledge',
        resource_ids=knowledge_base_ids,
        permission='write',
        user_group_ids=user_group_ids,
        db=db,
    )

    return KnowledgeAccessListResponse(
        items=[
            KnowledgeAccessResponse(
                **knowledge_base.model_dump(),
                write_access=(
                    user.id == knowledge_base.user_id
                    or (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
                    or knowledge_base.id in writable_knowledge_base_ids
                ),
            )
            for knowledge_base in result.items
        ],
        total=result.total,
    )


@router.get('/search/files', response_model=KnowledgeFileListResponse)
async def search_knowledge_files(
    query: Optional[str] = None,
    page: Optional[int] = 1,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    page = max(page, 1)
    limit = PAGE_ITEM_COUNT
    skip = (page - 1) * limit

    filter = {}
    if query:
        filter['query'] = query

    groups = await Groups.get_groups_by_member_id(user.id, db=db)
    if groups:
        filter['group_ids'] = [group.id for group in groups]

    filter['user_id'] = user.id

    return await Knowledges.search_knowledge_files(filter=filter, skip=skip, limit=limit, db=db)


############################
# CreateNewKnowledge
############################


@router.post('/create', response_model=Optional[KnowledgeResponse])
async def create_new_knowledge(
    request: Request,
    form_data: KnowledgeForm,
    user=Depends(get_verified_user),
):
    # NOTE: We intentionally do NOT use Depends(get_async_session) here.
    # Database operations (has_permission, filter_allowed_access_grants, insert_new_knowledge) manage their own sessions.
    # This prevents holding a connection during embed_knowledge_base_metadata()
    # which makes external embedding API calls (1-5+ seconds).
    if user.role != 'admin' and not await has_permission(
        user.id, 'workspace.knowledge', request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    form_data.access_grants = await filter_allowed_access_grants(
        request.app.state.config.USER_PERMISSIONS,
        user.id,
        user.role,
        form_data.access_grants,
        'sharing.public_knowledge',
    )

    knowledge = await Knowledges.insert_new_knowledge(user.id, form_data)

    if knowledge:
        # Embed knowledge base for semantic search
        await embed_knowledge_base_metadata(
            request,
            knowledge.id,
            knowledge.name,
            knowledge.description,
        )
        return knowledge
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FILE_EXISTS,
        )


############################
# ReindexKnowledgeFiles
############################


@router.post('/reindex', response_model=bool)
async def reindex_knowledge_files(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if user.role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    knowledge_bases = await Knowledges.get_knowledge_bases(db=db)

    log.info(f'Starting reindexing for {len(knowledge_bases)} knowledge bases')

    for knowledge_base in knowledge_bases:
        try:
            files = await Knowledges.get_files_by_id(knowledge_base.id, db=db)
            try:
                if await ASYNC_VECTOR_DB_CLIENT.has_collection(collection_name=knowledge_base.id):
                    await ASYNC_VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_base.id)
            except Exception as e:
                log.error(f'Error deleting collection {knowledge_base.id}: {str(e)}')
                continue  # Skip, don't raise

            failed_files = []
            for file in files:
                try:
                    await process_file(
                        request,
                        ProcessFileForm(file_id=file.id, collection_name=knowledge_base.id),
                        user=user,
                        db=db,
                    )
                except Exception as e:
                    log.error(f'Error processing file {file.filename} (ID: {file.id}): {str(e)}')
                    failed_files.append({'file_id': file.id, 'error': str(e)})
                    continue

        except Exception as e:
            log.error(f'Error processing knowledge base {knowledge_base.id}: {str(e)}')
            # Don't raise, just continue
            continue

        if failed_files:
            log.warning(f'Failed to process {len(failed_files)} files in knowledge base {knowledge_base.id}')
            for failed in failed_files:
                log.warning(f'File ID: {failed["file_id"]}, Error: {failed["error"]}')

    log.info(f'Reindexing completed.')
    return True


############################
# ReindexKnowledgeBases
############################


@router.post('/metadata/reindex', response_model=dict)
async def reindex_knowledge_base_metadata_embeddings(
    request: Request,
    user=Depends(get_admin_user),
):
    """Batch embed all existing knowledge bases. Admin only.

    NOTE: We intentionally do NOT use Depends(get_async_session) here.
    This endpoint loops through ALL knowledge bases and calls embed_knowledge_base_metadata()
    for each one, making N external embedding API calls. Holding a session during
    this entire operation would exhaust the connection pool.
    """
    knowledge_bases = await Knowledges.get_knowledge_bases()
    log.info(f'Reindexing embeddings for {len(knowledge_bases)} knowledge bases')

    success_count = 0
    for kb in knowledge_bases:
        if await embed_knowledge_base_metadata(request, kb.id, kb.name, kb.description):
            success_count += 1

    log.info(f'Embedding reindex complete: {success_count}/{len(knowledge_bases)}')
    return {'total': len(knowledge_bases), 'success': success_count}


############################
# GetKnowledgeById
############################


class KnowledgeFilesResponse(KnowledgeResponse):
    files: Optional[list[FileMetadataResponse]] = None
    write_access: Optional[bool] = False


@router.get('/{id}', response_model=Optional[KnowledgeFilesResponse])
async def get_knowledge_by_id(id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)

    if knowledge:
        if (
            user.role == 'admin'
            or knowledge.user_id == user.id
            or await AccessGrants.has_access(
                user_id=user.id,
                resource_type='knowledge',
                resource_id=knowledge.id,
                permission='read',
                db=db,
            )
        ):
            return KnowledgeFilesResponse(
                **knowledge.model_dump(),
                write_access=(
                    user.id == knowledge.user_id
                    or (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
                    or await AccessGrants.has_access(
                        user_id=user.id,
                        resource_type='knowledge',
                        resource_id=knowledge.id,
                        permission='write',
                        db=db,
                    )
                ),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateKnowledgeById
############################


@router.post('/{id}/update', response_model=Optional[KnowledgeFilesResponse])
async def update_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeForm,
    user=Depends(get_verified_user),
):
    # NOTE: We intentionally do NOT use Depends(get_async_session) here.
    # Database operations manage their own short-lived sessions internally.
    # This prevents holding a connection during embed_knowledge_base_metadata()
    # which makes external embedding API calls (1-5+ seconds).
    knowledge = await Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    # Is the user the original creator, in a group with write access, or an admin
    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    form_data.access_grants = await filter_allowed_access_grants(
        request.app.state.config.USER_PERMISSIONS,
        user.id,
        user.role,
        form_data.access_grants,
        'sharing.public_knowledge',
    )

    knowledge = await Knowledges.update_knowledge_by_id(id=id, form_data=form_data)
    if knowledge:
        # Re-embed knowledge base for semantic search
        await embed_knowledge_base_metadata(
            request,
            knowledge.id,
            knowledge.name,
            knowledge.description,
        )
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=await Knowledges.get_file_metadatas_by_id(knowledge.id),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ID_TAKEN,
        )


############################
# UpdateKnowledgeAccessById
############################


class KnowledgeAccessGrantsForm(BaseModel):
    access_grants: list[dict]


@router.post('/{id}/access/update', response_model=Optional[KnowledgeFilesResponse])
async def update_knowledge_access_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeAccessGrantsForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    form_data.access_grants = await filter_allowed_access_grants(
        request.app.state.config.USER_PERMISSIONS,
        user.id,
        user.role,
        form_data.access_grants,
        'sharing.public_knowledge',
    )

    knowledge.access_grants = await AccessGrants.set_access_grants('knowledge', id, form_data.access_grants, db=db)

    return KnowledgeFilesResponse(
        **knowledge.model_dump(),
        files=await Knowledges.get_file_metadatas_by_id(id, db=db),
    )


############################
# GetKnowledgeFilesById
############################


@router.get('/{id}/files', response_model=KnowledgeFileListResponse)
async def get_knowledge_files_by_id(
    id: str,
    query: Optional[str] = None,
    view_option: Optional[str] = None,
    order_by: Optional[str] = None,
    direction: Optional[str] = None,
    page: Optional[int] = 1,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if not (
        user.role == 'admin'
        or knowledge.user_id == user.id
        or await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='read',
            db=db,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    page = max(page, 1)

    limit = 30
    skip = (page - 1) * limit

    filter = {}
    if query:
        filter['query'] = query
    if view_option:
        filter['view_option'] = view_option
    if order_by:
        filter['order_by'] = order_by
    if direction:
        filter['direction'] = direction

    return await Knowledges.search_files_by_id(id, user.id, filter=filter, skip=skip, limit=limit, db=db)


############################
# AddFileToKnowledge
############################


class KnowledgeFileIdForm(BaseModel):
    file_id: str


@router.post('/{id}/file/add', response_model=Optional[KnowledgeFilesResponse])
async def add_file_to_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = await Files.get_file_by_id(form_data.file_id, db=db)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not file.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FILE_NOT_PROCESSED,
        )

    # Add content to the vector database
    try:
        await process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
            db=db,
        )

        # Add file to knowledge base
        await Knowledges.add_file_to_knowledge_by_id(knowledge_id=id, file_id=form_data.file_id, user_id=user.id, db=db)
    except Exception as e:
        log.debug(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=await Knowledges.get_file_metadatas_by_id(knowledge.id, db=db),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.post('/{id}/file/update', response_model=Optional[KnowledgeFilesResponse])
async def update_file_from_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = await Files.get_file_by_id(form_data.file_id, db=db)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Validate the file actually belongs to this knowledge base
    if not await Knowledges.has_file(knowledge_id=id, file_id=form_data.file_id, db=db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Remove content from the vector database
    await ASYNC_VECTOR_DB_CLIENT.delete(collection_name=knowledge.id, filter={'file_id': form_data.file_id})

    # Add content to the vector database
    try:
        await process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
            db=db,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=await Knowledges.get_file_metadatas_by_id(knowledge.id, db=db),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# RemoveFileFromKnowledge
############################


@router.post('/{id}/file/remove', response_model=Optional[KnowledgeFilesResponse])
async def remove_file_from_knowledge_by_id(
    id: str,
    form_data: KnowledgeFileIdForm,
    delete_file: bool = Query(True),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = await Files.get_file_by_id(form_data.file_id, db=db)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Validate the file actually belongs to this knowledge base
    if not await Knowledges.has_file(knowledge_id=id, file_id=form_data.file_id, db=db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    await Knowledges.remove_file_from_knowledge_by_id(knowledge_id=id, file_id=form_data.file_id, db=db)

    # Remove content from the vector database
    try:
        await ASYNC_VECTOR_DB_CLIENT.delete(
            collection_name=knowledge.id, filter={'file_id': form_data.file_id}
        )  # Remove by file_id first

        await ASYNC_VECTOR_DB_CLIENT.delete(
            collection_name=knowledge.id, filter={'hash': file.hash}
        )  # Remove by hash as well in case of duplicates
    except Exception as e:
        log.debug('This was most likely caused by bypassing embedding processing')
        log.debug(e)
        pass

    # Only the file owner or an admin may permanently delete the underlying
    # file.  Collaborators with KB write access can unlink a file from the
    # knowledge base but must not be able to destroy files they do not own,
    # as the same file may be referenced by other KBs and chats.
    if delete_file and (file.user_id == user.id or user.role == 'admin'):
        try:
            # Remove the file's collection from vector database
            file_collection = f'file-{form_data.file_id}'
            if await ASYNC_VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                await ASYNC_VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
        except Exception as e:
            log.debug('This was most likely caused by bypassing embedding processing')
            log.debug(e)
            pass

        # Delete file from database
        await Files.delete_file_by_id(form_data.file_id, db=db)

    if knowledge:
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=await Knowledges.get_file_metadatas_by_id(knowledge.id, db=db),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# DeleteKnowledgeById
############################


@router.delete('/{id}/delete', response_model=bool)
async def delete_knowledge_by_id(
    id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f'Deleting knowledge base: {id} (name: {knowledge.name})')

    # Get all models
    models = await Models.get_all_models(db=db)
    log.info(f'Found {len(models)} models to check for knowledge base {id}')

    # Update models that reference this knowledge base
    for model in models:
        if model.meta and hasattr(model.meta, 'knowledge'):
            knowledge_list = model.meta.knowledge or []
            # Filter out the deleted knowledge base
            updated_knowledge = [k for k in knowledge_list if k.get('id') != id]

            # If the knowledge list changed, update the model
            if len(updated_knowledge) != len(knowledge_list):
                log.info(f'Updating model {model.id} to remove knowledge base {id}')
                model.meta.knowledge = updated_knowledge
                model_form = ModelForm(**model.model_dump())
                await Models.update_model_by_id(model.id, model_form, db=db)

    # Clean up vector DB
    try:
        await ASYNC_VECTOR_DB_CLIENT.delete_collection(collection_name=id)
    except Exception as e:
        log.debug(e)
        pass

    # Remove knowledge base embedding
    await remove_knowledge_base_metadata_embedding(id)

    result = await Knowledges.delete_knowledge_by_id(id=id, db=db)
    return result


############################
# ReindexKnowledgeById
############################


class ReindexResponse(BaseModel):
    """Response model for reindex operation."""

    success: bool
    message: str
    total_files: int
    processed_files: int
    failed_files: list[dict]


@router.post("/{id}/reindex", response_model=ReindexResponse)
async def reindex_knowledge_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Reindex a single knowledge base by deleting its vector collection
    and re-processing all files with current embedding settings.

    This is useful when:
    - Embedding model has changed
    - Vector dimension mismatch errors occur
    - Files need to be re-chunked with new settings
    """
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Check access - must be owner, have write access, or be admin
    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"Starting reindex for knowledge base {id} ({knowledge.name})")

    files = await Knowledges.get_files_by_id(id, db=db)
    total_files = len(files)

    if total_files == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge base has no files to reindex",
        )

    # Delete existing vector collection
    try:
        if await ASYNC_VECTOR_DB_CLIENT.has_collection(collection_name=id):
            await ASYNC_VECTOR_DB_CLIENT.delete_collection(collection_name=id)
            log.info(f"Deleted existing vector collection for knowledge base {id}")
    except Exception as e:
        log.error(f"Error deleting collection {id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete existing vector collection: {str(e)}",
        )

    # Re-process all files
    failed_files = []
    processed_count = 0

    for file in files:
        try:
            await process_file(
                request,
                ProcessFileForm(file_id=file.id, collection_name=id),
                user=user,
                db=db,
            )
            processed_count += 1
            log.debug(f"Reindexed file {file.filename} (ID: {file.id})")
        except Exception as e:
            log.error(f"Error processing file {file.filename} (ID: {file.id}): {str(e)}")
            failed_files.append({
                "file_id": file.id,
                "filename": file.filename,
                "error": str(e)
            })

    # Log summary
    if failed_files:
        log.warning(
            f"Reindex completed for knowledge base {id} with {len(failed_files)} failures "
            f"out of {total_files} files"
        )
    else:
        log.info(
            f"Reindex completed successfully for knowledge base {id}: "
            f"{processed_count}/{total_files} files processed"
        )

    return ReindexResponse(
        success=len(failed_files) == 0,
        message=(
            f"Reindexed {processed_count}/{total_files} files successfully"
            if len(failed_files) == 0
            else f"Reindexed {processed_count}/{total_files} files with {len(failed_files)} failures"
        ),
        total_files=total_files,
        processed_files=processed_count,
        failed_files=failed_files,
    )


############################
# ResetKnowledgeById
############################


@router.post('/{id}/reset', response_model=Optional[KnowledgeResponse])
async def reset_knowledge_by_id(
    id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        await ASYNC_VECTOR_DB_CLIENT.delete_collection(collection_name=id)
    except Exception as e:
        log.debug(e)
        pass

    knowledge = await Knowledges.reset_knowledge_by_id(id=id, db=db)
    return knowledge


############################
# AddFilesToKnowledge
############################


@router.post('/{id}/files/batch/add', response_model=Optional[KnowledgeFilesResponse])
async def add_files_to_knowledge_batch(
    request: Request,
    id: str,
    form_data: list[KnowledgeFileIdForm],
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Add multiple files to a knowledge base
    """
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type='knowledge',
            resource_id=knowledge.id,
            permission='write',
            db=db,
        )
        and user.role != 'admin'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Batch-fetch all files to avoid N+1 queries
    log.info(f'files/batch/add - {len(form_data)} files')
    file_ids = [form.file_id for form in form_data]
    files = await Files.get_files_by_ids(file_ids, db=db)

    # Verify all requested files were found
    found_ids = {file.id for file in files}
    missing_ids = [fid for fid in file_ids if fid not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'File {missing_ids[0]} not found',
        )

    # Process files
    try:
        result = await process_files_batch(
            request=request,
            form_data=BatchProcessFilesForm(files=files, collection_name=id),
            user=user,
            db=db,
        )
    except Exception as e:
        log.error(f'add_files_to_knowledge_batch: Exception occurred: {e}', exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Only add files that were successfully processed
    successful_file_ids = [r.file_id for r in result.results if r.status == 'completed']
    for file_id in successful_file_ids:
        await Knowledges.add_file_to_knowledge_by_id(knowledge_id=id, file_id=file_id, user_id=user.id, db=db)

    # If there were any errors, include them in the response
    if result.errors:
        error_details = [f'{err.file_id}: {err.error}' for err in result.errors]
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=await Knowledges.get_file_metadatas_by_id(knowledge.id, db=db),
            warnings={
                'message': 'Some files failed to process',
                'errors': error_details,
            },
        )

    return KnowledgeFilesResponse(
        **knowledge.model_dump(),
        files=await Knowledges.get_file_metadatas_by_id(knowledge.id, db=db),
    )


############################
# ExportKnowledgeById
############################


@router.get('/{id}/export')
async def export_knowledge_by_id(id: str, user=Depends(get_admin_user), db: AsyncSession = Depends(get_async_session)):
    """
    Export a knowledge base as a zip file containing .txt files.
    Admin only.
    """

    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    files = await Knowledges.get_files_by_id(id, db=db)

    # Create zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            content = file.data.get('content', '') if file.data else ''
            if content:
                # Use original filename with .txt extension
                filename = file.filename
                if not filename.endswith('.txt'):
                    filename = f'{filename}.txt'
                zf.writestr(filename, content)

    zip_buffer.seek(0)

    # Sanitize knowledge name for filename
    # ASCII-safe fallback for the basic filename parameter (latin-1 safe)
    safe_name = ''.join(c if c.isascii() and (c.isalnum() or c in ' -_') else '_' for c in knowledge.name)
    zip_filename = f'{safe_name}.zip'

    # Use RFC 5987 filename* for non-ASCII names so the browser gets the real name
    quoted_name = quote(f'{knowledge.name}.zip')
    content_disposition = f'attachment; filename="{zip_filename}"; filename*=UTF-8\'\'{quoted_name}'

    return StreamingResponse(
        zip_buffer,
        media_type='application/zip',
        headers={'Content-Disposition': content_disposition},
    )


############################
# SharePoint Import
############################


class SharePointImportForm(BaseModel):
    drive_id: str
    item_id: str


class SharePointImportFileError(BaseModel):
    filename: str
    error: str


class SharePointImportResult(BaseModel):
    knowledge_id: str
    folder_name: str
    total_files: int
    imported: int
    failed: int
    errors: list[SharePointImportFileError]
    skipped_folders: list[str] = []
    truncated: bool = False


# Filesystem-safe path separator used when flattening subfolder paths into
# the uploaded filename (os.path.basename strips "/" and "\\" on Windows).
SHAREPOINT_PATH_SEPARATOR = " › "
SHAREPOINT_FILENAME_MAX = 250


def _build_display_filename(path: str, name: str) -> str:
    """Flatten a subfolder path into a display filename.

    Example: path="Invoices/2024/", name="report.pdf"
             → "Invoices › 2024 › report.pdf"
    """
    if not path:
        return name
    prefix = path.rstrip("/").replace("/", SHAREPOINT_PATH_SEPARATOR)
    combined = f"{prefix}{SHAREPOINT_PATH_SEPARATOR}{name}"
    if len(combined) <= SHAREPOINT_FILENAME_MAX:
        return combined
    # Truncate from the front — keep the original filename and its extension intact.
    overflow = len(combined) - SHAREPOINT_FILENAME_MAX + 1
    return f"…{combined[overflow:]}"


async def _assert_knowledge_write_access(knowledge, user, db):
    """Raise HTTPException if the user can't write to this KB."""
    if knowledge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if (
        knowledge.user_id != user.id
        and not await AccessGrants.has_access(
            user_id=user.id,
            resource_type="knowledge",
            resource_id=knowledge.id,
            permission="write",
            db=db,
        )
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


async def _get_microsoft_access_token(user, db) -> str:
    """Fetch the user's Microsoft OAuth token or raise an HTTP 401."""
    oauth_session = await OAuthSessions.get_session_by_provider_and_user_id(
        provider="microsoft", user_id=user.id, db=db
    )
    if not oauth_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No Microsoft OAuth session found. Please log in with Microsoft SSO first.",
        )
    access_token = oauth_session.token.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft OAuth session has no access token. Please re-login.",
        )
    return access_token


def _translate_graph_error(e: httpx.HTTPStatusError) -> HTTPException:
    """Normalise Microsoft Graph API errors to HTTPExceptions with hints."""
    if e.response.status_code == 401:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft token expired. Please re-login with Microsoft SSO.",
        )
    if e.response.status_code == 403:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied by Microsoft Graph API. Ensure Files.Read.All and Sites.Read.All scopes are granted.",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Microsoft Graph API error: {e.response.status_code}",
    )


async def _import_graph_files(
    request: Request,
    knowledge_id: str,
    graph: GraphClient,
    files: list[GraphFileItem],
    user,
    db: AsyncSession,
) -> tuple[int, list[SharePointImportFileError]]:
    """Download each Graph file and feed it through the KB upload pipeline.

    Returns (imported_count, errors). Files without a download URL and any
    exception during download/processing are captured per-file instead of
    aborting the whole import.
    """
    imported = 0
    errors: list[SharePointImportFileError] = []

    for graph_file in files:
        display_name = _build_display_filename(graph_file.path, graph_file.name)
        try:
            if not graph_file.download_url:
                errors.append(SharePointImportFileError(
                    filename=display_name,
                    error="No download URL provided by Graph API",
                ))
                continue

            content_bytes = await graph.download_file(graph_file.download_url)

            upload_file = UploadFile(
                file=io.BytesIO(content_bytes),
                filename=display_name,
                headers={
                    "content-type": graph_file.content_type
                    or "application/octet-stream"
                },
            )

            file_item = await upload_file_handler(
                request,
                file=upload_file,
                metadata={"knowledge_id": knowledge_id},
                process=True,
                process_in_background=False,
                user=user,
                db=db,
            )
            file_id = (
                file_item.get("id") if isinstance(file_item, dict) else file_item.id
            )

            await process_file(
                request,
                ProcessFileForm(file_id=file_id, collection_name=knowledge_id),
                user=user,
                db=db,
            )
            await Knowledges.add_file_to_knowledge_by_id(
                knowledge_id=knowledge_id,
                file_id=file_id,
                user_id=user.id,
                db=db,
            )
            imported += 1
        except Exception as e:
            log.warning(
                f"SharePoint import: failed to import {display_name}: {e}"
            )
            errors.append(SharePointImportFileError(
                filename=display_name,
                error=str(e),
            ))

    return imported, errors


async def _persist_sharepoint_source(knowledge, source: dict, db):
    meta = knowledge.meta or {}
    meta["sharepoint_source"] = source
    await Knowledges.update_knowledge_by_id(
        id=knowledge.id,
        form_data=KnowledgeForm(
            name=knowledge.name,
            description=knowledge.description,
            meta=meta,
        ),
        db=db,
    )


@router.post("/{id}/sharepoint/import", response_model=SharePointImportResult)
async def import_sharepoint_folder(
    request: Request,
    id: str,
    form_data: SharePointImportForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Import all files from a SharePoint/OneDrive folder into a knowledge base.

    Walks subfolders recursively; each file's origin path is flattened into
    the stored filename (see `_build_display_filename`). Uses the caller's
    Microsoft OAuth session token.
    """
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    await _assert_knowledge_write_access(knowledge, user, db)

    access_token = await _get_microsoft_access_token(user, db)
    graph = GraphClient(access_token)
    try:
        listing = await graph.list_folder(form_data.drive_id, form_data.item_id)
    except httpx.HTTPStatusError as e:
        raise _translate_graph_error(e)

    imported, errors = await _import_graph_files(
        request, id, graph, listing.files, user, db
    )

    if imported > 0:
        await _persist_sharepoint_source(
            knowledge,
            {
                "type": "folder",
                "drive_id": form_data.drive_id,
                "item_id": form_data.item_id,
                "folder_name": listing.folder_name,
                "folder_path": listing.folder_path,
                "last_imported_at": int(time.time()),
            },
            db,
        )

    return SharePointImportResult(
        knowledge_id=id,
        folder_name=listing.folder_name,
        total_files=len(listing.files),
        imported=imported,
        failed=len(errors),
        errors=errors,
        skipped_folders=listing.skipped_folders,
        truncated=listing.truncated,
    )


class SharePointSiteImportForm(BaseModel):
    site_id: str


@router.post("/{id}/sharepoint/import-site", response_model=SharePointImportResult)
async def import_sharepoint_site(
    request: Request,
    id: str,
    form_data: SharePointSiteImportForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Import every file from every document library of a SharePoint site.

    The drive name becomes the first segment of each file's display name,
    so files from different libraries remain distinguishable after import.
    """
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    await _assert_knowledge_write_access(knowledge, user, db)

    access_token = await _get_microsoft_access_token(user, db)
    graph = GraphClient(access_token)
    try:
        listing = await graph.list_site(form_data.site_id)
    except httpx.HTTPStatusError as e:
        raise _translate_graph_error(e)

    imported, errors = await _import_graph_files(
        request, id, graph, listing.files, user, db
    )

    if imported > 0:
        await _persist_sharepoint_source(
            knowledge,
            {
                "type": "site",
                "site_id": listing.site_id,
                "site_name": listing.site_name,
                "site_url": listing.site_url,
                "drive_count": len(listing.drives),
                "last_imported_at": int(time.time()),
            },
            db,
        )

    return SharePointImportResult(
        knowledge_id=id,
        folder_name=listing.site_name,
        total_files=len(listing.files),
        imported=imported,
        failed=len(errors),
        errors=errors,
        skipped_folders=[],
        truncated=listing.truncated,
    )


class SharePointSiteSearchResult(BaseModel):
    id: str
    name: str
    display_name: str
    web_url: str


@router.get(
    "/sharepoint/sites/search",
    response_model=list[SharePointSiteSearchResult],
)
async def search_sharepoint_sites(
    query: str = Query(..., min_length=1, max_length=100),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Search SharePoint sites the caller has access to.

    Thin wrapper over Graph `/sites?search=...`. Used by the custom picker
    to surface matches while the user types.
    """
    access_token = await _get_microsoft_access_token(user, db)
    graph = GraphClient(access_token)
    try:
        results = await graph.search_sites(query)
    except httpx.HTTPStatusError as e:
        raise _translate_graph_error(e)

    return [SharePointSiteSearchResult(**r) for r in results]


class SharePointSitesPage(BaseModel):
    sites: list[SharePointSiteSearchResult]
    next_link: Optional[str] = None


@router.get("/sharepoint/sites", response_model=SharePointSitesPage)
async def list_sharepoint_sites(
    query: str = Query("*", max_length=100),
    next_link: Optional[str] = Query(None),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of every SharePoint site the caller can read.

    First page: pass `query` (defaults to `*` wildcard). Subsequent pages:
    pass the opaque `next_link` returned in the previous response. Omit both
    to get the first wildcard page.
    """
    access_token = await _get_microsoft_access_token(user, db)
    graph = GraphClient(access_token)
    try:
        page = await graph.list_sites_paginated(query=query, next_link=next_link)
    except httpx.HTTPStatusError as e:
        raise _translate_graph_error(e)
    return SharePointSitesPage(
        sites=[SharePointSiteSearchResult(**s) for s in page["sites"]],
        next_link=page["next_link"],
    )


class SharePointDriveSummary(BaseModel):
    id: str
    name: str
    drive_type: str = ""
    root_item_id: str
    total_size: int = 0


class SharePointSiteDrivesResponse(BaseModel):
    site_name: str
    site_url: str
    drives: list[SharePointDriveSummary]


@router.get(
    "/sharepoint/sites/{site_id}/drives",
    response_model=SharePointSiteDrivesResponse,
)
async def list_sharepoint_site_drives(
    site_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """List all document libraries (drives) of a SharePoint site with size."""
    access_token = await _get_microsoft_access_token(user, db)
    graph = GraphClient(access_token)
    try:
        summary = await graph.list_site_drives_summary(site_id)
    except httpx.HTTPStatusError as e:
        raise _translate_graph_error(e)

    return SharePointSiteDrivesResponse(
        site_name=summary["site_name"],
        site_url=summary["site_url"],
        drives=[SharePointDriveSummary(**d) for d in summary["drives"]],
    )


class SharePointChildItem(BaseModel):
    id: str
    name: str
    is_folder: bool
    size: int = 0
    child_count: int = 0
    content_type: Optional[str] = None


class SharePointChildrenResponse(BaseModel):
    parent_name: str
    parent_size: int = 0
    folders: list[SharePointChildItem]
    files: list[SharePointChildItem]
    next_link: Optional[str] = None


@router.get(
    "/sharepoint/drives/{drive_id}/items/{item_id}/children",
    response_model=SharePointChildrenResponse,
)
async def list_sharepoint_folder_children(
    drive_id: str,
    item_id: str,
    next_link: Optional[str] = Query(None),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """One-level directory listing for a folder in a drive.

    Returns `folders` (with aggregate size + direct child count) and `files`
    (with size + content_type) plus a `next_link` cursor for pagination. First
    call omits `next_link`; subsequent pages echo back what the previous
    response returned. Sizes are pulled from Graph's `driveItem.size` so no
    recursive walk is required.
    """
    access_token = await _get_microsoft_access_token(user, db)
    graph = GraphClient(access_token)
    try:
        listing = await graph.list_folder_children(drive_id, item_id, next_link=next_link)
    except httpx.HTTPStatusError as e:
        raise _translate_graph_error(e)

    return SharePointChildrenResponse(
        parent_name=listing.parent_name,
        parent_size=listing.parent_size,
        folders=[SharePointChildItem(**f.model_dump()) for f in listing.folders],
        files=[SharePointChildItem(**f.model_dump()) for f in listing.files],
        next_link=listing.next_link,
    )


@router.post("/{id}/sharepoint/reimport", response_model=SharePointImportResult)
async def reimport_sharepoint_folder(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Re-import from the same SharePoint source previously configured.

    Dispatches based on `meta.sharepoint_source.type`: a missing or "folder"
    type replays the folder import; a "site" type re-imports every drive of
    the stored site. Existing-file deletion is handled inside the target
    import endpoint.
    """
    knowledge = await Knowledges.get_knowledge_by_id(id=id, db=db)
    await _assert_knowledge_write_access(knowledge, user, db)

    source = (knowledge.meta or {}).get("sharepoint_source")
    if not source:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No SharePoint source configured for this knowledge base. Import a folder or site first.",
        )

    source_type = source.get("type", "folder")

    if source_type == "site":
        return await import_sharepoint_site(
            request=request,
            id=id,
            form_data=SharePointSiteImportForm(site_id=source["site_id"]),
            user=user,
            db=db,
        )

    return await import_sharepoint_folder(
        request=request,
        id=id,
        form_data=SharePointImportForm(
            drive_id=source["drive_id"],
            item_id=source["item_id"],
        ),
        user=user,
        db=db,
    )
