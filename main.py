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
PICK_ROLE_ID = 1413424476770664499 # Zmień na faktyczne ID
STATUS_ADMINS = [1184620388425138183, 1409225386998501480, 1007732573063098378, 364869132526551050] # Zmień na faktyczne ID
ADMIN_ROLES = STATUS_ADMINS 
ZANCUDO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414194392214011974/image.png"
CAYO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414204332747915274/image.png"
LOGO_URL = "https://cdn.discordapp.com/attachments/1184622314302754857/1420796249484824757/RInmPqb.webp?ex=68d6b31e&is=68d5619e&hm=0cdf3f7cbb269b12c9f47d7eb034e40a8d830ff502ca9ceacb3d7902d3819413&"

# --- Discord Client ---
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Pamięć zapisów ---
captures = {}   
airdrops = {}   
events = {"zancudo": {}, "cayo": {}} 
squads = {}     

# <<< ZARZĄDZANIE ZAPISAMI >>>
def get_all_active_enrollments():
    all_enrollments = []
    for msg_id, data in captures.items():
        all_enrollments.append(("Captures", msg_id, data))
    for msg_id, data in airdrops.items():
        all_enrollments.append(("AirDrop", msg_id, data))
    for etype, msgs in events.items():
        for msg_id, data in msgs.items():
            all_enrollments.append((etype.capitalize(), msg_id, data))
    return all_enrollments

class EnrollmentSelectMenu(ui.Select):
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
            placeholder=f"Wybierz zapis:",
            max_values=1,
            min_values=1,
            options=options
        )
    async def callback(self, interaction: discord.Interaction):
        pass 
# <<< KONIEC ZARZĄDZANIE ZAPISAMI >>>

# =====================
#       AIRDROP & CAPTURES VIEWS
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
        # POPRAWKA KOLORU: używamy 0xFFFFFF (biały)
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
        # POPRAWKA KOLORU: używamy 0xFFFFFF (biały)
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
        
        # POPRAWKA KOLORU: używamy 0xFFFFFF (biały)
        embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
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
# <<< FUNKCJE DLA SQUADÓW (Z POPRAWKAMI) >>>
# =======================================================

def create_squad_embed(guild: discord.Guild, author_name: str, member_ids: list[int], title: str = "Main Squad"):
    """Tworzy embed dla Squadu na podstawie listy ID."""
    
    member_lines = []
    
    # Maksymalna liczba członków do wyświetlenia (Discord ma limit 1024 znaki na pole)
    # Wyświetlamy max 25, jak w UserSelect.
    for i, uid in enumerate(member_ids):
        member = guild.get_member(uid)
        if member:
            member_lines.append(f"{i+1}- {member.mention} | **{member.display_name}**")
        else:
            member_lines.append(f"{i+1}- <@{uid}> (Nieznany/Opuścił serwer)")
            
    members_list_str = "\n".join(member_lines) if member_lines else "Brak członków składu."
    count = len(member_ids)
        
    # POPRAWKA KOLORU: używamy 0xFFFFFF (biały)
    embed = discord.Embed(
        title=title, 
        description=f"Oto aktualny skład:\n\n{members_list_str}", 
        color=discord.Color(0xFFFFFF)
    )
    embed.set_thumbnail(url=LOGO_URL)
    
    embed.add_field(name="Liczba członków:", value=f"**{count}**", inline=False)
    
    embed.set_footer(text=f"Aktywowane przez {author_name}")
    return embed


