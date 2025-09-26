import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime
import re 
import asyncio # Dodajemy dla asynchronicznego timera
from typing import Literal

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
# WAŻNE: Wprowadź swoje faktyczne ID ról/użytkowników.
PICK_ROLE_ID = 1413424476770664499 # ID Roli, która może 'pickować' graczy
STATUS_ADMINS = [1184620388425138183, 1409225386998501480, 1007732573063098378, 364869132526551050] # ID Użytkowników-Adminów
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
# WAŻNE: W przypadku restartu bota te dane zostaną wyczyszczone!
captures = {}   
airdrops = {}   
events = {"zancudo": {}, "cayo": {}} 
squads = {}     

# =====================
# <<< FUNKCJE POMOCNICZE >>>
# =====================

# Funkcja dla Timera: wysyła ping po upływie czasu
async def send_timer_ping(channel_id, role_id, timer_minutes, initial_message_id, interaction_followup_message):
    """
    Oczekuje na timer_minutes, a następnie wysyła finalny ping.
    """
    await asyncio.sleep(timer_minutes * 60)
    
    channel = client.get_channel(channel_id)
    if channel:
        try:
            # Usuń tymczasową wiadomość "Wysłano ogłoszenie..."
            if interaction_followup_message:
                await interaction_followup_message.delete()
        except:
            pass # Ignoruj, jeśli wiadomość została już usunięta
            
        try:
            # Pobierz główną wiadomość ogłoszenia
            main_message = await channel.fetch_message(initial_message_id)
            if main_message:
                
                role_mention = f"<@&{role_id}>" if role_id else "@everyone"
                
                ping_embed = discord.Embed(
                    title="⏰ START ZA CHWILĘ!",
                    description=f"**{role_mention}** - Pora się zbierać! Czas na start upłynął. Zbierać się pod głównym ogłoszeniem!",
                    color=discord.Color.gold()
                )
                ping_embed.set_footer(text=f"Timer upłynął po {timer_minutes} minutach.")
                
                await channel.send(
                    content=role_mention, 
                    embed=ping_embed, 
                    reference=main_message, 
                    delete_after=300 # Usuń ping po 5 minutach
                )
        except discord.NotFound:
            print(f"Błąd: Nie znaleziono wiadomości {initial_message_id} do pingowania.")
        except Exception as e:
            print(f"Błąd podczas pingowania po timerze: {e}")


# Funkcja do pobierania aktywnych zapisów
def get_all_active_enrollments():
    """Zwraca listę wszystkich aktywnych zapisów dla menu wyboru."""
    all_enrollments = []
    # Captures
    for msg_id, data in captures.items():
        all_enrollments.append(("Captures", msg_id, data))
    # AirDrop
    for msg_id, data in airdrops.items():
        all_enrollments.append(("AirDrop", msg_id, data))
    # Events (Zancudo/Cayo)
    for etype, msgs in events.items():
        for msg_id, data in msgs.items():
            all_enrollments.append((etype.capitalize(), msg_id, data))
    return all_enrollments

# =====================
# <<< WIDOKI DLA ZAPISÓW (VIEWS) >>>
# =====================

