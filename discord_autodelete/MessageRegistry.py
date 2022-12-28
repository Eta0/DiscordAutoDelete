import datetime
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Dict, Sequence, Tuple, Optional

import aiosqlite
import discord


@dataclass
class AutoDeleteChannel:
    id: int
    duration: datetime.timedelta
    after: discord.Object


class MessageRegistry(AbstractAsyncContextManager):
    """
    Manages database entries for autodelete channels and messages pending deletion.
    This class must be constructed using its `open` factory method,
    and may be used as a context manager to commit or rollback database edits on exit.
    Note that, like with sqlite3 connections, the context manager form does not open or close the connection itself.
    """

    def __init__(self, client: discord.Client, db: aiosqlite.Connection):
        self.client = client
        self.channels: Dict[int, AutoDeleteChannel] = {}
        self.db = db

    @classmethod
    async def open(cls, client: discord.Client, db_path: str) -> "MessageRegistry":
        message_registry = MessageRegistry(client, await aiosqlite.connect(db_path))
        await message_registry._init_db()
        await message_registry._init_channels()
        return message_registry

    async def close(self) -> None:
        await self.db.close()

    async def _init_db(self) -> None:
        await self.db.executescript(r"""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER NOT NULL PRIMARY KEY,
                duration_seconds INTEGER NOT NULL,
                after INTEGER NOT NULL
            );
           
            CREATE TABLE IF NOT EXISTS messages (
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                delete_at INTEGER NOT NULL,
                FOREIGN KEY (channel_id)
                    REFERENCES channels (channel_id)
                    ON DELETE CASCADE,
                PRIMARY KEY (channel_id, message_id)
            );
            
            PRAGMA foreign_keys = ON;
           """)
        self.db.row_factory = aiosqlite.Row

    async def _init_channels(self) -> None:
        async with self.db.execute(r""" SELECT * FROM channels; """) as cursor:
            cursor: aiosqlite.Cursor
            async for c in cursor:
                channel_id = c["channel_id"]
                duration = datetime.timedelta(seconds=c["duration_seconds"])
                after = discord.Object(c["after"])
                self.channels[channel_id] = AutoDeleteChannel(id=channel_id, duration=duration, after=after)

    async def pop_expired_messages(self) -> Sequence[discord.PartialMessage]:
        now = discord.utils.time_snowflake(discord.utils.utcnow(), high=False)
        # channels.after may have been updated since the deletion was originally scheduled
        # so it is important to filter the result set here.
        # Ordering by the channel ID allows for itertools.groupby to be used on the output data.
        async with self.db.execute(
            r"""
            SELECT messages.channel_id, message_id FROM messages
            INNER JOIN channels ON channels.channel_id = messages.channel_id
            WHERE ? >= delete_at and message_id > channels.after
            ORDER BY messages.channel_id;
            """,
            (now,),
        ) as cursor:
            cursor: aiosqlite.Cursor

            messages = tuple(map(self._row_to_partial_message, await cursor.fetchall()))

            # This will implicitly open a transaction according to Python's DB API
            # which must be committed externally, once the *calling function* has used the data it retrieved.
            await cursor.execute(
                r"""
                DELETE FROM messages
                WHERE ? >= delete_at;
                """,
                (now,),
            )

            return messages

    def _row_to_partial_message(self, row: aiosqlite.Row) -> discord.PartialMessage:
        channel_id = row["channel_id"]
        message_id = row["message_id"]
        return discord.PartialMessage(
            channel=self.client.get_partial_messageable(id=channel_id),
            id=message_id,
        )

    async def get_next_expiring_message(
        self,
    ) -> Tuple[Optional[discord.PartialMessage], Optional[datetime.datetime]]:
        async with self.db.execute(r"""
                SELECT channel_id, message_id, delete_at FROM messages
                ORDER BY delete_at
                LIMIT 1;
                """) as cursor:
            cursor: aiosqlite.Cursor
            m = await cursor.fetchone()
            if m is not None:
                delete_at = discord.utils.snowflake_time(m["delete_at"])
                return self._row_to_partial_message(m), delete_at
            else:
                return None, None

    async def register_message(self, message: discord.Message) -> Optional[datetime.datetime]:
        channel_config = self.channels.get(message.channel.id)
        if channel_config is None:
            return None

        delete_at = message.created_at + channel_config.duration
        await self.db.execute(
            r"""
            INSERT INTO messages(channel_id, message_id, delete_at) VALUES (?, ?, ?);
            """,
            (message.channel.id, message.id, discord.utils.time_snowflake(delete_at)),
        )
        await self.db.commit()
        return delete_at

    async def register_channel(self, channel_config: AutoDeleteChannel):
        assert channel_config.duration.total_seconds() > 0
        await self.db.execute(r""" DELETE FROM channels WHERE channel_id = ?; """, (channel_config.id,))
        # "On conflict" clause is relevant to prevent race conditions
        await self.db.execute(
            r"""
            INSERT INTO channels(channel_id, duration_seconds, after) VALUES (?, ?, ?)
            ON CONFLICT (channel_id) DO UPDATE SET duration_seconds = excluded.duration_seconds, after = excluded.after;
            """,
            (channel_config.id, channel_config.duration.total_seconds(), channel_config.after.id),
        )
        await self.db.commit()
        # Since self.channels is used for preliminary checks, it should be updated last.
        self.channels[channel_config.id] = channel_config

    async def deregister_channel(self, channel: int) -> bool:
        try:
            del self.channels[channel]
        except KeyError:
            # Channel was already deregistered
            return False

        await self.db.execute(r""" DELETE FROM channels WHERE channel_id = ?; """, (channel,))
        await self.db.commit()
        return True

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            await self.db.commit()
        else:
            await self.db.rollback()

    async def get_latest_message(self, channel: int) -> Optional[discord.PartialMessage]:
        async with self.db.execute(
            r"""
            SELECT channel_id, message_id FROM messages WHERE channel_id = ?
            ORDER BY message_id DESC
            LIMIT 1;
            """,
            (channel,),
        ) as cursor:
            m = await cursor.fetchone()
            if m is not None:
                return self._row_to_partial_message(m)
