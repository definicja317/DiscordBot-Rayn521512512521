import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime
import re 
import traceback # DODANO: dla lepszej obsługi błędów

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

# DODANO: GLOBALNA OBSŁUGA BŁĘDÓW (aby uniknąć "Unknown interaction" i "Brak integracji")
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Drukuj błąd w konsoli (to jest najważniejsze, by poznać przyczynę)
    print(f"Globalny błąd komendy {interaction.command.name} (użytkownik: {interaction.user.display_name}):")
    # Logowanie pełnego tracebacka
    traceback.print_exc() 
    
    # Obsługa błędu MissingRole
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(f"⛔ Nie masz wymaganej roli, aby użyć tej komendy! (Wymagana rola ID: `{error.missing_role}`)", ephemeral=True)
        return
        
    # Obsługa innych błędów, w tym 404 (Unknown Interaction)
    error_name = type(error).__name__
    
    # Wysyłanie wiadomości zwrotnej do użytkownika
    try:
        # Sprawdzamy, czy interakcja została już obsłużona (np. przez defer)
        if interaction.response.is_done():
            # Używamy followup, jeśli bot już odpowiedział
            await interaction.followup.send(f"❌ Wystąpił błąd w kodzie: `{error_name}`. Sprawdź logi bota! Jeśli to był błąd 404/10062, powinien teraz zniknąć.", ephemeral=True)
        else:
            # Odpowiadamy normalnie, jeśli interakcja jeszcze nie została obsłużona
            await interaction.response.send_message(f"❌ Wystąpił błąd w kodzie: `{error_name}`. Sprawdź logi bota! Jeśli to był błąd 404/10062, powinien teraz zniknąć.", ephemeral=True)
            
    except discord.HTTPException:
        # Jeśli nawet próba wysłania błędu zwróci błąd HTTP (np. Unknown Interaction)
        print("Nie udało się wysłać wiadomości o błędzie do użytkownika, prawdopodobnie interakcja wygasła (10062).")
# KONIEC GLOBALNEJ OBSŁUGI BŁĘDÓW


# --- Pamięć zapisów ---
# WAŻNE: W przypadku restartu bota te dane zostaną wyczyszczone!
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
        # Dodanie custom_id
        super().__init__(
            placeholder=f"Wybierz zapis:",
            max_values=1,
            min_values=1,
            options=options,
            custom_id=f"enrollment_select_{action}"
        )
    async def callback(self, interaction: discord.Interaction):
        pass 
# <<< KONIEC ZARZĄDZANIE ZAPISAMI >>>

# =====================
#       AIRDROP & CAPTURES VIEWS
# =====================
class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel: discord.VoiceChannel, author_name: str):
        # ZMIANA: timeout=None dla trwałych widoków
        super().__init__(timeout=None)
        self.message_id = message_id
        self.description = description
        self.voice_channel = voice_channel
        self.participants: list[int] = [] 
        self.author_name = author_name
        # ZMIANA: Dodanie custom_id widoku, ważne do przywracania
        self.custom_id = f"airdrop_view:{message_id}" 

    def make_embed(self, guild: discord.Guild):
        # POPRAWKA KOLORU: używamy 0xFFFFFF (biały) zamiast .white
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

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="✅ Dołącz", style=discord.ButtonStyle.green, custom_id="airdrop_join")
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        # KLUCZOWA POPRAWKA: defer przy edycji głównej wiadomości, aby uniknąć 10062
        await interaction.response.defer() 
        
        if interaction.user.id in self.participants:
            await interaction.followup.send("Już jesteś zapisany(a).", ephemeral=True)
            return
        
        # Używamy bezpiecznego dostępu
        if self.message_id not in airdrops:
             # Jeśli bot się zrestartował i nie odzyskał danych, ale widok został przywrócony
             await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota. Spróbuj utworzyć nowy zapis.", ephemeral=True)
             return
             
        self.participants.append(interaction.user.id)
        airdrops[self.message_id]["participants"].append(interaction.user.id)
        
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.followup.send("✅ Dołączyłeś(aś)!", ephemeral=True)

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red, custom_id="airdrop_leave")
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        # KLUCZOWA POPRAWKA: defer przy edycji głównej wiadomości, aby uniknąć 10062
        await interaction.response.defer() 
        
        if interaction.user.id not in self.participants:
            await interaction.followup.send("Nie jesteś zapisany(a).", ephemeral=True)
            return
            
        # Używamy bezpiecznego dostępu
        if self.message_id not in airdrops:
             await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota. Spróbuj utworzyć nowy zapis.", ephemeral=True)
             return
             
        self.participants.remove(interaction.user.id)
        airdrops[self.message_id]["participants"].remove(interaction.user.id)
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.followup.send("❌ Opuściłeś(aś).", ephemeral=True)

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

        # ZMIANA: Dodanie custom_id
        super().__init__(
            placeholder="Wybierz do 25 graczy",
            max_values=min(25, len(options)),
            options=options,
            custom_id=f"player_select:{capture_id}"
        )

    async def callback(self, interaction: discord.Interaction):
        # Ta interakcja nie musi nic robić, tylko buforować wybór, więc defer wystarczy
        await interaction.response.defer() 

