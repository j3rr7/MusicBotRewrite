import aiohttp
import logging
import discord
import pytz
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta


class HolidayPaginator(discord.ui.View):
    def __init__(self, interaction, holidays, page_size=5):
        super().__init__(timeout=600)
        self.interaction = interaction
        self.holidays = holidays
        self.page_size = page_size
        self.current_page = 0
        self.total_pages = (len(self.holidays) + page_size - 1) // page_size

    async def update_embed(self):
        self.holidays = sorted(
            self.holidays, key=lambda h: h["formatted_date"], reverse=False
        )

        start = self.current_page * self.page_size
        end = min((self.current_page + 1) * self.page_size, len(self.holidays))
        current_holidays = self.holidays[start:end]

        embed = discord.Embed(
            title=f"Upcoming Holidays (Page {self.current_page + 1}/{self.total_pages})",
            color=discord.Color.blue(),
        )
        for holiday in current_holidays:
            embed.add_field(
                name=holiday["holiday_name"],
                value=f"Date: {holiday['formatted_date']}\nNational: {holiday['is_national_holiday']}",
                inline=False,
            )

        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1

        await self.interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page -= 1
        await self.update_embed()
        await interaction.response.defer()  # Important to prevent "interaction failed"

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page += 1
        await self.update_embed()
        await interaction.response.defer()  # Important to prevent "interaction failed"


class Holiday(commands.Cog):
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def cog_load(self):
        self.logger.info("Holiday cog loaded")

    async def cog_unload(self):
        self.logger.info("Holiday cog unloaded")

    @app_commands.command(
        name="holidays",
        description="Show available holidays",
    )
    async def holidays(
        self, interaction: discord.Interaction, national_only: bool = False
    ):
        await interaction.response.defer()

        async with aiohttp.ClientSession() as session:
            async with session.get("https://api-harilibur.netlify.app/api") as response:
                if response.status == 200:
                    holidays_data = await response.json()

                    if not holidays_data:
                        await interaction.followup.send("No holidays found.")
                        return

                    if national_only:
                        holidays_data = [
                            h for h in holidays_data if h["is_national_holiday"]
                        ]

                    # Convert dates to timestamps and format
                    for holiday in holidays_data:
                        date_obj = datetime.strptime(
                            holiday["holiday_date"], "%Y-%m-%d"
                        ).replace(tzinfo=pytz.timezone("Asia/Jakarta"))
                        timestamp = int(date_obj.timestamp())
                        holiday["formatted_date"] = f"<t:{timestamp}:R>"

                    view = HolidayPaginator(interaction, holidays_data)
                    await view.update_embed()

                else:
                    await interaction.followup.send(
                        f"Error: Status code {response.status}"
                    )


async def setup(bot):
    await bot.add_cog(Holiday(bot))
