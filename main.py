import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime

# --- Flask ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot działa!"

# --- Token ---
load_dotenv()
token = os.getenv("DISCORD_BOT_TOKEN")
if not token:
    print("Błąd: brak tokena Discord. Ustaw DISCORD_BOT_TOKEN w Render lub w .env")
    sys.exit(1)

# --- Ustawienia ---
PICK_ROLE_ID = 1413424476770664499
STATUS_ADMINS = [123456789012345678]  # <<< wpisz swoje ID
ZANCUDO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414194392214011974/image.png"
CAYO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414204332747915274/image.png"
LOGO_URL = "https://cdn.discordapp.com/icons/1206228465809100800/849c19ddef5481d01a3dfe4ccfaa8233.webp?size=1024"

# --- Discord Client ---
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Pamięć zapisów ---
captures = {}   # {msg_id: {"participants": [members]}}
airdrops = {}   # {msg_id: {"participants": [ids]}}
events = {"zancudo": {}, "cayo": {}}  # {msg_id: {"participants": [ids]}}

# =====================
#       AIRDROP
# =====================
class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel: discord.VoiceChannel, author_name: str):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.description = description
        self.voice_channel = voice_channel
        self.participants: list[int] = []
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild):
        embed = discord.Embed(title="🎁 AirDrop!", description=self.description, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL)
        embed.add_field(name="Kanał głosowy:", value=f"🔊 {self.voice_channel.mention}", inline=False)
        if self.participants:
            lines = []
            for uid in self.participants:
                member = guild.get_member(uid)
                if member:
                    lines.append(f"- {member.mention} | **{member.display_name}**")
                else:
                    lines.append(f"- <@{uid}>")
            embed.add_field(name=f"Zapisani ({len(self.participants)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
        embed.set_footer(text=f"Wystawione przez {self.author_name}")
        return embed

    @ui.button(label="✅ Dołącz", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id in self.participants:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)
            return
        self.participants.append(interaction.user.id)
        airdrops[self.message_id]["participants"].append(interaction.user.id)
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.response.send_message("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id not in self.participants:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)
            return
        self.participants.remove(interaction.user.id)
        airdrops[self.message_id]["participants"].remove(interaction.user.id)
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.response.send_message("❌ Opuściłeś(aś).", ephemeral=True)


# =====================
#       CAPTURES
# =====================
class PlayerSelectMenu(ui.Select):
    def __init__(self, capture_id):
        self.capture_id = capture_id
        options = [
            discord.SelectOption(label=member.display_name, value=str(member.id))
            for member in captures.get(self.capture_id, {}).get("participants", [])
        ]
        # jeśli brak uczestników, dodaj placeholder
        if not options:
            options = [discord.SelectOption(label="Brak uczestników", value="none")]
        super().__init__(
            placeholder="Wybierz do 25 graczy",
            max_values=min(25, len(options)),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

class PickPlayersView(ui.View):
    def __init__(self, capture_id):
        super().__init__()
        self.capture_id = capture_id
        self.player_select_menu = PlayerSelectMenu(capture_id)
        self.add_item(self.player_select_menu)

    @ui.button(label="Potwierdź wybór", style=discord.ButtonStyle.green)
    async def confirm_pick(self, interaction: discord.Interaction, button: ui.Button):
        selected_values = self.player_select_menu.values
        if len(selected_values) > 25:
            await interaction.response.send_message("Możesz wybrać maksymalnie 25 osób!", ephemeral=True)
            return
        selected_members = [
            interaction.guild.get_member(int(mid))
            for mid in selected_values if interaction.guild.get_member(int(mid))
        ]
        total_participants = len(captures.get(self.capture_id, {}).get("participants", []))
        final_embed = discord.Embed(
            title="Lista osób na captures!",
            description=f"Wybrano {len(selected_members)}/{total_participants} osób:",
            color=discord.Color(0xFFFFFF)
        )
        final_embed.add_field(
            name="Wybrani gracze:",
            value="\n".join(f"{i+1}. {m.mention} | **{m.display_name}**" for i, m in enumerate(selected_members)),
            inline=False
        )
        final_embed.set_footer(text=f"Wystawione przez {interaction.user.display_name} • {discord.utils.utcnow().strftime('%d.%m.%Y %H:%M')}")
        await interaction.response.send_message(embed=final_embed)

class CapturesView(ui.View):
    def __init__(self, capture_id):
        super().__init__(timeout=None)
        self.capture_id = capture_id

    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user not in captures.get(self.capture_id, {}).get("participants", []):
            captures.setdefault(self.capture_id, {"participants": []})["participants"].append(interaction.user)
            await interaction.response.send_message("Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user in captures.get(self.capture_id, {}).get("participants", []):
            captures[self.capture_id]["participants"].remove(interaction.user)
            await interaction.response.send_message("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple)
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        if PICK_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message("⛔ Brak uprawnień!", ephemeral=True)
            return
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if not participants:
            await interaction.response.send_message("Nikt się nie zapisał!", ephemeral=True)
            return
        await interaction.response.send_message("Wybierz do 25 graczy:", view=PickPlayersView(self.capture_id), ephemeral=True)


# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Captures z możliwością image_url
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures.")
@app_commands.describe(image_url="Link do obrazka w embedzie (opcjonalnie)")
async def create_capt(interaction: discord.Interaction, image_url: str = None):
    embed = discord.Embed(
        title="CAPTURES!",
        description="Kliknij przycisk, aby się zapisać!",
        color=discord.Color(0xFFFFFF)
    )
    if image_url:
        embed.set_image(url=image_url)  # ustawienie obrazka jeśli podany

    # najpierw wyślij wiadomość
    sent = await interaction.channel.send(content="@everyone", embed=embed)

    # utwórz osobny wpis w słowniku dla tej wiadomości
    captures[sent.id] = {"participants": []}

    # przypisz widok z poprawnym message_id
    await sent.edit(view=CapturesView(sent.id))

    await interaction.response.send_message("Ogłoszenie o captures wysłane!", ephemeral=True)

# AirDrop
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie")
async def airdrop_command(interaction: discord.Interaction, channel: discord.TextChannel, voice: discord.VoiceChannel, role: discord.Role, opis: str):
    await interaction.response.defer(ephemeral=True)
    view = AirdropView(0, opis, voice, interaction.user.display_name)
    embed = view.make_embed(interaction.guild)
    sent = await channel.send(content=f"{role.mention}", embed=embed, view=view)
    view.message_id = sent.id
    airdrops[sent.id] = {"participants": []}
    await interaction.followup.send("✅ AirDrop utworzony!", ephemeral=True)

# Eventy Zancudo / Cayo
@tree.command(name="ping-zancudo", description="Wysyła ogłoszenie o ataku na Fort Zancudo.")
async def ping_zancudo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    embed = discord.Embed(title="Atak na FORT ZANCUDO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFF0000))
    embed.set_image(url=ZANCUDO_IMAGE_URL)
    await interaction.channel.send(content=f"{role.mention}", embed=embed)
    await interaction.response.send_message("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

@tree.command(name="ping-cayo", description="Wysyła ogłoszenie o ataku na Cayo Perico.")
async def ping_cayo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    embed = discord.Embed(title="Atak na CAYO PERICO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFFAA00))
    embed.set_image(url=CAYO_IMAGE_URL)
    await interaction.channel.send(content=f"{role.mention}", embed=embed)
    await interaction.response.send_message("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

# Lista wszystkich zapisanych
@tree.command(name="list-all", description="Pokazuje listę wszystkich zapisanych")
async def list_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    desc = ""
    for mid, data in airdrops.items():
        desc += f"\n**AirDrop (msg {mid})**: {len(data['participants'])} osób"
    for etype, msgs in events.items():
        for mid, data in msgs.items():
            desc += f"\n**{etype.capitalize()} (msg {mid})**: {len(data['participants'])} osób"
    for mid, data in captures.items():
        desc += f"\n**Captures (msg {mid})**: {len(data['participants'])} osób"
    if not desc:
        desc = "Brak aktywnych zapisów."
    embed = discord.Embed(title="📋 Lista wszystkich zapisanych", description=desc, color=discord.Color.blue())
    await interaction.followup.send(embed=embed, ephemeral=True)

# Set status
@tree.command(name="set-status", description="Zmienia status bota (tylko admini)")
async def set_status(interaction: discord.Interaction, status: str, activity: str = None):
    if interaction.user.id not in STATUS_ADMINS:
        await interaction.response.send_message("⛔ Brak uprawnień!", ephemeral=True)
        return
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    if status.lower() not in status_map:
        await interaction.response.send_message("⚠️ Podaj: online/idle/dnd/invisible", ephemeral=True)
        return
    await client.change_presence(status=status_map[status.lower()],
                                 activity=discord.Game(name=activity) if activity else None)
    await interaction.response.send_message(f"✅ Status ustawiony na {status}", ephemeral=True)


# --- Start bota ---
def run_discord_bot():
    client.run(token)

threading.Thread(target=run_discord_bot).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
