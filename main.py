import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime
import re 

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
STATUS_ADMINS = [1184620388425138183, 1409225386998501480, 1007732573063098378, 364869132526551050]   # <<< wpisz swoje ID
ADMIN_ROLES = STATUS_ADMINS # Używane do komend /wpisz-na-capt, /wypisz-z-capt, /create-squad
ZANCUDO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414194392214011974/image.png"
CAYO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414204332747915274/image.png"
LOGO_URL = "https://cdn.discordapp.com/attachments/1184622314302754857/1420796249484824757/RInmPqb.webp?ex=68d6b31e&is=68d5619e&hm=0cdf3f7cbb269b12c9f47d7eb034e40a8d830ff502ca9ceacb3d7902d3819413&"

# --- Discord Client ---
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Pamięć zapisów ---
# {msg_id: {"participants": [member_ids], "message": discord.Message, "channel_id": int, "author_name": str}}
captures = {}   
airdrops = {}   
events = {"zancudo": {}, "cayo": {}} 
# NOWA PAMIĘĆ: {msg_id: {"role_id": int, "members_list": str, "message": discord.Message, "channel_id": int, "author_name": str}}
squads = {}     

# <<< ZARZĄDZANIE ZAPISAMI >>>
def get_all_active_enrollments():
    """Zwraca listę wszystkich aktywnych zapisów w formacie: [(nazwa, id_wiadomości, słownik_danych)]."""
    all_enrollments = []
    
    # Captures
    for msg_id, data in captures.items():
        all_enrollments.append(("Captures", msg_id, data))

    # AirDrops
    for msg_id, data in airdrops.items():
        all_enrollments.append(("AirDrop", msg_id, data))
        
    # Events
    for etype, msgs in events.items():
        for msg_id, data in msgs.items():
            all_enrollments.append((etype.capitalize(), msg_id, data))
            
    return all_enrollments

class EnrollmentSelectMenu(ui.Select):
    """Rozwijane menu do wyboru konkretnego aktywnego zapisu."""
    def __init__(self, action: str):
        self.action = action 
        enrollments = get_all_active_enrollments()
        options = []
        
        for name, msg_id, data in enrollments:
            count = len(data.get("participants", []))
            options.append(
                discord.SelectOption(
                    label=f"{name} (ID: {msg_id}) - {count} os.", 
                    value=f"{name.lower()}-{msg_id}"
                )
            )

        super().__init__(
            placeholder=f"Wybierz zapis, z którego usunąć/do którego dodać osobę:",
            max_values=1,
            min_values=1,
            options=options
        )
        
    async def callback(self, interaction: discord.Interaction):
        pass 