class PickPlayersView(ui.View):
    def __init__(self, capture_id: int):
        # ZMIANA: Dodanie custom_id
        super().__init__(timeout=180, custom_id=f"pick_players_view:{capture_id}")
        self.capture_id = capture_id

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="Potwierdź wybór", style=discord.ButtonStyle.green, custom_id="confirm_pick_button")
    async def confirm_pick(self, interaction: discord.Interaction, button: ui.Button):
        # Defer, bo generowanie i wysłanie embeda zajmuje czas
        await interaction.response.defer(ephemeral=True)
        
        # Iteracja po children, aby znaleźć SelectMenu, bez CustomID jest to bezpieczniejsze
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        
        if not select_menu:
             await interaction.followup.send("Błąd: Nie znaleziono menu wyboru. Spróbuj ponownie.", ephemeral=True)
             return
             
        selected_values = select_menu.values
        
        if not selected_values:
            await interaction.followup.send("Nie wybrano żadnych osób!", ephemeral=True)
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
        await interaction.followup.send(embed=final_embed)

class CapturesView(ui.View):
    # ZMIANA W INICJALIZACJI: Dodanie image_url
    def __init__(self, capture_id: int, author_name: str, image_url: str = None): 
        # ZMIANA: timeout=None dla trwałych widoków
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name
        self.image_url = image_url # DODANE
        # ZMIANA: Dodanie custom_id widoku, ważne do przywracania
        self.custom_id = f"captures_view:{capture_id}"

    def make_embed(self, guild: discord.Guild):
        participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        
        # POPRAWKA KOLORU: używamy 0xFFFFFF (biały)
        embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
        # DODANA LOGIKA: Ustawienie obrazka, jeśli link został podany
        if self.image_url:
            embed.set_image(url=self.image_url)
        
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

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green, custom_id="capt_join")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id not in participants:
            # KLUCZOWA POPRAWKA: defer przy edycji głównej wiadomości, aby uniknąć 10062
            await interaction.response.defer() 
            
            # Używamy bezpiecznego dostępu
            if self.capture_id not in captures:
                 # UWZGLĘDNIENIE image_url przy ponownej inicjalizacji danych, jeśli zaginęły
                 captures[self.capture_id] = {"participants": [], "author_name": self.author_name, "image_url": self.image_url} 
                 
            captures[self.capture_id]["participants"].append(user_id)
            
            data = captures.get(self.capture_id)
            if data and data.get("message"):
                await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
                await interaction.followup.send("Zostałeś(aś) zapisany(a)!", ephemeral=True)
            else:
                # Jeśli wiadomość zaginęła (np. bot się zrestartował)
                await interaction.followup.send("Zostałeś(aś) zapisany(a), ale wiadomość ogłoszenia mogła zaginąć po restarcie bota.", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red, custom_id="capt_leave")
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id in participants:
            # KLUCZOWA POPRAWKA: defer przy edycji głównej wiadomości, aby uniknąć 10062
            await interaction.response.defer() 
            
            # Używamy bezpiecznego dostępu
            if self.capture_id not in captures:
                 await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota.", ephemeral=True)
                 return
                 
            captures[self.capture_id]["participants"].remove(user_id)
            
            data = captures.get(self.capture_id)
            if data and data.get("message"):
                await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
                await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
            else:
                 # Jeśli wiadomość zaginęła (np. bot się zrestartował)
                 await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple, custom_id="capt_pick")
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        # Defer, bo wysłanie nowego view zajmuje czas
        await interaction.response.defer(ephemeral=True)
        
        # POPRAWKA: Używamy roli z danych
        guild_member = interaction.guild.get_member(interaction.user.id)
        if PICK_ROLE_ID not in [r.id for r in guild_member.roles]:
            await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
            return
            
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if not participants:
            await interaction.followup.send("Nikt się nie zapisał!", ephemeral=True)
            return
            
        pick_view = PickPlayersView(self.capture_id)
        pick_view.add_item(PlayerSelectMenu(self.capture_id, interaction.guild))
        
        await interaction.followup.send("Wybierz do 25 graczy:", view=pick_view, ephemeral=True)