# Klasa dla Menu Wyboru Zapisów (używana w wpisz/wypisz)
class EnrollmentSelectMenu(ui.Select):
    def __init__(self, action: str, member_id: int):
        self.action = action 
        self.member_id = member_id
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
        await interaction.response.defer(ephemeral=True)
        
        selected_value = self.values[0]
        type_str, msg_id_str = selected_value.split('-')
        msg_id = int(msg_id_str)
        
        participant_name = interaction.guild.get_member(self.member_id).display_name if interaction.guild.get_member(self.member_id) else f"Użytkownik ID:{self.member_id}"

        # Pobranie listy uczestników
        participants = []
        target_dict = {}
        if type_str == "captures":
            target_dict = captures
        elif type_str == "airdrop":
            target_dict = airdrops
        elif type_str in events:
            target_dict = events[type_str]

        if msg_id in target_dict:
            participants = target_dict[msg_id].get("participants", [])
        
        success = False
        if self.action == "add":
            if self.member_id not in participants:
                participants.append(self.member_id)
                success = True
            else:
                await interaction.followup.edit_message(
                    content=f"❌ **{participant_name}** jest już zapisany(a) na **{type_str.capitalize()}** (ID: `{msg_id}`).", 
                    view=None
                )
                return
        elif self.action == "remove":
            if self.member_id in participants:
                participants.remove(self.member_id)
                success = True
            else:
                await interaction.followup.edit_message(
                    content=f"❌ **{participant_name}** nie jest zapisany(a) na **{type_str.capitalize()}** (ID: `{msg_id}`).", 
                    view=None
                )
                return

        if success:
            # Aktualizacja danych w pamięci
            if type_str == "captures":
                captures[msg_id]["participants"] = participants
            elif type_str == "airdrop":
                airdrops[msg_id]["participants"] = participants
            elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants
                 
            # Próba odświeżenia głównego embeda (jeśli wiadomość istnieje)
            data = target_dict.get(msg_id)
            if data and data.get("message"):
                message = data["message"]
                
                # Użyjmy odpowiedniego widoku, aby odświeżyć embed
                if type_str == "captures":
                    new_view = CapturesView(msg_id, interaction.guild.get_member(data['author']).display_name if interaction.guild.get_member(data['author']) else "Admin")
                    new_embed = new_view.make_embed(interaction.guild)
                elif type_str == "airdrop":
                    new_view = AirdropView(msg_id, data["description"], interaction.guild.get_channel(data["voice_channel_id"]), interaction.guild.get_member(data['author']).display_name if interaction.guild.get_member(data['author']) else "Admin")
                    new_embed = new_view.make_embed(interaction.guild)
                elif type_str in events:
                    new_view = EventView(msg_id, type_str, interaction.guild.get_member(data['author']).display_name if interaction.guild.get_member(data['author']) else "Admin")
                    new_embed = new_view.make_embed(interaction.guild)
                
                await message.edit(embed=new_embed, view=new_view)
            
            # Odpowiedź adminowi
            await interaction.followup.edit_message(
                content=f"✅ Pomyślnie {'wpisano' if self.action == 'add' else 'wypisano'} **{participant_name}** {'na' if self.action == 'add' else 'z'} **{type_str.capitalize()}** (ID: `{msg_id}`).", 
                view=None
            )

# Widok dla admina do wyboru zapisu, na który wpisać
class AddEnrollmentView(ui.View):
    def __init__(self, member_to_add: discord.Member):
        super().__init__(timeout=180)
        self.member_to_add = member_to_add
        self.add_item(EnrollmentSelectMenu("add", member_to_add.id))
        
# Widok dla admina do wyboru zapisu, z którego wypisać
class RemoveEnrollmentView(ui.View):
    def __init__(self, member_to_remove: discord.Member):
        super().__init__(timeout=180)
        self.member_to_remove = member_to_remove
        self.add_item(EnrollmentSelectMenu("remove", member_to_remove.id))