# <<< KONIEC ZARZĄDZANIE ZAPISAMI >>>

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
                    lines.append(f"- <@{uid}> (Użytkownik opuścił serwer)")
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
        # Edycja wiadomości
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.response.send_message("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id not in self.participants:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)
            return
        self.participants.remove(interaction.user.id)
        airdrops[self.message_id]["participants"].remove(interaction.user.id)
        # Edycja wiadomości
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.response.send_message("❌ Opuściłeś(aś).", ephemeral=True)

# =====================
#       CAPTURES
# =====================
class PlayerSelectMenu(ui.Select):
    def __init__(self, capture_id: int, guild: discord.Guild):
        self.capture_id = capture_id
        participant_ids = captures.get(self.capture_id, {}).get("participants", [])
        options = []
        for member_id in participant_ids:
            member = guild.get_member(member_id)
            if member:
                options.append(
                    discord.SelectOption(label=member.display_name, value=str(member.id))
                )

        super().__init__(
            placeholder="Wybierz do 25 graczy",
            max_values=min(25, len(options)),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

class PickPlayersView(ui.View):
    def __init__(self, capture_id: int):
        super().__init__()
        self.capture_id = capture_id
        pass 

    @ui.button(label="Potwierdź wybór", style=discord.ButtonStyle.green)
    async def confirm_pick(self, interaction: discord.Interaction, button: ui.Button):
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        
        if not select_menu:
             await interaction.response.send_message("Błąd: Nie znaleziono menu wyboru. Spróbuj ponownie.", ephemeral=True)
             return
             
        selected_values = select_menu.values
        
        if not selected_values:
            await interaction.response.send_message("Nie wybrano żadnych osób!", ephemeral=True)
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
    def __init__(self, capture_id: int, author_name: str): 
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild):
        participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        
        embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
        # LOGIKA WYŚWIETLANIA LISTY OSÓB
        if participants_ids:
            lines = []
            for uid in participants_ids:
                member = guild.get_member(uid)
                if member:
                    lines.append(f"- {member.mention} | **{member.display_name}**")
                else:
                    lines.append(f"- <@{uid}> (Użytkownik opuścił serwer)")
            embed.add_field(name=f"Zapisani ({len(participants_ids)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
            
        # Stopka z autorem aktywacji
        embed.set_footer(text=f"Wystawione przez {self.author_name}")
        return embed

    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id not in captures.get(self.capture_id, {}).get("participants", []):
            captures.setdefault(self.capture_id, {"participants": []})["participants"].append(user_id)
            
            data = captures.get(self.capture_id)
            if data and data.get("message"):
                await data["message"].edit(embed=self.make_embed(interaction.guild), view=self)
            
            await interaction.response.send_message("Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id in captures.get(self.capture_id, {}).get("participants", []):
            captures[self.capture_id]["participants"].remove(user_id)
            
            data = captures.get(self.capture_id)
            if data and data.get("message"):
                await data["message"].edit(embed=self.make_embed(interaction.guild), view=self)
            
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
            
        pick_view = PickPlayersView(self.capture_id)
        pick_view.add_item(PlayerSelectMenu(self.capture_id, interaction.guild))
        
        await interaction.response.send_message("Wybierz do 25 graczy:", view=pick_view, ephemeral=True)


# =======================================================
# <<< NOWE FUNKCJE DLA SQUADÓW >>>
# =======================================================

def create_squad_embed(guild: discord.Guild, author_name: str, members_list: str = "Brak członków składu.", title: str = "Main Squad"):
    """Tworzy embed dla Squadu."""
    member_lines = [line for line in members_list.split('\n') if line.strip()]
    
    # Liczenie pingów, aby określić liczbę członków (to jest najbardziej precyzyjne)
    ping_count = len(re.findall(r'<@!?\d+>', members_list)) 
    
    # Jeśli nie ma pingów, liczymy po prostu niepuste linie (dla początkowego tekstu)
    if ping_count == 0:
        count = len(member_lines)
    else:
        count = ping_count # Jeśli są pingi, używamy ich liczby
        
    embed = discord.Embed(
        title=title, 
        description=f"Oto aktualny skład:\n\n{members_list}", 
        color=discord.Color(0xFFFFFF) 
    )
    embed.set_thumbnail(url=LOGO_URL)
    
    embed.add_field(name="Liczba członków:", value=f"**{count}**", inline=False)
    
    embed.set_footer(text=f"Aktywowane przez {author_name}")
    return embed

class SquadModal(ui.Modal, title='Edytuj Skład'):
    def __init__(self, message_id: int, current_content: str):
        super().__init__()
        self.message_id = message_id
        
        # Optymalizacja danych w Modalu
        editable_content = self._prepare_editable_content(current_content)
        
        self.list_input = ui.TextInput(
            label='Lista (Wpisz nr-ID/nazwa/nick, np. 1- 1234567890)',
            style=discord.TextStyle.paragraph,
            default=editable_content,
            required=True,
            max_length=4000
        )
        self.add_item(self.list_input)
        
    def _prepare_editable_content(self, content: str) -> str:
        """Usuwa pingi i formatowanie z tekstu, zostawiając tylko numerację i nazwy/tekst."""
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            # 1. Usuń pingi (<@!123456789>)
            line = re.sub(r'<@!?\d+>', '', line)
            # 2. Usuń formatowanie (**display_name**)
            line = re.sub(r'\s*\|\s*\*\*[^\*]+\*\*', '', line).strip()
            
            if line:
                 new_lines.append(line)
        return "\n".join(new_lines) if new_lines else "1- [Wpisz ID lub nazwę]\n2- [Wpisz ID lub nazwę]"

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        input_lines = self.list_input.value.split('\n')
        final_lines = []
        guild = interaction.guild

        for line in input_lines:
            line = line.strip()
            if not line:
                continue

            # Sprawdź, czy linia już zawiera aktywny ping (np. jeśli ktoś go wkleił)
            if re.search(r'<@!?\d+>', line):
                final_lines.append(line)
                continue

            # Wyszukaj prefiks (np. 1-, 2-, albo cokolwiek przed nazwą)
            prefix_match = re.match(r'(.+[-:.]\s*)', line)
            
            if prefix_match:
                name_or_id_to_search = line[prefix_match.end():].strip()
                prefix = prefix_match.group(0)
            else:
                name_or_id_to_search = line
                prefix = ""

            member = None
            if name_or_id_to_search:
                
                # <<< NOWA LOGIKA: Sprawdź, czy to jest ID >>>
                if name_or_id_to_search.isdigit():
                    try:
                        member_id = int(name_or_id_to_search)
                        member = guild.get_member(member_id)
                    except ValueError:
                        pass # To nie był poprawny numer
                        
                # <<< STARA LOGIKA: Jeśli nie ID, spróbuj znaleźć po nazwie/tagu >>>
                if member is None:
                    member = guild.get_member_named(name_or_id_to_search)

            if member:
                # Jeśli znaleziono, zamień na ping
                ping = member.mention
                final_lines.append(f"{prefix}{ping} | **{member.display_name}**")
            else:
                # Jeśli nie znaleziono, dodaj jako zwykły tekst
                final_lines.append(line)
        
        new_members_list = "\n".join(final_lines)

        squad_data = squads.get(self.message_id)

        if not squad_data:
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return

        # Aktualizujemy listę członków w pamięci
        squad_data["members_list"] = new_members_list
        
        # Odtwarzamy embed
        message = squad_data.get("message")
        author_name = squad_data.get("author_name", "Bot")
        
        # Używamy tytułu z wiadomości lub fallback
        title = "Main Squad"
        if message and message.embeds:
            title = message.embeds[0].title
            
        new_embed = create_squad_embed(interaction.guild, author_name, new_members_list, title)
        
        # Odświeżamy wiadomość
        if message and hasattr(message, 'edit'):
            # Odtwarzamy widok, by był spójny
            new_view = SquadView(self.message_id, squad_data.get("role_id"))
            
            # Wysłanie pingu na początku zawartości
            role_id = squad_data.get("role_id")
            content = f"<@&{role_id}> **Zaktualizowano Skład!**" if role_id else ""
            
            await message.edit(content=content, embed=new_embed, view=new_view)
            await interaction.followup.send("✅ Skład został pomyślnie zaktualizowany! Wprowadzone ID i nazwy zostały przekształcone na pingi.", ephemeral=True)
        else:
            await interaction.followup.send("Błąd: Nie można odświeżyć wiadomości składu.", ephemeral=True)

class SquadView(ui.View):
    def __init__(self, message_id: int, role_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id

    @ui.button(label="Zarządzaj składem (ADMIN)", style=discord.ButtonStyle.blurple)
    async def manage_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id not in ADMIN_ROLES:
            await interaction.response.send_message("⛔ Brak uprawnień do zarządzania składem!", ephemeral=True)
            return

        squad_data = squads.get(self.message_id)
        if not squad_data:
            await interaction.response.send_message("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return
            
        # Pobieramy aktualną listę do wyświetlenia w Modalu
        current_content = squad_data.get("members_list", "1- [Wpisz ID lub nazwę]")
        
        # Uruchamiamy Modal
        await interaction.response.send_modal(SquadModal(self.message_id, current_content))

# =======================================================
# <<< KONIEC FUNKCJI DLA SQUADÓW >>>
# =======================================================


# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Nowa komenda SQUAD
@tree.command(name="create-squad", description="Tworzy ogłoszenie o składzie z możliwością edycji.")
async def create_squad(interaction: discord.Interaction, rola: discord.Role, tytul: str = "Main Squad"):
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.response.send_message("⛔ Brak uprawnień!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    author_name = interaction.user.display_name
    role_id = rola.id
    
    # 1. Tworzymy początkowy embed i view
    initial_members = "1- [Wpisz ID lub nazwę]\n2- [Wpisz ID lub nazwę]\n3- [Wpisz ID lub nazwę]"
    embed = create_squad_embed(interaction.guild, author_name, initial_members, tytul)
    view = SquadView(0, role_id)
    
    # 2. Wysyłamy wiadomość z pingiem
    content = f"{rola.mention}"
    sent = await interaction.channel.send(content=content, embed=embed, view=view)
    
    # 3. Zapisujemy do pamięci
    squads[sent.id] = {
        "role_id": role_id, 
        "members_list": initial_members, 
        "message": sent, 
        "channel_id": sent.channel.id,
        "author_name": author_name,
    }
    
    # 4. Aktualizujemy ID wiadomości w widoku
    view.message_id = sent.id
    await sent.edit(view=view) 
    
    await interaction.followup.send(f"✅ Ogłoszenie o składzie '{tytul}' dla roli {rola.mention} wysłane!", ephemeral=True)


# Captures
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures.")
async def create_capt(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True) 
    
    author_name = interaction.user.display_name
    view = CapturesView(0, author_name) 
    embed = view.make_embed(interaction.guild)
    
    sent = await interaction.channel.send(content="@everyone", embed=embed, view=view)
    
    captures[sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id, "author_name": author_name}
    
    view.capture_id = sent.id 
    await sent.edit(view=view) 
    
    await interaction.followup.send("Ogłoszenie o captures wysłane!", ephemeral=True)

# AirDrop
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie")
async def airdrop_command(interaction: discord.Interaction, channel: discord.TextChannel, voice: discord.VoiceChannel, role: discord.Role, opis: str):
    await interaction.response.defer(ephemeral=True)
    view = AirdropView(0, opis, voice, interaction.user.display_name)
    embed = view.make_embed(interaction.guild)
    sent = await channel.send(content=f"{role.mention}", embed=embed, view=view)
    view.message_id = sent.id
    airdrops[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "description": opis, 
        "voice_channel_id": voice.id, 
        "author_name": interaction.user.display_name
    }
    await interaction.followup.send("✅ AirDrop utworzony!", ephemeral=True)

# Eventy Zancudo / Cayo
@tree.command(name="ping-zancudo", description="Wysyła ogłoszenie o ataku na Fort Zancudo.")
async def ping_zancudo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="Atak na FORT ZANCUDO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFF0000))
    embed.set_image(url=ZANCUDO_IMAGE_URL)
    embed.set_thumbnail(url=LOGO_URL) 
    sent = await interaction.channel.send(content=f"{role.mention}", embed=embed)
    events["zancudo"][sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

@tree.command(name="ping-cayo", description="Wysyła ogłoszenie o ataku na Cayo Perico.")
async def ping_cayo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="Atak na CAYO PERICO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFFAA00))
    embed.set_image(url=CAYO_IMAGE_URL)
    embed.set_thumbnail(url=LOGO_URL) 
    sent = await interaction.channel.send(content=f"{role.mention}", embed=embed)
    events["cayo"][sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

# Lista wszystkich zapisanych
@tree.command(name="list-all", description="Pokazuje listę wszystkich zapisanych")
async def list_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    desc = ""
    for name, mid, data in get_all_active_enrollments():
        desc += f"\n**{name} (msg {mid})**: {len(data['participants'])} osób"
        
    for mid, data in squads.items():
        count = len([line for line in data['members_list'].split('\n') if line.strip()])
        desc += f"\n**Squad (msg {mid})**: {count} osób (zarządzane ręcznie)"

    if not desc:
        desc = "Brak aktywnych zapisów i składów."
    embed = discord.Embed(title="📋 Lista wszystkich zapisanych i składów", description=desc, color=discord.Color.blue())
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

# ===============================================
# <<< KOMENDA - WYPISZ-Z-CAPT >>>
# ===============================================
class RemoveEnrollmentView(ui.View):
    def __init__(self, member_to_remove: discord.Member):
        super().__init__(timeout=180)
        self.member_to_remove = member_to_remove
        self.add_item(EnrollmentSelectMenu("remove"))

    @ui.button(label="Potwierdź usunięcie", style=discord.ButtonStyle.red)
    async def confirm_remove(self, interaction: discord.Interaction, button: ui.Button):
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not select_menu or not select_menu.values:
            await interaction.response.send_message("⚠️ Najpierw wybierz zapis z listy!", ephemeral=True)
            return

        type_str, msg_id_str = select_menu.values[0].split('-')
        msg_id = int(msg_id_str)
        user_id = self.member_to_remove.id
        
        data_dict = None
        if type_str == "captures":
            data_dict = captures.get(msg_id)
        elif type_str == "airdrop":
            data_dict = airdrops.get(msg_id)
        elif type_str in events:
            data_dict = events[type_str].get(msg_id)

        if not data_dict:
            await interaction.response.edit_message(content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.", view=None)
            return

        participants = data_dict.get("participants", [])
        
        if user_id not in participants:
            await interaction.response.edit_message(content=f"⚠️ **{self.member_to_remove.display_name}** nie jest zapisany(a) na ten **{type_str.capitalize()}**.", view=None)
            return

        participants.remove(user_id)
        
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
            if type_str == "airdrop":
                voice_channel = message.guild.get_channel(data_dict["voice_channel_id"])
                description = data_dict["description"]
                author_name = data_dict["author_name"]
                
                view_obj = AirdropView(msg_id, description, voice_channel, author_name)
                view_obj.participants = participants
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
            elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
                 
                 author_name = data_dict["author_name"]
                      
                 view_obj = CapturesView(msg_id, author_name)
                 new_embed = view_obj.make_embed(message.guild)
                 await message.edit(embed=new_embed, view=view_obj)
            elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants
                 # W eventach (zancudo/cayo) nie ma interaktywnych przycisków
                 # Wystarczy odświeżyć wewnętrzną listę participants

        await interaction.response.edit_message(
            content=f"✅ Pomyślnie wypisano **{self.member_to_remove.display_name}** z **{type_str.capitalize()}** (ID: `{msg_id}`).", 
            view=None
        )

@tree.command(name="wypisz-z-capt", description="Wypisuje użytkownika z dowolnego aktywnego zapisu (Captures, AirDrop, Event).")
async def remove_from_enrollment(interaction: discord.Interaction, członek: discord.Member):
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.response.send_message("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
        
    enrollments = get_all_active_enrollments()
    if not enrollments:
        await interaction.response.send_message("⚠️ Brak aktywnych zapisów, z których można wypisać użytkownika.", ephemeral=True)
        return
        
    await interaction.response.send_message(
        f"Wybierz zapis, z którego usunąć **{członek.display_name}**:", 
        view=RemoveEnrollmentView(członek), 
        ephemeral=True
    )

# ===============================================
# <<< KOMENDA - WPISZ-NA-CAPT >>>
# ===============================================
class AddEnrollmentView(ui.View):
    def __init__(self, member_to_add: discord.Member):
        super().__init__(timeout=180)
        self.member_to_add = member_to_add
        self.add_item(EnrollmentSelectMenu("add"))

    @ui.button(label="Potwierdź dodanie", style=discord.ButtonStyle.green)
    async def confirm_add(self, interaction: discord.Interaction, button: ui.Button):
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not select_menu or not select_menu.values:
            await interaction.response.send_message("⚠️ Najpierw wybierz zapis z listy!", ephemeral=True)
            return

        type_str, msg_id_str = select_menu.values[0].split('-')
        msg_id = int(msg_id_str)
        user_id = self.member_to_add.id
        
        data_dict = None
        if type_str == "captures":
            data_dict = captures.get(msg_id)
        elif type_str == "airdrop":
            data_dict = airdrops.get(msg_id)
        elif type_str in events:
            data_dict = events[type_str].get(msg_id)

        if not data_dict:
            await interaction.response.edit_message(content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.", view=None)
            return

        participants = data_dict.get("participants", [])
        
        if user_id in participants:
            await interaction.response.edit_message(content=f"⚠️ **{self.member_to_add.display_name}** jest już zapisany(a) na ten **{type_str.capitalize()}**.", view=None)
            return

        participants.append(user_id)
        
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
             if type_str == "airdrop":
                voice_channel = message.guild.get_channel(data_dict["voice_channel_id"])
                description = data_dict["description"]
                author_name = data_dict["author_name"]

                view_obj = AirdropView(msg_id, description, voice_channel, author_name)
                view_obj.participants = participants
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
             elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
                 
                 author_name = data_dict["author_name"]
                      
                 view_obj = CapturesView(msg_id, author_name)
                 new_embed = view_obj.make_embed(message.guild)
                 await message.edit(embed=new_embed, view=view_obj)
             elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants
                 # W eventach (zancudo/cayo) nie ma interaktywnych przycisków
                 # Wystarczy odświeżyć wewnętrzną listę participants

        await interaction.response.edit_message(
            content=f"✅ Pomyślnie wpisano **{self.member_to_add.display_name}** na **{type_str.capitalize()}** (ID: `{msg_id}`).", 
            view=None
        )

@tree.command(name="wpisz-na-capt", description="Wpisuje użytkownika na dowolny aktywny zapis (Captures, AirDrop, Event).")
async def add_to_enrollment(interaction: discord.Interaction, członek: discord.Member):
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.response.send_message("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
        
    enrollments = get_all_active_enrollments()
    if not enrollments:
        await interaction.response.send_message("⚠️ Brak aktywnych zapisów, na które można wpisać użytkownika.", ephemeral=True)
        return
        
    await interaction.response.send_message(
        f"Wybierz zapis, na który wpisać **{członek.display_name}**:", 
        view=AddEnrollmentView(członek), 
        ephemeral=True
    )


# --- Start bota ---
def run_discord_bot():
    client.run(token)

threading.Thread(target=run_discord_bot).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