# =======================================================
# <<< FUNKCJE DLA SQUADÓW (Z POPRAWKAMI) >>>
# =======================================================

def create_squad_embed(guild: discord.Guild, author_name: str, member_ids: list[int], title: str = "Main Squad"):
    """Tworzy embed dla Squadu na podstawie listy ID. POPRAWIONO KOLOR."""
    
    member_lines = []
    
    for i, uid in enumerate(member_ids):
        member = guild.get_member(uid)
        if member:
            member_lines.append(f"{i+1}- {member.mention} | **{member.display_name}**")
        else:
            member_lines.append(f"{i+1}- <@{uid}> (Nieznany/Opuścił serwer)")
            
    members_list_str = "\n".join(member_lines) if member_lines else "Brak członków składu."
    count = len(member_ids)
        
    # POPRAWKA KOLORU: używamy 0xFFFFFF (biały) zamiast .white
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
    """Widok zawierający menu wyboru użytkowników i przycisk Potwierdź edycję. **Zastępuje Modal**."""
    def __init__(self, message_id: int):
        # Timeout 3 minuty, ZMIANA: Dodanie custom_id
        super().__init__(timeout=180, custom_id=f"edit_squad_view:{message_id}") 
        self.message_id = message_id
        
        # UserSelect (wybieracz użytkowników) - max 25
        self.add_item(ui.UserSelect(
            placeholder="Wybierz członków składu (max 25)",
            max_values=25, 
            custom_id="squad_member_picker"
        ))

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="✅ Potwierdź edycję", style=discord.ButtonStyle.green, custom_id="confirm_edit_squad")
    async def confirm_edit(self, interaction: discord.Interaction, button: ui.Button):
        # KLUCZOWA POPRAWKA: Odroczenie interakcji, ponieważ edytujemy główną wiadomość!
        await interaction.response.defer(ephemeral=True)

        # Pobieramy ID wybranych użytkowników z UserSelect
        select_menu = next((item for item in self.children if item.custom_id == "squad_member_picker"), None)
        selected_ids = []
        if select_menu and select_menu.values:
            # UserSelect zwraca obiekty User/Member, a my potrzebujemy ID
            selected_ids = [user.id for user in select_menu.values]
        
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
            # Upewniamy się, że pierwszy embed istnieje
            if message.embeds:
                title = message.embeds[0].title
            
        new_embed = create_squad_embed(interaction.guild, author_name, selected_ids, title)
        
        # Odświeżamy wiadomość
        if message and hasattr(message, 'edit'):
            # Wysyłamy pierwotny widok z powrotem, który teraz ma tylko przycisk Zarządzaj
            new_squad_view = SquadView(self.message_id, squad_data.get("role_id"))
            
            role_id = squad_data.get("role_id")
            # Poprawka: używamy <@&ID> dla roli
            content = f"<@&{role_id}> **Zaktualizowano Skład!**" if role_id else ""
            
            await message.edit(content=content, embed=new_embed, view=new_squad_view)
            
            # Odpowiedź po pomyślnej edycji
            await interaction.followup.send(content="✅ Skład został pomyślnie zaktualizowany! Wróć do głównej wiadomości składu.", ephemeral=True)
        else:
            await interaction.followup.send(content="Błąd: Nie można odświeżyć wiadomości składu. Być może bot został zrestartowany.", ephemeral=True)