class EditSquadView(ui.View):
    """Widok zawierający menu wyboru użytkowników i przycisk Potwierdź edycję. Zastępuje stary modal."""
    def __init__(self, message_id: int):
        super().__init__(timeout=180)
        self.message_id = message_id
        
        # UserSelect (wybieracz użytkowników)
        self.add_item(ui.UserSelect(
            placeholder="Wybierz członków składu (max 25)",
            max_values=25, 
            custom_id="squad_member_picker"
        ))

    @ui.button(label="✅ Potwierdź edycję", style=discord.ButtonStyle.green)
    async def confirm_edit(self, interaction: discord.Interaction, button: ui.Button):
        # KLUCZOWA POPRAWKA: Odroczenie interakcji!
        await interaction.response.defer(ephemeral=True)

        # Pobieramy wybrany UserSelect
        select_menu = next((item for item in self.children if item.custom_id == "squad_member_picker"), None)
        
        # Jeśli UserSelect istnieje i ma wartości, to są to ID użytkowników (str)
        # UWAGA: UserSelect zwraca ID w `select_menu.values` (str) i obiekty w `interaction.data.resolved['users']`
        selected_ids = []
        if select_menu and select_menu.values:
            selected_ids = [int(uid) for uid in select_menu.values]
        
        squad_data = squads.get(self.message_id)

        if not squad_data:
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return

        # Aktualizujemy listę ID członków w pamięci
        squad_data["member_ids"] = selected_ids
        
        # Odtwarzamy embed
        message = squad_data.get("message")
        author_name = squad_data.get("author_name", "Bot")
        title = "Main Squad"
        if message and message.embeds:
            title = message.embeds[0].title
            
        new_embed = create_squad_embed(interaction.guild, author_name, selected_ids, title)
        
        # Odświeżamy wiadomość
        if message and hasattr(message, 'edit'):
            new_squad_view = SquadView(self.message_id, squad_data.get("role_id"))
            
            role_id = squad_data.get("role_id")
            content = f"<@&{role_id}> **Zaktualizowano Skład!**" if role_id else ""
            
            await message.edit(content=content, embed=new_embed, view=new_squad_view)
            
            # Odpowiedź po pomyślnej edycji
            await interaction.followup.send(content="✅ Skład został pomyślnie zaktualizowany! Wróć do głównej wiadomości składu.", ephemeral=True)
        else:
            await interaction.followup.send(content="Błąd: Nie można odświeżyć wiadomości składu.", ephemeral=True)


