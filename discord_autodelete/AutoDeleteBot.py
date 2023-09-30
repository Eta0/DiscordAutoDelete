import asyncio
import datetime
import logging
import os
import sys
from itertools import groupby
from typing import Optional, Sequence

import discord
from discord.ext import commands, tasks

from .MessageRegistry import MessageRegistry


class AutoDeleteBot(commands.Bot):
    def __init__(self, sync_commands: bool, db_path: str, log_path: str, *, protect_pins: bool = False):
        self.sync = sync_commands
        self.db_path = db_path
        self.log_path = log_path
        self._setup_logger()
        self.work_pending = asyncio.Event()
        self.delete_lock = asyncio.Lock()
        self.wake_time = discord.utils.utcnow()
        self.active_sleep = None
        self.protect_pins = protect_pins

        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        application_id = int(os.getenv("APPLICATION_ID"))
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            application_id=application_id,
        )

    def _setup_logger(self) -> None:
        # Bot logs
        self.logger = logging.getLogger("AutoDelete")
        self.logger.setLevel(logging.WARNING)
        self.logger.propagate = False

        local = os.getenv("LOCAL")
        if local:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "[{levelname:^7}] {asctime} {name}: {message}",
                datefmt="%H:%M:%S",
                style="{",
            )
        else:
            handler = logging.FileHandler(self.log_path, "a", "utf-8", delay=True)
            formatter = logging.Formatter(
                "[{levelname:^7}] {asctime} {name}: {message}",
                datefmt="%Y-%m-%d %H:%M:%S",
                style="{",
            )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        # discord.py logs
        self.discord_logger = logging.getLogger("discord")
        self.discord_logger.setLevel(logging.WARNING)
        self.discord_logger.addHandler(handler)

    async def __aenter__(self):
        self.message_registry = await MessageRegistry.open(client=self, db_path=self.db_path)
        self.add_listener(self._register_message_for_deletion, "on_message")
        return await super().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.message_registry.close()
        return await super().__aexit__(exc_type, exc_val, exc_tb)

    async def _register_message_for_deletion(self, message: discord.Message) -> Optional[datetime.datetime]:
        delete_at = await self.message_registry.register_message(message)
        if delete_at is not None:
            self.work_pending.set()
            await self._shorten_sleep(delete_at)
        return delete_at

    async def scan_channel(self, channel: discord.TextChannel, from_beginning: bool = False) -> None:
        self.logger.debug(f"Scanning channel {channel.id}.")
        channel_config = self.message_registry.channels.get(channel.id)
        if channel_config is None:
            raise ValueError("Cannot scan unregistered channel.")

        after = channel_config.after
        if not from_beginning:
            latest_message = await self.message_registry.get_latest_message(channel.id)
            if latest_message is not None and latest_message.created_at > after.created_at:
                after = latest_message

        found_count = 0
        async for message in channel.history(limit=None, after=after, oldest_first=True):
            found_count += await self._register_message_for_deletion(message) is not None
        self.logger.debug(f"Finished scanning channel {channel.id}, found {found_count} messages.")

    async def fetch_or_deregister_channel(self, channel_id: int):
        channel = self.get_channel(channel_id)
        if channel is not None:
            return channel
        else:
            try:
                return await self.fetch_channel(channel_id)
            except discord.NotFound:
                await self.message_registry.deregister_channel(channel_id)
                raise

    async def scan_all_channels(self, from_beginning: bool = False) -> None:
        await self.wait_until_ready()
        channels = []
        for channel_id in self.message_registry.channels:
            try:
                channels.append(self.get_channel(channel_id) or await self.fetch_or_deregister_channel(channel_id))
            except discord.NotFound:
                continue
        await asyncio.gather(*(self.scan_channel(channel, from_beginning) for channel in channels))

    async def _begin_monitor(self):
        await self.scan_all_channels()
        self.monitor_expired_messages.start()
        self.monitor_expired_messages.add_exception_type(discord.DiscordServerError)
        # on_ready events after the first may imply that the bot was temporarily disconnected
        # to the extent that it cannot replay missed events, so it may have missed some messages
        self.add_listener(self.scan_all_channels, name="on_ready")

    async def is_protected_message(self, message: discord.PartialMessage):
        # Protects pinned messages from deletion
        try:
            m = await message.fetch()
            return m.pinned
        except discord.HTTPException:
            return False

    async def clear_expired_messages(self) -> None:
        async with self.delete_lock:
            async with self.message_registry:
                # Assume by default that pending work will be finished by the end of this action.
                # If this assumption is true, this will find no more messages on its next check, and pause
                # until more messages become available. If it is false, then it won't need to check this anyway.
                self.work_pending.clear()
                messages = await self.message_registry.pop_expired_messages()
                messages_by_channel = groupby(messages, lambda m: m.channel)

                skipped_count = 0
                deletion_reason = "Time-based autodelete"
                deletions = []
                for partial_channel, message_group_iter in messages_by_channel:
                    # Dynamic deletion strategy based on bulk message delete limitations.
                    partial_channel: discord.PartialMessageable
                    message_group: Sequence[discord.PartialMessage] = tuple(message_group_iter)
                    if self.protect_pins:
                        unfiltered_message_count = len(message_group)
                        if unfiltered_message_count > 1:
                            # Retrieve a list of pins to compare against in a single request,
                            # rather than fetching each message individually and checking its pinned status.
                            try:
                                channel_pins = {m.id for m in await partial_channel.pins()}
                                message_group = tuple(m for m in message_group if m.id not in channel_pins)
                            except discord.HTTPException:
                                pass
                        elif message_group and self.is_protected_message(message_group[0]):
                            message_group = ()
                        if not message_group:
                            continue
                        skipped_count += unfiltered_message_count - len(message_group)
                    time_limit = discord.utils.utcnow() - datetime.timedelta(days=13.8)  # 14 days, plus margin of error
                    bulk_deletable = tuple(m for m in message_group if m.created_at > time_limit)
                    non_bulk_deletable = (m for m in message_group if m.created_at <= time_limit)

                    if len(bulk_deletable) == 1:
                        deletions.append(bulk_deletable[0].delete())
                    elif bulk_deletable:
                        # 2+ messages
                        try:
                            channel = self.get_channel(partial_channel.id) or await self.fetch_or_deregister_channel(
                                partial_channel.id
                            )
                        except discord.HTTPException:
                            continue
                        for start in range(0, len(bulk_deletable), 100):
                            # Discord limits bulk deletions to 100 messages per API call.
                            end = start + 100
                            chunk = bulk_deletable[start:end]
                            deletions.append(channel.delete_messages(chunk, reason=deletion_reason))

                    for m in non_bulk_deletable:
                        # Messages older than 14 days cannot be bulk-deleted.
                        deletions.append(m.delete())

                attempt_count = len(messages) - skipped_count
                failure_count = 0
                for message, result in zip(messages, await asyncio.gather(*deletions, return_exceptions=True)):
                    if isinstance(result, Exception):
                        failure_count += 1
                        message_identifier = f"{message.channel.id}-{message.id}"
                        if isinstance(result, discord.Forbidden):
                            # Can't do anything, but permissions could be different in other channels, so continue.
                            self.logger.warning(
                                f"Failed to delete message {message_identifier} due to insufficient permissions."
                            )
                            continue
                        elif isinstance(result, discord.NotFound):
                            # Most likely already deleted
                            self.logger.info(f"Failed to delete message {message_identifier} as it was not found.")
                            continue
                        elif isinstance(result, discord.HTTPException):
                            self.logger.warning(
                                f"Failed to delete message {message_identifier} due to"
                                f" HTTP error {result.status}: {result.text}"
                            )
                            # This compromises the validity of this operation.
                            # The messages in the database shouldn't be cleared, so let it interrupt the function.
                        raise result
                if attempt_count > 0:
                    self.logger.debug(
                        f"Cleared {attempt_count - failure_count} messages"
                        + (f" ({failure_count} failed)." if failure_count else ".")
                    )

    @tasks.loop(reconnect=True)
    async def monitor_expired_messages(self):
        await self.wait_until_ready()
        self.logger.debug("Starting monitor.")
        while True:
            await self.clear_expired_messages()
            self.logger.debug("Finished clearing messages, beginning wait.")
            await self._wait_until_needed()
            self.logger.debug("Finished wait, beginning clearing messages.")

    async def _shorten_sleep(self, dt: datetime.datetime) -> None:
        if dt < self.wake_time:
            self.wake_time = dt
            if self.active_sleep is not None:
                self.active_sleep.cancel()

    async def _sleep_until(self) -> None:
        """
        Sleeps until self.wake_time.
        This sleep may be modified by changing self.wake_time and then cancelling self.active_sleep.
        It is not safe to run this method multiple times concurrently.
        """
        while True:
            sleeping_until = self.wake_time
            seconds = (sleeping_until - discord.utils.utcnow()).total_seconds()
            if seconds > 0:
                try:
                    self.active_sleep = asyncio.create_task(asyncio.sleep(seconds))
                    await self.active_sleep
                    return
                except asyncio.CancelledError:
                    # This could mean that the timer changed.
                    if sleeping_until == self.wake_time:
                        # Timer didn't change; unrelated cancellation
                        raise
                finally:
                    self.active_sleep = None
            else:
                return

    async def _wait_until_needed(self) -> None:
        (
            next_message,
            delete_at,
        ) = await self.message_registry.get_next_expiring_message()
        if next_message is None:
            await self.work_pending.wait()
        else:
            # Sleep until the next message is queued for deletion.
            # This sleep may be shortened if a new message is inserted with an earlier deletion time.
            self.wake_time = delete_at
            await self._sleep_until()

    async def setup_hook(self) -> None:
        if self.sync:
            await self.tree.sync()
        asyncio.create_task(self._begin_monitor())

    async def on_ready(self):
        self.logger.info("Bot ready.")
