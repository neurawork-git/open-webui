"""Tests for the LDAP credential store.

Two groups, and the second one is the point of the file:

  * that the cryptography does what it claims (round-trip, AAD binding, fresh nonce), and
  * that the secret never appears in anything the outside world can see -- no response
    model, no log line, on success paths and failure paths alike.

The DB-backed cases run against in-memory SQLite with session sharing on, so the session
the test creates is the one the model layer uses.
"""

import base64
import logging
import os

import pytest
import pytest_asyncio

# Must be set before the model module reads it at construction time.
SENTINEL = 'S3ntinel-Pw-DoNotLeak'
TEST_KEY = base64.urlsafe_b64encode(b'k' * 32).decode()
OTHER_KEY = base64.urlsafe_b64encode(b'z' * 32).decode()

os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret-key')
os.environ['DATABASE_ENABLE_SESSION_SHARING'] = 'true'
os.environ['LDAP_CREDENTIAL_ENCRYPTION_KEY'] = TEST_KEY

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import open_webui.models.user_credentials as uc  # noqa: E402
from open_webui.internal.db import Base  # noqa: E402
from open_webui.models.user_credentials import (  # noqa: E402
    UserCredential,
    UserCredentialsTable,
)

USER_A = 'user-a'
USER_B = 'user-b'
ACCOUNT = 'SKKIEL\\mmuster'


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(uc, 'LDAP_CREDENTIAL_ENCRYPTION_KEY', TEST_KEY)
    return UserCredentialsTable()


@pytest_asyncio.fixture
async def db(monkeypatch):
    # Patch the constant, not the env var: `internal.db` binds it at import time, so by
    # the time this module runs in a full-suite session the env is already read. Without
    # this, get_async_db_context() ignores the session below and opens a real one.
    monkeypatch.setattr('open_webui.internal.db.DATABASE_ENABLE_SESSION_SHARING', True)

    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[UserCredential.__table__])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Cryptography
# ---------------------------------------------------------------------------


class TestCrypto:
    def test_roundtrip(self, table):
        assert table._decrypt(table._encrypt(SENTINEL, USER_A), USER_A) == SENTINEL

    def test_aad_binds_ciphertext_to_its_user(self, table):
        """The attack this prevents: someone with DB write access copies user A's
        ciphertext into user B's row and acts as A against SharePoint."""
        blob = table._encrypt(SENTINEL, USER_A)
        assert table._decrypt(blob, USER_B) is None

    def test_nonce_is_fresh_per_encryption(self, table):
        assert table._encrypt(SENTINEL, USER_A) != table._encrypt(SENTINEL, USER_A)

    def test_tampered_ciphertext_is_rejected(self, table):
        blob = table._encrypt(SENTINEL, USER_A)
        raw = bytearray(base64.urlsafe_b64decode(blob))
        raw[-1] ^= 0x01
        assert table._decrypt(base64.urlsafe_b64encode(bytes(raw)).decode(), USER_A) is None

    def test_missing_key_refuses_to_start(self, monkeypatch):
        monkeypatch.setattr(uc, 'LDAP_CREDENTIAL_ENCRYPTION_KEY', '')
        with pytest.raises(RuntimeError, match='not set'):
            UserCredentialsTable()

    def test_short_key_refuses_to_start(self, monkeypatch):
        """No silent SHA256 stretching, unlike the OAuth token store: a password vault
        must not come up on an improvised key."""
        monkeypatch.setattr(
            uc, 'LDAP_CREDENTIAL_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'short').decode()
        )
        with pytest.raises(RuntimeError, match='32 bytes'):
            UserCredentialsTable()


# ---------------------------------------------------------------------------
# Storage behaviour
# ---------------------------------------------------------------------------