class SquadView(ui.View):
    """Główny widok składu z przyciskiem do przejścia do edycji. Z usuniętym przyciskiem 'Dołącz'."""
    def __init__(self, message_id: int, role_id: int):
        # ZMIANA: timeout=None dla trwałych widoków
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id
        # ZMIANA: Dodanie custom_id widoku, ważne do przywracania
        self.custom_id = f"squad_view:{message_id}"

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="Zarządzaj składem (ADMIN)", style=discord.ButtonStyle.blurple, custom_id="manage_squad_button")
    async def manage_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        # KLUCZOWA POPRAWKA: Odroczenie interakcji! Zapobiega błędom 404/10062 i 400 Bad Request.
        await interaction.response.defer(ephemeral=True) 

        if interaction.user.id not in ADMIN_ROLES:
            await interaction.followup.send("⛔ Brak uprawnień do zarządzania składem!", ephemeral=True)
            return

        squad_data = squads.get(self.message_id)
        if not squad_data:
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return
            
        # Zastępujemy Modala widokiem z UserSelect
        edit_view = EditSquadView(self.message_id)
            
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
    
    # 1. SQUAD VIEWS
    if squads:
        print(f"Próba przywrócenia {len(squads)} widoków Squad.")
        for msg_id, data in squads.items():
             try:
                 # Ważne: musimy ustawić message obiekt, aby móc edytować
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     # Upewniamy się, że message nie zostanie ustawione, jeśli nie znajdziemy wiadomości
                     data["message"] = await channel.fetch_message(msg_id)
                     # ZMIANA: Dodajemy widok
                     client.add_view(SquadView(msg_id, data["role_id"]))
             except discord.NotFound:
                 print(f"Ostrzeżenie: Nie znaleziono wiadomości Squad {msg_id}. Pomijam przywracanie widoku.")
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku Squad {msg_id}: {e}")
                 
    # 2. CAPTURES VIEWS
    if captures:
        print(f"Próba przywrócenia {len(captures)} widoków Captures.")
        for msg_id, data in captures.items():
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     data["message"] = await channel.fetch_message(msg_id)
                     # ZMIANA: Dodajemy widok CapturesView, przekazując image_url
                     image_url = data.get("image_url")
                     client.add_view(CapturesView(msg_id, data["author_name"], image_url))
             except discord.NotFound:
                 print(f"Ostrzeżenie: Nie znaleziono wiadomości Captures {msg_id}. Pomijam przywracanie widoku.")
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku Captures {msg_id}: {e}")
                 
    # 3. AIRDROP VIEWS
    if airdrops:
        print(f"Próba przywrócenia {len(airdrops)} widoków AirDrop.")
        for msg_id, data in airdrops.items():
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     data["message"] = await channel.fetch_message(msg_id)
                     voice_channel = client.get_channel(data["voice_channel_id"])
                     
                     if voice_channel:
                         view = AirdropView(msg_id, data["description"], voice_channel, data["author_name"])
                         view.participants = data.get("participants", []) # Ustawienie listy uczestników
                         # ZMIANA: Dodajemy widok AirdropView
                         client.add_view(view)
                     else:
                         print(f"Ostrzeżenie: Nie znaleziono kanału głosowego dla AirDrop {msg_id}. Pomijam przywracanie widoku.")
             except discord.NotFound:
                 print(f"Ostrzeżenie: Nie znaleziono wiadomości AirDrop {msg_id}. Pomijam przywracanie widoku.")
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku AirDrop {msg_id}: {e}")
                 
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
    # Ważne: message_id=0 zostanie ustawione później na sent.id
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
    
    # Aktualizacja View z poprawnym ID wiadomości i custom_id
    view.message_id = sent.id
    view.custom_id = f"squad_view:{sent.id}"
    await sent.edit(view=view) 
    
    # Odpowiedź w kanale follow up
    await interaction.followup.send(f"✅ Ogłoszenie o składzie '{tytul}' dla roli {rola.mention} wysłane!", ephemeral=True)


