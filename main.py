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
STATUS_ADMINS = [1184620388425138183, 1007732573063098378]  # <<< wpisz swoje ID
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
    def __init__(self, capture_id, guild: discord.Guild):
        self.capture_id = capture_id
        options = [
            discord.SelectOption(
                label=guild.get_member(uid).display_name if guild.get_member(uid) else f"ID {uid}",
                value=str(uid)
            )
            for uid in captures.get(self.capture_id, {}).get("participants", [])
        ]
        super().__init__(placeholder="Wybierz do 25 graczy", max_values=min(25, len(options)), options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

class PickPlayersView(ui.View):
    def __init__(self, capture_id, guild: discord.Guild):
        super().__init__()
        self.capture_id = capture_id
        self.player_select_menu = PlayerSelectMenu(capture_id, guild)
        self.add_item(self.player_select_menu)

    @ui.button(label="Potwierdź wybór", style=discord.ButtonStyle.green)
    async def confirm_pick(self, interaction: discord.Interaction, button: ui.Button):
        selected_values = self.player_select_menu.values
        selected_members = [interaction.guild.get_member(int(uid)) for uid in selected_values if interaction.guild.get_member(int(uid))]
        total_participants = len(captures.get(self.capture_id, {}).get("participants", []))
        final_embed = discord.Embed(
            title="Lista osób na captures!",
            description=f"Wybrane osoby spośród {total_participants} uczestników:",
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

    @ui.button(label="✅ Zapisz się", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        participants = captures.setdefault(self.capture_id, {"participants": []})["participants"]
        if interaction.user.id not in participants:
            participants.append(interaction.user.id)
            await interaction.response.send_message("✅ Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Jesteś już zapisany(a)!", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if interaction.user.id in participants:
            participants.remove(interaction.user.id)
            await interaction.response.send_message("✅ Wypisałeś(aś) się z captures!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Nie jesteś zapisany(a)!", ephemeral=True)

    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple)
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        if PICK_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message("⛔ Brak uprawnień!", ephemeral=True)
            return
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if not participants:
            await interaction.response.send_message("❌ Nikt się nie zapisał!", ephemeral=True)
            return
        await interaction.response.send_message("Wybierz do 25 graczy:", view=PickPlayersView(self.capture_id, interaction.guild), ephemeral=True)

# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Captures
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures.")
@app_commands.describe(image_url="Link do obrazka dla embedu (opcjonalnie)")
async def create_capt(interaction: discord.Interaction, image_url: str = None):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
    if image_url:
        embed.set_image(url=image_url)
    sent = await interaction.channel.send(content="@everyone", embed=embed, view=CapturesView(0))
    captures[sent.id] = {"participants": []}
    await sent.edit(view=CapturesView(sent.id))
    await interaction.followup.send("✅ Ogłoszenie o captures wysłane!", ephemeral=True)

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

# =====================
#       ROZBUDOWANY STATUS
# =====================
@tree.command(name="set-status", description="Zmienia status bota i aktywność (tylko admini)")
@app_commands.describe(
    status="online/idle/dnd/invisible",
    activity_type="Typ aktywności: gra/stream/słuchanie/oglądanie (opcjonalnie)",
    activity_name="Nazwa aktywności (opcjonalnie)",
    stream_url="Link do streama, jeśli typ to stream (opcjonalnie)"
)
async def set_status(interaction: discord.Interaction, status: str, activity_type: str = None, activity_name: str = None, stream_url: str = None):
    if interaction.user.id not in STATUS_ADMINS:
        await interaction.response.send_message("⛔ Brak uprawnień!", ephemeral=True)
        return

    status_map = {"online": discord.Status.online, "idle": discord.Status.idle, "dnd": discord.Status.dnd, "invisible": discord.Status.invisible}
    if status.lower() not in status_map:
        await interaction.response.send_message("⚠️ Podaj prawidłowy status: online/idle/dnd/invisible", ephemeral=True)
        return

    activity = None
    if activity_type and activity_name:
        activity_type = activity_type.lower()
        if activity_type == "gra":
            activity = discord.Game(name=activity_name)
        elif activity_type == "stream":
            url = stream_url if stream_url else "https://twitch.tv/streamer"
            activity = discord.Streaming(name=activity_name, url=url)
        elif activity_type == "słuchanie":
            activity = discord.Activity(type=discord.ActivityType.listening, name=activity_name)
        elif activity_type == "oglądanie":
            activity = discord.Activity(type=discord.ActivityType.watching, name=activity_name)
        else:
            await interaction.response.send_message("⚠️ Nieprawidłowy typ aktywności: gra/stream/słuchanie/oglądanie", ephemeral=True)
            return

    await client.change_presence(status=status_map[status.lower()], activity=activity)

    embed = discord.Embed(title="✨ Status bota zaktualizowany", color=discord.Color.green())
    embed.add_field(name="Status", value=status.capitalize(), inline=True)
    if activity:
        embed.add_field(name="Aktywność", value=f"{activity_type.capitalize()} - {activity_name}", inline=True)
    embed.set_footer(text=f"Ustawione przez {interaction.user.display_name} • {discord.utils.utcnow().strftime('%d.%m.%Y %H:%M')}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Start bota ---
def run_discord_bot():
    client.run(token)

threading.Thread(target=run_discord_bot).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