# AirdropView (poprawione)
class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel: discord.VoiceChannel, author_name: str):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.description = description
        
        # Obsługa kanału głosowego (jeśli jest to tylko ID, a nie obiekt)
        if isinstance(voice_channel, int):
            self.voice_channel = client.get_channel(voice_channel)
        else:
            self.voice_channel = voice_channel
            
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild):
        participants_ids = airdrops.get(self.message_id, {}).get("participants", [])
        
        embed = discord.Embed(title="🎁 AirDrop!", description=self.description, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL)
        embed.add_field(name="Kanał głosowy:", value=f"🔊 {self.voice_channel.mention if self.voice_channel else 'Nieznany kanał'}", inline=False)
        
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

    @ui.button(label="✅ Dołącz", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        participants = airdrops.get(self.message_id, {}).get("participants", [])
        
        if interaction.user.id in participants:
            await interaction.followup.send("Już jesteś zapisany(a).", ephemeral=True)
            return
        
        # Zapisz do pamięci i zaktualizuj embed
        airdrops.setdefault(self.message_id, {"participants": []})["participants"].append(interaction.user.id)
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.followup.send("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        participants = airdrops.get(self.message_id, {}).get("participants", [])
        
        if interaction.user.id not in participants:
            await interaction.followup.send("Nie jesteś zapisany(a).", ephemeral=True)
            return
            
        # Usuń z pamięci i zaktualizuj embed
        airdrops[self.message_id]["participants"].remove(interaction.user.id)
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.followup.send("❌ Opuściłeś(aś).", ephemeral=True)

# CapturesView (bez zmian, ale wymaga, aby make_embed było spójne)
class CapturesView(ui.View):
    def __init__(self, capture_id: int, author_name: str): 
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild):
        participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        
        # Stała, krótka treść ogłoszenia (Opis)
        description_text = "Zapraszamy wszystkich chętnych do wzięcia udziału w nadchodzących Captures! Kliknij przycisk poniżej, aby się zapisać."
        
        embed = discord.Embed(title="CAPTURES!", description=description_text, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
        data = captures.get(self.capture_id, {})
        if data.get("image_url"):
            embed.set_image(url=data["image_url"])
        
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
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id not in participants:
            await interaction.response.defer() 
            captures.setdefault(self.capture_id, {"participants": []})["participants"].append(user_id)
            await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
            await interaction.followup.send("Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id in participants:
            await interaction.response.defer() 
            captures[self.capture_id]["participants"].remove(user_id)
            await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
            await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple)
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        # ... Logika pickowania (bez zmian) ...
        await interaction.response.send_message("Logika pickowania bez zmian (wyświetli select menu).", ephemeral=True)

# EventView (Nowa klasa dla Zancudo/Cayo)
class EventView(ui.View):
    def __init__(self, message_id: int, event_type: str, author_name: str): 
        super().__init__(timeout=None)
        self.message_id = message_id
        self.event_type = event_type
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild):
        participants_ids = events[self.event_type].get(self.message_id, {}).get("participants", [])
        data = events[self.event_type].get(self.message_id, {})
        
        # Tytuły i linki
        title = "PING ZANCUDO" if self.event_type == "zancudo" else "PING CAYO"
        image_url = ZANCUDO_IMAGE_URL if self.event_type == "zancudo" else CAYO_IMAGE_URL
        
        voice_channel = guild.get_channel(data.get("voice_channel_id"))
        role = guild.get_role(data.get("role_id"))
        
        description_text = f"🚨 {role.mention if role else 'Ogłoszenie'}! Zbiórka na: **{voice_channel.mention if voice_channel else 'Nieznany kanał'}**."
        
        embed = discord.Embed(title=title, description=description_text, color=discord.Color.red())
        embed.set_image(url=image_url)
        
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
        participants = events[self.event_type].get(self.message_id, {}).get("participants", [])
        
        if user_id not in participants:
            await interaction.response.defer() 
            events[self.event_type].setdefault(self.message_id, {"participants": []})["participants"].append(user_id)
            await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
            await interaction.followup.send("Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = events[self.event_type].get(self.message_id, {}).get("participants", [])
        
        if user_id in participants:
            await interaction.response.defer() 
            events[self.event_type][self.message_id]["participants"].remove(user_id)
            await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
            await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

# Widoki Squad (bez zmian)
# ... [Pozostałe klasy widoków (PickPlayersView, SquadView, EditSquadView) pozostają bez zmian] ...

# =====================
#       PANEL ZARZĄDZANIA (ManagementPanelView)
# =====================
class ManagementPanelView(ui.View):
    def __init__(self, admin_id: int):
        super().__init__(timeout=180) # Ustawiamy timeout na 3 minuty
        self.admin_id = admin_id

    # Opcja 1: Captures
    @ui.button(label="📝 Utwórz Captures", style=discord.ButtonStyle.green, row=0)
    async def create_capt_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/create-capt #kanał @rola [link do obrazka] [timer]**, aby utworzyć ogłoszenie.", 
            ephemeral=True
        )
        
    # Opcja 2: AirDrop
    @ui.button(label="🎁 Utwórz AirDrop", style=discord.ButtonStyle.blurple, row=0)
    async def create_airdrop_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/airdrop #kanał #głosowy @rola [opis] [timer]**, aby utworzyć ogłoszenie.", 
            ephemeral=True
        )

    # Opcja 3: Zancudo
    @ui.button(label="🚁 Ping Zancudo", style=discord.ButtonStyle.red, row=1)
    async def ping_zancudo_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/ping-zancudo @rola #głosowy [timer]**, aby wysłać ogłoszenie na bieżącym kanale.", 
            ephemeral=True
        )
        
    # Opcja 4: Cayo
    @ui.button(label="🏝️ Ping Cayo", style=discord.ButtonStyle.red, row=1)
    async def ping_cayo_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/ping-cayo @rola #głosowy [timer]**, aby wysłać ogłoszenie na bieżącym kanale.", 
            ephemeral=True
        )
        
    # Opcja 5: Squad
    @ui.button(label="👥 Utwórz Squad", style=discord.ButtonStyle.blurple, row=2)
    async def create_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/create-squad #kanał @rola**, aby utworzyć ogłoszenie o składzie.", 
            ephemeral=True
        )
        
    # Opcja 6: Wpisz na zapis (zmieniona na instrukcję)
    @ui.button(label="➕ Wpisz gracza na zapis", style=discord.ButtonStyle.green, row=3)
    async def add_enroll_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/wpisz-na-capt @użytkownik**, aby dodać gracza do aktywnego zapisu. Po jej użyciu pojawi się menu wyboru zapisu.",
            ephemeral=True
        )
        
    # Opcja 7: Wypisz z zapisu (zmieniona na instrukcję)
    @ui.button(label="➖ Wypisz gracza z zapisu", style=discord.ButtonStyle.red, row=3)
    async def remove_enroll_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/wypisz-z-capt @użytkownik**, aby usunąć gracza z aktywnego zapisu. Po jej użyciu pojawi się menu wyboru zapisu.",
            ephemeral=True
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_ROLES:
            return True
        else:
            await interaction.response.send_message("❌ Tylko administrator, który otworzył panel, może z niego korzystać.", ephemeral=True)
            return False

# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    # ... [Logika przywracania widoków - bez zmian] ...
    # Symulacja reszty on_ready
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Panel Administracyjny (bez zmian)
@tree.command(name="panel", description="Wyświetla panel do tworzenia ogłoszeń (tylko Admini).")
async def panel_command(interaction: discord.Interaction):
    # ... [Logika komendy /panel - bez zmian] ...
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
    embed = discord.Embed(
        title="🛠️ Panel Zarządzania Ogłoszeniami", 
        description="Wybierz opcję. Dla tworzenia ogłoszeń użyj komendy slash z argumentami. Dla zarządzania zapisami użyj komend **/wpisz-na-capt** lub **/wypisz-z-capt**.",
        color=discord.Color.dark_green()
    )
    await interaction.followup.send(
        embed=embed, 
        view=ManagementPanelView(interaction.user.id), 
        ephemeral=True
    )

# Komenda CAPTURES (Zmodyfikowana)
@tree.command(name="create-capt", description="Tworzy ogłoszenie o Captures z zapisami.")
@app_commands.describe(
    channel="Kanał tekstowy, na którym ma zostać wysłane ogłoszenie.",
    role="Rola do spingowania (@rola).",
    image_url="Link do obrazka w tle (opcjonalnie).",
    timer_minutes="Timer w minutach (np. 5 - ping po 5 minutach).",
)
async def create_capt(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role,
    image_url: str = None,
    timer_minutes: app_commands.Range[int, 1] = None
):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return

    description_text = "Zapraszamy wszystkich chętnych do wzięcia udziału w nadchodzących Captures! Kliknij przycisk poniżej, aby się zapisać."
    
    embed = discord.Embed(title="CAPTURES!", description=description_text, color=discord.Color(0xFFFFFF))
    embed.set_thumbnail(url=LOGO_URL) 
    
    if image_url:
        embed.set_image(url=image_url)

    embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
    embed.set_footer(text=f"Wystawione przez {interaction.user.display_name}")

    role_mention = role.mention if role else ""
    timer_info = f" ({timer_minutes} minut do pingu)" if timer_minutes else ""
    
    content_message = f"{role_mention} **NOWE CAPTURES!** Ogłoszenie na kanale: {channel.mention}{timer_info}"
    
    try:
        message = await channel.send(
            content=content_message,
            embed=embed,
            view=CapturesView(0, interaction.user.display_name) 
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości na kanale {channel.mention}. Sprawdź uprawnienia bota. Błąd: {e}", ephemeral=True)
        return

    # Zapisanie do pamięci
    captures[message.id] = {
        "participants": [],
        "author": interaction.user.id,
        "channel_id": channel.id,
        "message": message,
        "role_id": role.id if role else None,
        "image_url": image_url
    }
    
    # Aktualizacja view z poprawnym ID
    view = CapturesView(message.id, interaction.user.display_name)
    await message.edit(view=view)
    
    confirmation_message = await interaction.followup.send(f"✅ Ogłoszenie **CAPTURES** wysłano na {channel.mention}.", ephemeral=True)

    # Uruchomienie timera w tle
    if timer_minutes:
         client.loop.create_task(send_timer_ping(channel.id, role.id if role else None, timer_minutes, message.id, confirmation_message))


# Komenda AIRDROP (Zmodyfikowana)
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie z zapisami.")
@app_commands.describe(
    channel="Kanał tekstowy, na którym ma zostać wysłane ogłoszenie.",
    voice_channel="Kanał głosowy, na którym mają się zbierać gracze.",
    role="Rola do spingowania (@rola).",
    description="Opis i zasady AirDropa (np. 'Zasady: RPK, 30 min, 5 osób').",
    timer_minutes="Timer w minutach (np. 10 - ping po 10 minutach)."
)
async def airdrop(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    voice_channel: discord.VoiceChannel,
    role: discord.Role,
    description: str,
    timer_minutes: app_commands.Range[int, 1] = None
):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return

    embed = discord.Embed(title="🎁 AirDrop!", description=description, color=discord.Color(0xFFFFFF))
    embed.set_thumbnail(url=LOGO_URL)
    embed.add_field(name="Kanał głosowy:", value=f"🔊 {voice_channel.mention}", inline=False)
    embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
    embed.set_footer(text=f"Wystawione przez {interaction.user.display_name}")

    role_mention = role.mention if role else ""
    timer_info = f" ({timer_minutes} minut do pingu)" if timer_minutes else ""
    content_message = f"{role_mention} **NOWY AIRDROP!** Zbiórka na {voice_channel.mention}{timer_info}"

    try:
        message = await channel.send(
            content=content_message,
            embed=embed,
            view=AirdropView(0, description, voice_channel, interaction.user.display_name)
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości na kanale {channel.mention}. Sprawdź uprawnienia bota. Błąd: {e}", ephemeral=True)
        return

    # Zapisanie do pamięci
    airdrops[message.id] = {
        "participants": [],
        "author": interaction.user.id,
        "channel_id": channel.id,
        "voice_channel_id": voice_channel.id,
        "description": description,
        "message": message,
        "role_id": role.id if role else None
    }
    
    view = AirdropView(message.id, description, voice_channel, interaction.user.display_name)
    await message.edit(view=view)

    confirmation_message = await interaction.followup.send(f"✅ Ogłoszenie **AIRDROP** wysłano na {channel.mention}.", ephemeral=True)

    if timer_minutes:
         client.loop.create_task(send_timer_ping(channel.id, role.id if role else None, timer_minutes, message.id, confirmation_message))


# Funkcja pomocnicza do pingowania eventów (Zancudo/Cayo)
async def create_event_ping(
    interaction: discord.Interaction, 
    event_type: Literal["zancudo", "cayo"], 
    role: discord.Role, 
    voice_channel: discord.VoiceChannel, 
    timer_minutes: app_commands.Range[int, 1] = None
):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
        
    image_url = ZANCUDO_IMAGE_URL if event_type == "zancudo" else CAYO_IMAGE_URL
    title = "PING ZANCUDO" if event_type == "zancudo" else "PING CAYO"
    
    description_text = f"🚨 {role.mention} **{title}**! Zbiórka na: **{voice_channel.mention}**."
    
    embed = discord.Embed(
        title=title, 
        description=description_text, 
        color=discord.Color.red()
    )
    embed.set_image(url=image_url) 
    
    embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
    embed.set_footer(text=f"Wystawione przez {interaction.user.display_name}")

    role_mention = role.mention if role else ""
    timer_info = f" ({timer_minutes} minut do pingu)" if timer_minutes else ""
    content_message = f"{role_mention} **{title.upper()}!** Zbiórka na {voice_channel.mention}{timer_info}"

    try:
        message = await interaction.channel.send(
            content=content_message,
            embed=embed,
            view=EventView(0, event_type, interaction.user.display_name)
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości. Sprawdź uprawnienia bota. Błąd: {e}", ephemeral=True)
        return

    # Zapisanie do pamięci
    events[event_type][message.id] = {
        "participants": [],
        "author": interaction.user.id,
        "channel_id": interaction.channel.id,
        "voice_channel_id": voice_channel.id,
        "message": message,
        "role_id": role.id if role else None
    }
    
    view = EventView(message.id, event_type, interaction.user.display_name)
    await message.edit(view=view)

    confirmation_message = await interaction.followup.send(f"✅ Ogłoszenie **{title}** wysłano na {interaction.channel.mention}.", ephemeral=True)

    if timer_minutes:
         client.loop.create_task(send_timer_ping(interaction.channel.id, role.id if role else None, timer_minutes, message.id, confirmation_message))

@tree.command(name="ping-zancudo", description="Ping o Zancudo (tylko Admini).")
@app_commands.describe(
    role="Rola do spingowania (@rola).",
    voice_channel="Kanał głosowy, na którym mają się zbierać gracze.",
    timer_minutes="Timer w minutach (np. 5 - ping po 5 minutach)."
)
async def ping_zancudo(
    interaction: discord.Interaction, 
    role: discord.Role, 
    voice_channel: discord.VoiceChannel,
    timer_minutes: app_commands.Range[int, 1] = None
):
    await create_event_ping(interaction, "zancudo", role, voice_channel, timer_minutes)

@tree.command(name="ping-cayo", description="Ping o Cayo (tylko Admini).")
@app_commands.describe(
    role="Rola do spingowania (@rola).",
    voice_channel="Kanał głosowy, na którym mają się zbierać gracze.",
    timer_minutes="Timer w minutach (np. 5 - ping po 5 minutach)."
)
async def ping_cayo(
    interaction: discord.Interaction, 
    role: discord.Role, 
    voice_channel: discord.VoiceChannel,
    timer_minutes: app_commands.Range[int, 1] = None
):
    await create_event_ping(interaction, "cayo", role, voice_channel, timer_minutes)

# Komenda SQUAD (Zmodyfikowana)
@tree.command(name="create-squad", description="Tworzy ogłoszenie o składzie z możliwością edycji.")
@app_commands.describe(
    channel="Kanał tekstowy, na którym ma zostać wysłane ogłoszenie.",
    role="Rola do spingowania (@rola)."
)
async def create_squad(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role
):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return

    author_name = interaction.user.display_name
    member_ids = []
    
    # Utworzenie podstawowego embeda
    embed = discord.Embed(
        title="Main Squad", 
        description="Brak członków składu. Użyj przycisku 'Zarządzaj składem' aby ustalić członków.", 
        color=discord.Color(0xFFFFFF)
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.add_field(name="Liczba członków:", value="**0**", inline=False)
    embed.set_footer(text=f"Aktywowane przez {author_name}")
    
    content_message = f"{role.mention} **NOWY SQUAD!** Użyj 'Zarządzaj składem' aby ustalić członków."

    try:
        # Wysyłamy wiadomość
        message = await channel.send(
            content=content_message,
            embed=embed,
            view=SquadView(0, role.id)
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości na kanale {channel.mention}. Sprawdź uprawnienia bota. Błąd: {e}", ephemeral=True)
        return

    # Zapisanie do pamięci
    squads[message.id] = {
        "member_ids": member_ids,
        "author": interaction.user.id,
        "channel_id": channel.id,
        "message": message,
        "role_id": role.id
    }
    
    # Aktualizacja view z poprawnym ID
    await message.edit(view=SquadView(message.id, role.id))
    
    await interaction.followup.send(f"✅ Ogłoszenie **SQUAD** wysłano na {channel.mention}.", ephemeral=True)


# Komenda Wpisz-na-capt
@tree.command(name="wpisz-na-capt", description="Wpisuje użytkownika na dowolny aktywny zapis (Captures, AirDrop, Event).")
@app_commands.describe(członek="Użytkownik, którego chcesz wpisać.")
async def add_to_enrollment(interaction: discord.Interaction, członek: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
        
    enrollments = get_all_active_enrollments()
    if not enrollments:
        await interaction.followup.send("⚠️ Brak aktywnych zapisów, na które można wpisać użytkownika.", ephemeral=True)
        return
        
    await interaction.followup.send(
        f"Wybierz zapis, na który wpisać **{członek.display_name}**:", 
        view=AddEnrollmentView(członek), 
        ephemeral=True
    )

# Komenda Wypisz-z-capt
@tree.command(name="wypisz-z-capt", description="Wypisuje użytkownika z dowolnego aktywnego zapisu (Captures, AirDrop, Event).")
@app_commands.describe(członek="Użytkownik, którego chcesz wypisać.")
async def remove_from_enrollment(interaction: discord.Interaction, członek: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!.", ephemeral=True)
        return
        
    enrollments = get_all_active_enrollments()
    if not enrollments:
        await interaction.followup.send("⚠️ Brak aktywnych zapisów, z których można wypisać użytkownika.", ephemeral=True)
        return
        
    await interaction.followup.send(
        f"Wybierz zapis, z którego wypisać **{członek.display_name}**:", 
        view=RemoveEnrollmentView(członek), 
        ephemeral=True
    )

# --- Start bota ---
def run_discord_bot():
    # ... [Logika uruchamiania Flask i Bota - bez zmian] ...
    # Symulacja reszty run_discord_bot
    pass

# Upewnij się, że na końcu pliku masz tylko kod startujący
# run_discord_bot()
# client.run(token)
