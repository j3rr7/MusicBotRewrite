import json
import logging
import datetime
import pytz
import discord
import traceback
import aiohttp
from discord import app_commands
from discord.ext import commands, tasks
from config import HAPPI_KEY


class ExchangeAPI(commands.Cog):
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def cog_load(self):
        self.logger.info("ExchangeAPI cog loaded")
        self.daily_message.start()

    async def cog_unload(self):
        self.logger.info("ExchangeAPI cog unloaded")
        self.daily_message.stop()

    @tasks.loop(
        time=datetime.time(
            hour=8, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=7))
        ),  # GMT+7 (Asia/Jakarta)
    )
    async def daily_message(self):
        # TODO: add daily message
        self.logger.info("Daily message should sent here")
        pass

    @app_commands.command(
        name="exchangerate",
        description="Gets the current exchange rate between two currencies.",
    )
    @app_commands.describe(
        from_currency="The currency to convert from (e.g., USD).",
        to_currency="The currency to convert to (e.g., IDR).",
    )
    async def get_current_exchange_rate(
        self,
        interaction: discord.Interaction,
        from_currency: str = "USD",
        to_currency: str = "IDR",
    ):
        await interaction.response.defer()

        embed = discord.Embed(
            title=f"Exchange Rate ({from_currency} to {to_currency})",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(
            text="⚠️ Warning: This is an experimental feature. Use with caution! ⚠️"
        )

        try:
            url = f"https://api.happi.dev/v1/currency-convert?from={from_currency}&to={to_currency}&amount=1"
            headers = {"x-happi-token": HAPPI_KEY, "Accept": "application/json"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        rate = data.get("value")
                        if rate is not None:
                            embed.description = f"Fetched at: <t:{int(discord.utils.utcnow().timestamp())}:F>\n\n1 {from_currency} = {rate} {to_currency}"
                            await interaction.followup.send(embed=embed)
                        else:
                            await interaction.followup.send(
                                "Error: 'value' not found in API response. Check the currency codes."
                            )
                    else:
                        await interaction.followup.send(
                            f"Failed to fetch exchange rate. Status code: {response.status}"
                        )
        except aiohttp.ClientError as e:
            await interaction.followup.send(
                f"Failed to fetch exchange rate. Error: {e}"
            )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction[discord.Client],
        error: app_commands.AppCommandError,
    ) -> None:
        self.logger.error(traceback.format_exc())

        try:
            await interaction.response.send_message(
                "Error: " + str(error), ephemeral=True
            )
        except discord.errors.InteractionResponded:
            await interaction.followup.send("Error: " + str(error), ephemeral=True)


async def setup(bot):
    await bot.add_cog(ExchangeAPI(bot))
