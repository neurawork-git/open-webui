"""Encrypted per-user credentials for NTLM-only on-prem services (fork-local).

Mirrors `models/oauth_sessions.py` in shape -- table, Pydantic model, `*Table` class,
`get_async_db_context(db)` in every method -- but deliberately NOT in its cryptography.
An OAuth token is short-lived and replaceable; an AD password is neither.  The two
differences that matter:

  * AES-256-GCM instead of Fernet, with `user_id` as additional authenticated data, so a
    ciphertext copied from one user's row into another's fails to decrypt.  Without that,
    anyone able to write to the DB could act as any user against SharePoint -- which is
    the whole permission model this feature exists to preserve.
  * A missing or malformed key raises instead of being silently stretched.  A password
    store must not come up on an improvised key.

Nothing here ever returns the secret over an API; the only reader is
`utils/sharepoint_backend.py`.
"""

import base64
import hashlib
import logging
import os
import time
import uuid
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from open_webui.env import LDAP_CREDENTIAL_ENCRYPTION_KEY, LDAP_CREDENTIAL_TTL
from open_webui.internal.db import Base, get_async_db_context
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, Index, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

NONCE_BYTES = 12  # AES-GCM standard; never derive, always random per encryption

####################
# DB MODEL
####################


class UserCredential(Base):
    __tablename__ = 'user_credential'

    id = Column(Text, primary_key=True, unique=True)
    user_id = Column(Text, nullable=False)
    realm = Column(Text, nullable=False)  # 'ad' today; room for further systems
    account = Column(Text, nullable=False)  # DOMAIN\user -- not a secret
    secret = Column(Text, nullable=True)  # base64(nonce + AES-GCM ciphertext)
    key_id = Column(Text, nullable=True)  # which key encrypted `secret`
    # Storing is the default; this column only ever records an explicit refusal.
    opted_in = Column(Boolean, nullable=False, default=True)
    expires_at = Column(BigInteger, nullable=False, default=0)
    last_used_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('idx_user_credential_user_realm', 'user_id', 'realm', unique=True),
        Index('idx_user_credential_expires_at', 'expires_at'),
    )


class UserCredentialModel(BaseModel):
    """Metadata only -- `secret` is intentionally absent so it cannot leak by accident."""

    id: str
    user_id: str
    realm: str
    account: str
    opted_in: bool
    expires_at: int
    last_used_at: Optional[int] = None
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class UserCredentialStatusResponse(BaseModel):
    exists: bool
    opted_in: bool
    account: Optional[str] = None
    expires_at: Optional[int] = None
    last_used_at: Optional[int] = None