class SquadView(ui.View):
    """Główny widok składu z przyciskiem do przejścia do edycji."""
    def __init__(self, message_id: int, role_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id

    @ui.button(label="Zarządzaj składem (ADMIN)", style=discord.ButtonStyle.blurple)
    async def manage_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        # KLUCZOWA POPRAWKA: Odroczenie interakcji! Zapobiega błędom 404/10062.
        # Jest to konieczne, ponieważ wysłanie nowego View/Wiadomości zajmuje czas.
        await interaction.response.defer(ephemeral=True) 

        if interaction.user.id not in ADMIN_ROLES:
            await interaction.followup.send("⛔ Brak uprawnień do zarządzania składem!", ephemeral=True)
            return

        squad_data = squads.get(self.message_id)
        if not squad_data:
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return
            
        edit_view = EditSquadView(self.message_id)
        
        # Zamiast Modala wysyłamy teraz EditSquadView z UserSelect
        await interaction.followup.send(
            "Wybierz listę członków składu (użyj menu rozwijanego, max 25 osób). Po wybraniu naciśnij 'Potwierdź edycję':", 
            view=edit_view, 
            ephemeral=True
        )

# =======================================================
# <<< KONIEC FUNKCJI DLA SQUADÓW >>>
# =======================================================


# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    # Przywracanie widoków
    if squads:
        print(f"Próba przywrócenia {len(squads)} widoków Squad.")
        for msg_id, data in squads.items():
             try:
                 client.add_view(SquadView(msg_id, data["role_id"]))
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku Squad {msg_id}: {e}")
                 
    # Synchronizacja komend
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Komenda SQUAD
@tree.command(name="create-squad", description="Tworzy ogłoszenie o składzie z możliwością edycji.")
async def create_squad(interaction: discord.Interaction, rola: discord.Role, tytul: str = "Main Squad"):
    # KLUCZOWA POPRAWKA: Odroczenie interakcji! Zapobiega błędom 404/10062.
    await interaction.response.defer(ephemeral=True) 

    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
        return

    author_name = interaction.user.display_name
    role_id = rola.id
    
    initial_member_ids = []
    # POPRAWKA KOLORU: używa poprawionej funkcji
    embed = create_squad_embed(interaction.guild, author_name, initial_member_ids, tytul) 
    view = SquadView(0, role_id)
    
    content = f"{rola.mention}"
    sent = await interaction.channel.send(content=content, embed=embed, view=view)
    
    # Zapisanie danych składu
    squads[sent.id] = {
        "role_id": role_id, 
        "member_ids": initial_member_ids, 
        "message": sent, 
        "channel_id": sent.channel.id,
        "author_name": author_name,
    }
    
    # Aktualizacja View z poprawnym ID wiadomości
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
        count = len(data.get('member_ids', []))
        desc += f"\n**Squad (msg {mid})**: {count} osób"

    if not desc:
        desc = "Brak aktywnych zapisów i składów."
    embed = discord.Embed(title="📋 Lista wszystkich zapisanych i składów", description=desc, color=discord.Color.blue())
    await interaction.followup.send(embed=embed, ephemeral=True)

# Set status
@tree.command(name="set-status", description="Zmienia status i aktywność bota (tylko admini)")
async def set_status(interaction: discord.Interaction, status: str, opis_aktywnosci: str = None, typ_aktywnosci: str = None, url_stream: str = None):
    if interaction.user.id not in STATUS_ADMINS:
        await interaction.response.send_message("⛔ Brak uprawnień!", ephemeral=True)
        return

    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    
    activity_type_map = {
        "gra": discord.ActivityType.playing,    
        "slucha": discord.ActivityType.listening, 
        "patrzy": discord.ActivityType.watching,   
        "stream": discord.ActivityType.streaming,  
    }

    if status.lower() not in status_map:
        await interaction.response.send_message("⚠️ Nieprawidłowy status. Użyj: online/idle/dnd/invisible.", ephemeral=True)
        return
        
    activity = None
    if opis_aktywnosci:
        activity_type = discord.ActivityType.playing 
        
        if typ_aktywnosci and typ_aktywnosci.lower() in activity_type_map:
            activity_type = activity_type_map[typ_aktywnosci.lower()]

        if activity_type == discord.ActivityType.streaming:
            if not url_stream or not (url_stream.startswith('http://') or url_stream.startswith('https://')):
                await interaction.response.send_message("⚠️ Aby ustawić 'stream', musisz podać poprawny link (URL) do streamu w argumencie `url_stream`!", ephemeral=True)
                return
            
            activity = discord.Activity(
                name=opis_aktywnosci,
                type=discord.ActivityType.streaming,
                url=url_stream
            )
        else:
            activity = discord.Activity(
                name=opis_aktywnosci,
                type=activity_type
            )

    await client.change_presence(status=status_map[status.lower()], activity=activity)
    
    response_msg = f"✅ Status ustawiony na **{status.upper()}**"
    if opis_aktywnosci:
        if activity_type == discord.ActivityType.playing:
            activity_text = f"Gra w **{opis_aktywnosci}**"
        elif activity_type == discord.ActivityType.listening:
            activity_text = f"Słucha **{opis_aktywnosci}**"
        elif activity_type == discord.ActivityType.watching:
            activity_text = f"Ogląda **{opis_aktywnosci}**"
        elif activity_type == discord.ActivityType.streaming:
            activity_text = f"Streamuje **{opis_aktywnosci}** (URL: {url_stream})"
        else:
             activity_text = f"Aktywność: **{opis_aktywnosci}**"
             
        response_msg += f" z aktywnością: **{activity_text}**"

    await interaction.response.send_message(response_msg, ephemeral=True)

# Wypisz z capt
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

# Wpisz na capt
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