# ZMIANA: Dodanie opcjonalnego argumentu 'link_do_zdjecia'
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures.")
async def create_capt(interaction: discord.Interaction, link_do_zdjecia: str = None):
    # KLUCZOWA POPRAWKA: Defer
    await interaction.response.defer(ephemeral=True) 
    
    author_name = interaction.user.display_name
    
    # Ważne: message_id=0 zostanie ustawione później na sent.id
    # ZMIANA: Przekazujemy link_do_zdjecia do widoku
    view = CapturesView(0, author_name, link_do_zdjecia) 
    embed = view.make_embed(interaction.guild)
    
    sent = await interaction.channel.send(content="@everyone", embed=embed, view=view)
    
    # ZMIANA: Zapisujemy link_do_zdjecia w pamięci
    captures[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "author_name": author_name,
        "image_url": link_do_zdjecia # DODANE
    }
    
    # Aktualizacja View z poprawnym ID wiadomości i custom_id
    view.capture_id = sent.id 
    view.custom_id = f"captures_view:{sent.id}"
    await sent.edit(view=view) 
    
    # ZMIANA: Wysyłamy wiadomość follow-up po zakończeniu wszystkich operacji
    await interaction.followup.send("Ogłoszenie o captures wysłane!", ephemeral=True)

# AirDrop
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie")
async def airdrop_command(interaction: discord.Interaction, channel: discord.TextChannel, voice: discord.VoiceChannel, role: discord.Role, opis: str):
    # KLUCZOWA POPRAWKA: Defer
    await interaction.response.defer(ephemeral=True)
    # Ważne: message_id=0 zostanie ustawione później na sent.id
    view = AirdropView(0, opis, voice, interaction.user.display_name)
    embed = view.make_embed(interaction.guild)
    sent = await channel.send(content=f"{role.mention}", embed=embed, view=view)
    
    # Zapisanie danych AirDrop
    airdrops[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "description": opis, 
        "voice_channel_id": voice.id, 
        "author_name": interaction.user.display_name
    }
    
    # Aktualizacja View z poprawnym ID wiadomości i custom_id
    view.message_id = sent.id
    view.custom_id = f"airdrop_view:{sent.id}"
    await sent.edit(view=view)
    
    await interaction.followup.send("✅ AirDrop utworzony!", ephemeral=True)

