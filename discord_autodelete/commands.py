import datetime
from typing import Optional

import discord
import pytimeparse
from discord import app_commands

from .AutoDeleteBot import AutoDeleteBot
from .MessageRegistry import AutoDeleteChannel


# noinspection PyAbstractClass
class DurationTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> Optional[datetime.timedelta]:
        seconds = pytimeparse.parse(value)
        return None if seconds is None else datetime.timedelta(seconds=seconds)


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class AutoDeleteChannelControl(app_commands.Group):
    def __init__(self, **kwargs):
        super().__init__(
            name="autodelete",
            description="Configure channels with autodelete enabled.",
            **kwargs,
        )

    @app_commands.command(
        name="list",
        description="List channels with autodeletion enabled.",
        auto_locale_strings=False,
    )
    async def channels_list(self, interaction: discord.Interaction) -> None:
        """List channels with autodeletion enabled."""
        # noinspection PyTypeChecker
        bot: AutoDeleteBot = interaction.client

        index = []
        for channel_id, config in bot.message_registry.channels.items():
            try:
                channel = bot.get_channel(channel_id) or await bot.fetch_or_deregister_channel(channel_id)
            except discord.HTTPException:
                continue
            if channel.guild.id == interaction.guild_id:
                index.append(f"{channel.mention}, duration: {config.duration}")

        if index:
            index.insert(0, "Channels with autodelete enabled:")
            message = "\n".join(index) + "."
        else:
            message = "No channels currently have autodelete enabled."
        await interaction.response.send_message(message)

    @app_commands.command(
        name="enable",
        description="Configure a channel for message autodeletion.",
        auto_locale_strings=False,
    )
    async def channels_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        duration: app_commands.Transform[Optional[datetime.timedelta], DurationTransformer],
    ) -> None:
        """Configure a channel for message autodeletion."""
        if duration is None:
            await interaction.response.send_message(
                (
                    "The provided duration could not be understood. "
                    "Please use a recognized time format such as "
                    "`1 week`, `1h, 30m`, `30 minutes`, or `00:00:10`."
                ),
                ephemeral=True,
            )
            return

        if duration.total_seconds() <= 0:
            await interaction.response.send_message("Invalid duration. The duration must be positive.", ephemeral=True)
            return
        # noinspection PyTypeChecker
        bot: AutoDeleteBot = interaction.client

        if channel.guild.id != interaction.guild_id:
            await interaction.response.send_message("That channel does not belong to this server.", ephemeral=True)
            return

        if not channel.permissions_for(channel.guild.me).manage_messages:
            await interaction.response.send_message(
                "I don't have permission to delete messages in that channel.",
                ephemeral=True,
            )
            return

        # The response is sent first so that the response message is not subject to autodelete,
        # per calculation of `after`.
        await interaction.response.send_message(
            f"Enabled autodelete in channel {channel.mention} with message duration {duration}."
        )
        response = await interaction.original_response()
        after = discord.Object(response.id)
        try:
            await bot.message_registry.register_channel(AutoDeleteChannel(channel.id, duration, after))
        except Exception:
            await response.edit(content=f"Failed to enable autodelete in channel {channel.mention}.")
            raise

    @app_commands.command(
        name="disable",
        description="Turn off message autodeletion for a channel.",
        auto_locale_strings=False,
    )
    async def channels_remove(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """Turn off message autodeletion for a channel."""
        # noinspection PyTypeChecker
        bot: AutoDeleteBot = interaction.client

        if channel.guild.id != interaction.guild_id:
            await interaction.response.send_message("That channel does not belong to this server.", ephemeral=True)
            return

        if await bot.message_registry.deregister_channel(channel.id):
            response = f"Disabled autodelete in {channel.mention}."
        else:
            response = f"Autodelete is not enabled in {channel.mention}."
        await interaction.response.send_message(response)