class TestStorage:
    @pytest.mark.asyncio
    async def test_storing_is_the_default_for_an_unknown_user(self, table, db):
        """No row means "store". There is no consent dialog; the login writes."""
        assert await table.is_opted_out(USER_A, db=db) is False

        status = await table.get_status(USER_A, db=db)
        assert status.opted_in is True
        assert status.exists is False  # allowed, but nothing captured yet

    @pytest.mark.asyncio
    async def test_opt_out_is_remembered_without_a_prior_row(self, table, db):
        """The refusal itself is what has to persist -- otherwise the next login stores
        anyway and the delete button is theatre."""
        assert await table.set_opt_in(USER_A, False, db=db)
        assert await table.is_opted_out(USER_A, db=db) is True

    @pytest.mark.asyncio
    async def test_opt_out_survives_a_later_login_attempt(self, table, db):
        """Simulates: user opts out, then logs in again. Nothing may be stored."""
        await table.set_opt_in(USER_A, False, db=db)

        # what maybe_store_ldap_credential does
        if not await table.is_opted_out(USER_A, db=db):
            await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)

        assert await table.get_secret(USER_A, db=db) is None
        assert (await table.get_status(USER_A, db=db)).exists is False

    @pytest.mark.asyncio
    async def test_opting_back_in_allows_storage_again(self, table, db):
        await table.set_opt_in(USER_A, False, db=db)
        await table.set_opt_in(USER_A, True, db=db)

        assert await table.is_opted_out(USER_A, db=db) is False
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
        assert await table.get_secret(USER_A, db=db) == (ACCOUNT, SENTINEL)

    @pytest.mark.asyncio
    async def test_unreadable_state_fails_closed(self, table, monkeypatch):
        """If we cannot tell whether the user refused, do not store."""

        class _Boom:
            async def __aenter__(self):
                raise RuntimeError('db down')

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(uc, 'get_async_db_context', lambda db=None: _Boom())
        assert await table.is_opted_out(USER_A) is True

    @pytest.mark.asyncio
    async def test_upsert_then_read_back(self, table, db):
        await table.set_opt_in(USER_A, True, db=db)
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)

        assert await table.get_secret(USER_A, db=db) == (ACCOUNT, SENTINEL)

    @pytest.mark.asyncio
    async def test_upsert_overwrites_instead_of_duplicating(self, table, db):
        """A password change must be self-healing at the next login."""
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret='old-pw', db=db)
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret='new-pw', db=db)

        from sqlalchemy import select

        rows = (
            await db.execute(select(UserCredential).where(UserCredential.user_id == USER_A))
        ).scalars().all()
        assert len(rows) == 1
        assert await table.get_secret(USER_A, db=db) == (ACCOUNT, 'new-pw')

    @pytest.mark.asyncio
    async def test_expired_credential_returns_none_and_is_deleted(self, table, db):
        await table.upsert(
            user_id=USER_A, account=ACCOUNT, secret=SENTINEL, ttl_seconds=-1, db=db
        )
        assert await table.get_secret(USER_A, db=db) is None
        assert (await table.get_status(USER_A, db=db)).exists is False

    @pytest.mark.asyncio
    async def test_rotated_key_drops_the_row_without_touching_the_network(
        self, table, db, monkeypatch
    ):
        """A rotation invalidates every row. Detecting it locally is what keeps a stale
        credential from ever reaching the domain controller as a failed logon."""
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)

        monkeypatch.setattr(uc, 'LDAP_CREDENTIAL_ENCRYPTION_KEY', OTHER_KEY)
        rotated = UserCredentialsTable()
        assert rotated.key_id != table.key_id
        assert await rotated.get_secret(USER_A, db=db) is None
        assert (await rotated.get_status(USER_A, db=db)).exists is False

    @pytest.mark.asyncio
    async def test_withdrawing_consent_deletes_the_secret(self, table, db):
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
        await table.set_opt_in(USER_A, False, db=db)

        assert await table.get_secret(USER_A, db=db) is None
        status = await table.get_status(USER_A, db=db)
        assert status.opted_in is False and status.exists is False

    @pytest.mark.asyncio
    async def test_delete_removes_everything(self, table, db):
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
        assert await table.delete(USER_A, db=db)
        assert (await table.get_status(USER_A, db=db)).exists is False

    @pytest.mark.asyncio
    async def test_get_secret_records_last_used(self, table, db):
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
        assert (await table.get_status(USER_A, db=db)).last_used_at is None

        await table.get_secret(USER_A, db=db)
        assert (await table.get_status(USER_A, db=db)).last_used_at is not None

    @pytest.mark.asyncio
    async def test_users_are_isolated(self, table, db):
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
        assert await table.get_secret(USER_B, db=db) is None


# ---------------------------------------------------------------------------
# The sharp one: nothing leaks
# ---------------------------------------------------------------------------


class TestNoLeak:
    @pytest.mark.asyncio
    async def test_status_response_cannot_carry_the_secret(self, table, db):
        await table.set_opt_in(USER_A, True, db=db)
        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)

        status = await table.get_status(USER_A, db=db)
        assert SENTINEL not in status.model_dump_json()
        assert 'secret' not in status.model_dump()

    @pytest.mark.asyncio
    async def test_returned_model_cannot_carry_the_secret(self, table, db):
        model = await table.upsert(
            user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db
        )
        assert SENTINEL not in model.model_dump_json()
        assert 'secret' not in model.model_dump()

    @pytest.mark.asyncio
    async def test_no_log_line_contains_the_secret(self, table, db, caplog):
        """Covers the failure paths too -- that is where leaks actually happen."""
        with caplog.at_level(logging.DEBUG):
            await table.set_opt_in(USER_A, True, db=db)
            await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
            await table.get_secret(USER_A, db=db)
            await table.get_status(USER_A, db=db)

            # failure paths
            table._decrypt('not-base64-at-all', USER_A)
            table._decrypt(table._encrypt(SENTINEL, USER_A), USER_B)  # AAD mismatch
            await table.upsert(
                user_id=USER_B, account=ACCOUNT, secret=SENTINEL, ttl_seconds=-1, db=db
            )
            await table.get_secret(USER_B, db=db)  # expired -> delete path

            await table.delete(USER_A, db=db)

        for record in caplog.records:
            assert SENTINEL not in record.getMessage()
            assert SENTINEL not in str(record.args or '')

    @pytest.mark.asyncio
    async def test_stored_column_is_not_the_plaintext(self, table, db):
        from sqlalchemy import select

        await table.upsert(user_id=USER_A, account=ACCOUNT, secret=SENTINEL, db=db)
        row = (
            await db.execute(select(UserCredential).where(UserCredential.user_id == USER_A))
        ).scalar_one()

        assert row.secret != SENTINEL
        assert SENTINEL not in row.secret
        assert SENTINEL.encode() not in base64.urlsafe_b64decode(row.secret)