class UserCredentialsTable:
    def __init__(self):
        if not LDAP_CREDENTIAL_ENCRYPTION_KEY:
            raise RuntimeError(
                'LDAP_CREDENTIAL_ENCRYPTION_KEY is not set. The LDAP credential store '
                'refuses to start without it -- it must not fall back to WEBUI_SECRET_KEY. '
                'Generate one with: '
                'python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"'
            )

        try:
            key = base64.urlsafe_b64decode(LDAP_CREDENTIAL_ENCRYPTION_KEY)
        except Exception as e:
            raise RuntimeError(
                'LDAP_CREDENTIAL_ENCRYPTION_KEY is not valid url-safe base64.'
            ) from e

        if len(key) != 32:
            raise RuntimeError(
                f'LDAP_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes for AES-256-GCM, '
                f'got {len(key)}. It is deliberately not stretched -- generate a real key.'
            )

        self._aesgcm = AESGCM(key)
        # Identifies the key without revealing it, so a row encrypted under an older key
        # is recognised locally instead of failing somewhere downstream.
        self.key_id = hashlib.sha256(key).hexdigest()[:12]

    def _encrypt(self, plaintext: str, user_id: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode(), user_id.encode())
        return base64.urlsafe_b64encode(nonce + ct).decode()

    def _decrypt(self, blob: str, user_id: str) -> Optional[str]:
        """Returns None on any failure. Never logs the value or the exception detail."""
        try:
            raw = base64.urlsafe_b64decode(blob)
            return self._aesgcm.decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], user_id.encode()
            ).decode()
        except InvalidTag:
            # Wrong key, or the ciphertext belongs to a different user_id (AAD mismatch).
            log.warning('Credential decryption failed: authentication tag mismatch')
            return None
        except Exception as e:
            log.warning('Credential decryption failed: %s', type(e).__name__)
            return None

    async def is_opted_out(
        self, user_id: str, realm: str = 'ad', db: Optional[AsyncSession] = None
    ) -> bool:
        """True only when the user explicitly said no.

        Storing is the default, so the absence of a row means "store". The distinction
        matters: without it a user who deletes their credential would get it silently
        re-stored at the next login, which makes the delete button theatre.
        """
        try:
            async with get_async_db_context(db) as db:
                row = (
                    await db.execute(
                        select(UserCredential).where(
                            UserCredential.user_id == user_id,
                            UserCredential.realm == realm,
                        )
                    )
                ).scalar_one_or_none()
                return row is not None and not row.opted_in
        except Exception as e:
            # Fail closed: if we cannot tell, do not store.
            log.error(f'Error reading credential opt-out: {e}')
            return True

    async def set_opt_in(
        self, user_id: str, value: bool, realm: str = 'ad', db: Optional[AsyncSession] = None
    ) -> bool:
        """Set the user's choice. Storing is on by default, so this is mainly used to turn
        it OFF -- and that choice has to survive, or the next login just re-stores.
        Turning it off drops any stored secret immediately."""
        try:
            async with get_async_db_context(db) as db:
                now = int(time.time())
                row = (
                    await db.execute(
                        select(UserCredential).where(
                            UserCredential.user_id == user_id,
                            UserCredential.realm == realm,
                        )
                    )
                ).scalar_one_or_none()

                if row is None:
                    # A row is created even for `value=False`: the refusal is exactly what
                    # has to be remembered, otherwise the next login stores anyway.
                    db.add(
                        UserCredential(
                            id=str(uuid.uuid4()),
                            user_id=user_id,
                            realm=realm,
                            account='',
                            secret=None,
                            key_id=None,
                            opted_in=value,
                            expires_at=0,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    row.opted_in = value
                    row.updated_at = now
                    if not value:
                        row.secret = None
                        row.key_id = None
                        row.expires_at = 0

                await db.commit()
                return True
        except Exception as e:
            log.error(f'Error setting credential opt-in: {e}')
            return False

    async def upsert(
        self,
        user_id: str,
        account: str,
        secret: str,
        realm: str = 'ad',
        ttl_seconds: Optional[int] = None,
        db: Optional[AsyncSession] = None,
    ) -> Optional[UserCredentialModel]:
        """Store (or replace) the credential. Encryption happens here, never in the caller.

        Overwriting on every successful login is what makes a password change self-healing.
        """
        try:
            async with get_async_db_context(db) as db:
                now = int(time.time())
                ttl = LDAP_CREDENTIAL_TTL if ttl_seconds is None else ttl_seconds

                row = (
                    await db.execute(
                        select(UserCredential).where(
                            UserCredential.user_id == user_id,
                            UserCredential.realm == realm,
                        )
                    )
                ).scalar_one_or_none()

                if row is None:
                    row = UserCredential(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        realm=realm,
                        opted_in=True,
                        created_at=now,
                    )
                    db.add(row)

                row.account = account
                row.secret = self._encrypt(secret, user_id)
                row.key_id = self.key_id
                row.expires_at = now + ttl
                row.updated_at = now

                await db.commit()
                # Copy before the session closes, as in OAuthSessionTable.
                return UserCredentialModel(
                    id=row.id,
                    user_id=row.user_id,
                    realm=row.realm,
                    account=row.account,
                    opted_in=row.opted_in,
                    expires_at=row.expires_at,
                    last_used_at=row.last_used_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
        except Exception as e:
            log.error(f'Error storing user credential: {e}')
            return None

    async def get_secret(
        self, user_id: str, realm: str = 'ad', db: Optional[AsyncSession] = None
    ) -> Optional[tuple[str, str]]:
        """(account, password) or None. Deletes the row when it is expired or unreadable.

        Unreadable means the key rotated or the ciphertext was tampered with.  Either way
        the row is worthless, and deleting it locally is what keeps a stale credential
        from ever reaching the domain controller as a failed logon.
        """
        try:
            async with get_async_db_context(db) as db:
                row = (
                    await db.execute(
                        select(UserCredential).where(
                            UserCredential.user_id == user_id,
                            UserCredential.realm == realm,
                        )
                    )
                ).scalar_one_or_none()

                if row is None or not row.secret:
                    return None

                now = int(time.time())
                if row.expires_at and row.expires_at < now:
                    log.info('Stored credential expired, deleting')
                    await db.delete(row)
                    await db.commit()
                    return None

                # ponytail: single active key. A rotation invalidates every row and each
                # user re-arms it at the next login -- no failed logon reaches the DC,
                # because this check is local. Accept a list of old keys here if a
                # rotation without re-login ever becomes a requirement.
                if row.key_id and row.key_id != self.key_id:
                    log.warning('Stored credential was encrypted under another key, deleting')
                    await db.delete(row)
                    await db.commit()
                    return None

                plaintext = self._decrypt(row.secret, user_id)
                if plaintext is None:
                    await db.delete(row)
                    await db.commit()
                    return None

                row.last_used_at = now
                await db.commit()
                return (row.account, plaintext)
        except Exception as e:
            log.error(f'Error reading user credential: {e}')
            return None

    async def get_status(
        self, user_id: str, realm: str = 'ad', db: Optional[AsyncSession] = None
    ) -> UserCredentialStatusResponse:
        try:
            async with get_async_db_context(db) as db:
                row = (
                    await db.execute(
                        select(UserCredential).where(
                            UserCredential.user_id == user_id,
                            UserCredential.realm == realm,
                        )
                    )
                ).scalar_one_or_none()

                if row is None:
                    return UserCredentialStatusResponse(exists=False, opted_in=True)
                return UserCredentialStatusResponse(
                    exists=bool(row.secret),
                    opted_in=bool(row.opted_in),
                    account=row.account or None,
                    expires_at=row.expires_at or None,
                    last_used_at=row.last_used_at,
                )
        except Exception as e:
            log.error(f'Error reading credential status: {e}')
            return UserCredentialStatusResponse(exists=False, opted_in=True)

    async def delete(
        self, user_id: str, realm: str = 'ad', db: Optional[AsyncSession] = None
    ) -> bool:
        try:
            async with get_async_db_context(db) as db:
                await db.execute(
                    delete(UserCredential).where(
                        UserCredential.user_id == user_id,
                        UserCredential.realm == realm,
                    )
                )
                await db.commit()
                return True
        except Exception as e:
            log.error(f'Error deleting user credential: {e}')
            return False

    async def delete_expired(self, db: Optional[AsyncSession] = None) -> int:
        try:
            async with get_async_db_context(db) as db:
                result = await db.execute(
                    delete(UserCredential).where(
                        UserCredential.expires_at > 0,
                        UserCredential.expires_at < int(time.time()),
                    )
                )
                await db.commit()
                return result.rowcount or 0
        except Exception as e:
            log.error(f'Error deleting expired user credentials: {e}')
            return 0


_table: Optional[UserCredentialsTable] = None


def get_user_credentials() -> UserCredentialsTable:
    """Lazy singleton.  Instantiating at import time would break every deployment that
    does not set LDAP_CREDENTIAL_ENCRYPTION_KEY -- i.e. every one except KHKI."""
    global _table
    if _table is None:
        _table = UserCredentialsTable()
    return _table
