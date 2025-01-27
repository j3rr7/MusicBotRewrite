import discord
import wavelink
from discord.ui import View


class QueueView(View):
    def __init__(self, player: wavelink.Player) -> None:
        super().__init__(timeout=180)
        self.player = player
        self.current_page = 0
        self.page_size = 10

    def create_embed(self) -> discord.Embed:
        start = self.current_page * self.page_size
        end = min((self.current_page + 1) * self.page_size, len(self.player.queue))

        if not self.player.queue and not self.player.current:
            return discord.Embed(
                title="Queue is empty!",
                description="No songs in queue.",
                color=discord.Color.red(),
            )

        description = []
        for i, track in enumerate(self.player.queue[start:end], start=start + 1):
            description.append(f"{i}. [{track.title}]({track.uri})")

        if self.player.current:
            description.insert(
                0,
                f"**Now Playing:** [{self.player.current.title}]({self.player.current.uri})",
            )

        embed = discord.Embed(
            title="Queue",
            description="\n".join(description),
            color=discord.Color.blue(),
        )

        total_pages = -(len(self.player.queue) // -self.page_size)
        embed.set_footer(text=f"Page {self.current_page + 1} of {total_pages}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        max_pages = -(len(self.player.queue) // -self.page_size)
        self.current_page = min(self.current_page + 1, max_pages - 1)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)
