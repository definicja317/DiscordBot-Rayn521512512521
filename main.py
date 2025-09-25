import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Bot has logged in as {bot.user}')

@bot.command()
async def some_command(ctx):
    # Example command
    await ctx.send('This is a command!')

@bot.interaction()
async def some_interaction(interaction):
    # Get member from guild instead of using interaction.user.roles
    member = interaction.guild.get_member(interaction.user.id)

    # Implement timeout handling
    await interaction.response.defer(ephemeral=True)  # Deferring response for timeout handling
    # Do something with member

# Run the bot as a daemon thread
if __name__ == '__main__':
    bot.run(os.getenv('DISCORD_TOKEN'), bot=True, reconnect=True)