# Eventy Zancudo / Cayo
@tree.command(name="ping-zancudo", description="Wysyła ogłoszenie o ataku na Fort Zancudo.")
async def ping_zancudo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    # KLUCZOWA POPRAWKA: Defer
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="Atak na FORT ZANCUDO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFF0000))
    embed.set_image(url=ZANCUDO_IMAGE_URL)
    embed.set_thumbnail(url=LOGO_URL) 
    sent = await interaction.channel.send(content=f"{role.mention}", embed=embed)
    events["zancudo"][sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

@tree.command(name="ping-cayo", description="Wysyła ogłoszenie o ataku na Cayo Perico.")
async def ping_cayo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    # KLUCZOWA POPRAWKA: Defer
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
    # KLUCZOWA POPRAWKA: Defer
    await interaction.response.defer(ephemeral=True)
    desc = ""
    for name, mid, data in get_all_active_enrollments():
        desc += f"\n**{name} (msg {mid})**: {len(data['participants'])} osób"
        
    for mid, data in squads.items():
        count = len(data.get('member_ids', []))
        desc += f"\n**Squad (msg {mid})**: {count} osób"

    if not desc:
        desc = "Brak aktywnych zapisów i składów."
    # POPRAWKA KOLORU: używamy 0xFFFFFF (biały) zamiast .blue()
    embed = discord.Embed(title="📋 Lista wszystkich zapisanych i składów", description=desc, color=discord.Color(0xFFFFFF))
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
        # ZMIANA: Dodanie custom_id
        super().__init__(timeout=180, custom_id=f"remove_enrollment_view:{member_to_remove.id}")
        self.member_to_remove = member_to_remove
        self.add_item(EnrollmentSelectMenu("remove"))

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="Potwierdź usunięcie", style=discord.ButtonStyle.red, custom_id="confirm_remove_button")
    async def confirm_remove(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() # Defer w trakcie przetwarzania
        
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not select_menu or not select_menu.values:
            await interaction.followup.send("⚠️ Najpierw wybierz zapis z listy!", ephemeral=True)
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
            await interaction.followup.edit_message(content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.", view=None)
            return

        participants = data_dict.get("participants", [])
        
        if user_id not in participants:
            await interaction.followup.edit_message(content=f"⚠️ **{self.member_to_remove.display_name}** nie jest zapisany(a) na ten **{type_str.capitalize()}**.", view=None)
            return

        participants.remove(user_id)
        
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
            if type_str == "airdrop":
                voice_channel = message.guild.get_channel(data_dict["voice_channel_id"])
                description = data_dict["description"]
                author_name = data_dict["author_name"]
                
                # ZMIANA: używamy message_id z data_dict, nie z view (view ma 0 w nowym AirdropView)
                view_obj = AirdropView(msg_id, description, voice_channel, author_name) 
                view_obj.participants = participants
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
            elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
                 author_name = data_dict["author_name"]
                 image_url = data_dict.get("image_url") # POBRANO image_url
                 # ZMIANA: używamy message_id z data_dict i przekazujemy image_url
                 view_obj = CapturesView(msg_id, author_name, image_url) 
                 new_embed = view_obj.make_embed(message.guild)
                 await message.edit(embed=new_embed, view=view_obj)
            elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants

        await interaction.followup.edit_message(
            content=f"✅ Pomyślnie wypisano **{self.member_to_remove.display_name}** z **{type_str.capitalize()}** (ID: `{msg_id}`).", 
            view=None
        )

@tree.command(name="wypisz-z-capt", description="Wypisuje użytkownika z dowolnego aktywnego zapisu (Captures, AirDrop, Event).")
async def remove_from_enrollment(interaction: discord.Interaction, członek: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
        
    enrollments = get_all_active_enrollments()
    if not enrollments:
        await interaction.followup.send("⚠️ Brak aktywnych zapisów, z których można wypisać użytkownika.", ephemeral=True)
        return
        
    await interaction.followup.send(
        f"Wybierz zapis, z którego usunąć **{członek.display_name}**:", 
        view=RemoveEnrollmentView(członek), 
        ephemeral=True
    )

# Wpisz na capt
class AddEnrollmentView(ui.View):
    def __init__(self, member_to_add: discord.Member):
        # ZMIANA: Dodanie custom_id
        super().__init__(timeout=180, custom_id=f"add_enrollment_view:{member_to_add.id}")
        self.member_to_add = member_to_add
        self.add_item(EnrollmentSelectMenu("add"))

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="Potwierdź dodanie", style=discord.ButtonStyle.green, custom_id="confirm_add_button")
    async def confirm_add(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() # Defer w trakcie przetwarzania
        
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not select_menu or not select_menu.values:
            await interaction.followup.send("⚠️ Najpierw wybierz zapis z listy!", ephemeral=True)
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
            await interaction.followup.edit_message(content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.", view=None)
            return

        participants = data_dict.get("participants", [])
        
        if user_id in participants:
            await interaction.followup.edit_message(content=f"⚠️ **{self.member_to_add.display_name}** jest już zapisany(a) na ten **{type_str.capitalize()}**.", view=None)
            return

        participants.append(user_id)
        
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
             if type_str == "airdrop":
                voice_channel = message.guild.get_channel(data_dict["voice_channel_id"])
                description = data_dict["description"]
                author_name = data_dict["author_name"]

                # ZMIANA: używamy message_id z data_dict
                view_obj = AirdropView(msg_id, description, voice_channel, author_name) 
                view_obj.participants = participants
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
             elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
                 author_name = data_dict["author_name"]
                 image_url = data_dict.get("image_url") # POBRANO image_url
                 # ZMIANA: używamy message_id z data_dict i przekazujemy image_url
                 view_obj = CapturesView(msg_id, author_name, image_url) 
                 new_embed = view_obj.make_embed(message.guild)
                 await message.edit(embed=new_embed, view=view_obj)
             elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants

        await interaction.followup.edit_message(
            content=f"✅ Pomyślnie wpisano **{self.member_to_add.display_name}** na **{type_str.capitalize()}** (ID: `{msg_id}`).", 
            view=None
        )

@tree.command(name="wpisz-na-capt", description="Wpisuje użytkownika na dowolny aktywny zapis (Captures, AirDrop, Event).")
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


# --- Start bota ---
def run_discord_bot():
    try:
        client.run(token)
    except Exception as e:
        print(f"Błąd uruchomienia bota: {e}")

threading.Thread(target=run_discord_bot).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
