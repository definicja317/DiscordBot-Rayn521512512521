import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
# ZMIANA: Dodajemy asyncio, pytz, timedelta
import asyncio
import pytz 
from datetime import datetime, timedelta, timezone 
import re 
import traceback 

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
# ZMIANA: Definicja strefy czasowej dla Polski (dla timera)
POLAND_TZ = pytz.timezone('Europe/Warsaw')

# WAŻNE: Wprowadź swoje faktyczne ID ról/użytkowników.
BOT_COMMAND_ROLE_ID = 1413424476770664499 # <<< ZMIEŃ TO NA FAKTYCZNE ID ROLI!
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

# DODANO: GLOBALNA OBSŁUGA BŁĘDÓW (aby uniknąć "Brak integracji")
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Drukuj błąd w konsoli (to jest najważniejsze, by poznać przyczynę)
    print(f"Globalny błąd komendy {interaction.command.name} (użytkownik: {interaction.user.display_name}):")
    # Zabezpieczenie przed błędem uprawnień
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(f"⛔ Nie masz wymaganej roli, aby użyć tej komendy! (Wymagana rola ID: `{error.missing_role}`)", ephemeral=True)
        return
    
    traceback.print_exc()

    # Wysyłanie wiadomości zwrotnej do użytkownika, aby uniknąć "Brak integracji"
    try:
        # Sprawdzamy, czy interakcja została już obsłużona (np. przez defer)
        if interaction.response.is_done():
            # Używamy followup, jeśli bot już odpowiedział
            await interaction.followup.send(f"❌ Wystąpił błąd w kodzie: `{type(error).__name__}`. Sprawdź logi bota!", ephemeral=True)
        else:
            # Odpowiadamy normalnie, jeśli interakcja jeszcze nie została obsłużona
            await interaction.response.send_message(f"❌ Wystąpił błąd w kodzie: `{type(error).__name__}`. Sprawdź logi bota!", ephemeral=True)
            
    except discord.HTTPException:
        pass
# KONIEC GLOBALNEJ OBSŁUGI BŁĘDÓW


# ZMIANA: FUNKCJA SPRAWDZAJĄCA, CZY UŻYTKOWNIK MA WYMAGANĄ ROLĘ
def is_allowed_role():
    """Sprawdza, czy użytkownik ma rolę BOT_COMMAND_ROLE_ID."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            # Zezwalaj na komendy w DM (jeśli masz takie komendy)
            return True
        
        # Sprawdzamy, czy BOT_COMMAND_ROLE_ID jest w rolach użytkownika
        if BOT_COMMAND_ROLE_ID not in [role.id for role in interaction.user.roles]:
            # Rzucamy wyjątek, który zostanie przechwycony przez @tree.error
            raise app_commands.MissingRole(BOT_COMMAND_ROLE_ID)
        return True
    return app_commands.check(predicate)


# --- Pamięć zapisów ---
# WAŻNE: W przypadku restartu bota te dane zostaną wyczyszczone!
captures = {}   
airdrops = {}   
events = {"zancudo": {}, "cayo": {}} 
squads = {}     

# <<< DODANO: NARZĘDZIA DO TIMERA >>>

def format_countdown(end_time: datetime) -> tuple[str, bool]:
    """Zwraca sformatowany czas do końca i flagę, czy czas minął."""
    # Upewniamy się, że aktualny czas jest świadomy strefy czasowej
    now = datetime.now(POLAND_TZ) 
    remaining = end_time - now
    
    # Czas minął
    if remaining.total_seconds() <= 0:
        return "🔴 Czas minął! Zapisy zamknięte.", True 

    seconds = int(remaining.total_seconds())
    
    # Poniżej 1 minuty: Pokaż sekundy
    if seconds < 60:
        return f"⏱️ Pozostało: **{seconds} sekund**", False
    
    # Powyżej 1 minuty: Pokaż minuty i sekundy
    minutes = seconds // 60
    seconds_mod = seconds % 60
    
    # Formatowanie: 20 min 05 sek
    return f"⏱️ Pozostało: **{minutes} min {seconds_mod:02d} sek**", False

class CountdownManager:
    """Klasa zarządzająca pętlą aktualizującą timery zapisów Captures."""
    def __init__(self, client):
        self.client = client
        self.update_interval = 5 # Aktualizuj co 5 sekund
        self.is_running = False

    async def run_update_loop(self):
        await self.client.wait_until_ready()
        self.is_running = True
        print("CountdownManager uruchomiony.")
        while self.is_running:
            await self.update_all_captures()
            await asyncio.sleep(self.update_interval)

    async def update_all_captures(self):
        closed_captures = []
        
        # Iterujemy po kopii, by bezpiecznie modyfikować oryginalny słownik
        for msg_id, data in list(captures.items()):
            message = data.get("message")
            end_time = data.get("end_time")
            
            # Tylko zapisy z ustawionym czasem są aktualizowane przez managera
            if not message or not end_time:
                continue

            countdown_str, is_expired = format_countdown(end_time)
            
            try:
                # Tworzymy nową instancję widoku (dla odzyskania przycisków w przypadku błędu)
                view_instance = CapturesView(msg_id, data["author_name"])
                # Ustawiamy listę uczestników (konieczne, bo view jest nowy)
                view_instance.participants = data.get("participants", []) 
                new_embed = view_instance.make_embed(message.guild)
                
                if is_expired:
                    # Czas minął: usuń widok (przyciski)
                    await message.edit(embed=new_embed, view=None) 
                    closed_captures.append(msg_id)
                    print(f"Zapis Captures (ID: {msg_id}) zamknięty automatycznie.")
                else:
                    # Aktualizuj tylko embed (zachowaj przyciski)
                    await message.edit(embed=new_embed, view=view_instance)
            
            except discord.NotFound:
                # Wiadomość usunięta przez użytkownika, usuń z pamięci
                closed_captures.append(msg_id)
            except Exception as e:
                print(f"Błąd podczas aktualizacji Captures {msg_id}: {e}")
                
        # Czyszczenie pamięci
        for msg_id in closed_captures:
            captures.pop(msg_id, None)

# Inicjalizacja Managera
countdown_manager = CountdownManager(client)
# <<< KONIEC NARZĘDZI DO TIMERA >>>


# <<< ZARZĄDZANIE ZAPISAMI >>>
def get_all_active_enrollments():
# ... reszta funkcji get_all_active_enrollments
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
    # ... reszta klasy EnrollmentSelectMenu
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
    # ... reszta klasy AirdropView
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
        # ... reszta make_embed
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

    # ... reszta przycisków join i leave


class PlayerSelectMenu(ui.Select):
    # ... reszta klasy PlayerSelectMenu
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
    # ... reszta klasy PickPlayersView
    def __init__(self, capture_id: int):
        # ZMIANA: Dodanie custom_id
        super().__init__(timeout=180, custom_id=f"pick_players_view:{capture_id}")
        self.capture_id = capture_id

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
    def __init__(self, capture_id: int, author_name: str): 
        # ZMIANA: timeout=None dla trwałych widoków
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name
        # ZMIANA: Dodanie custom_id widoku, ważne do przywracania
        self.custom_id = f"captures_view:{capture_id}"

    def make_embed(self, guild: discord.Guild):
        participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        data = captures.get(self.capture_id, {})
        end_time = data.get("end_time") # POBIERAMY CZAS ZAKOŃCZENIA
        
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
            
        # ZMIANA: Dodajemy pole z timerem
        if end_time:
            countdown_str, is_expired = format_countdown(end_time)
            
            # Dodaj pole timera na sam koniec embeda
            embed.add_field(name="\u200b", value=countdown_str, inline=False) 
            
            # Jeśli czas minął, a interakcja jest nadal aktywna, wyłączamy przyciski
            if is_expired:
                # Zwróć None zamiast view (w praktyce robi to manager, ale to na wszelki wypadek)
                return embed, True # True oznacza, że zapis jest zamknięty

        embed.set_footer(text=f"Wystawione przez {self.author_name}")
        return embed

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green, custom_id="capt_join")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        # Sprawdzamy, czy czas nie minął przed defer
        data = captures.get(self.capture_id, {})
        end_time = data.get("end_time")
        if end_time and (end_time - datetime.now(POLAND_TZ)).total_seconds() <= 0:
            await interaction.response.send_message("❌ Zapisy zostały zamknięte, czas minął!", ephemeral=True)
            return
            
        user_id = interaction.user.id
        participants = data.get("participants", [])
        
        if user_id not in participants:
            # KLUCZOWA POPRAWKA: defer przy edycji głównej wiadomości, aby uniknąć 10062
            await interaction.response.defer() 
            
            # Używamy bezpiecznego dostępu
            if self.capture_id not in captures:
                 captures[self.capture_id] = {"participants": [], "author_name": self.author_name}
                 
            captures[self.capture_id]["participants"].append(user_id)
            
            # W make_embed zwracamy teraz krotkę (embed, is_expired)
            new_embed = self.make_embed(interaction.guild)
            
            # Tylko jeśli mamy embed (nie jest zamknięty)
            if isinstance(new_embed, discord.Embed):
                await interaction.message.edit(embed=new_embed, view=self)
            
            await interaction.followup.send("Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red, custom_id="capt_leave")
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        # Sprawdzamy, czy czas nie minął przed defer
        data = captures.get(self.capture_id, {})
        end_time = data.get("end_time")
        if end_time and (end_time - datetime.now(POLAND_TZ)).total_seconds() <= 0:
            await interaction.response.send_message("❌ Zapisy zostały zamknięte, czas minął!", ephemeral=True)
            return

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
            
            # W make_embed zwracamy teraz krotkę (embed, is_expired)
            new_embed = self.make_embed(interaction.guild)

            # Tylko jeśli mamy embed (nie jest zamknięty)
            if isinstance(new_embed, discord.Embed):
                await interaction.message.edit(embed=new_embed, view=self)

            await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

    # ZMIANA: Dodanie custom_id do przycisku
    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple, custom_id="capt_pick")
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        # ... reszta metody pick_button (nie zmieniona poza timer check)
        # Defer, bo wysłanie nowego view zajmuje czas
        await interaction.response.defer(ephemeral=True)
        
        if PICK_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
            return
            
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if not participants:
            await interaction.followup.send("Nikt się nie zapisał!", ephemeral=True)
            return
            
        pick_view = PickPlayersView(self.capture_id)
        pick_view.add_item(PlayerSelectMenu(self.capture_id, interaction.guild))
        
        await interaction.followup.send("Wybierz do 25 graczy:", view=pick_view, ephemeral=True)


# ... reszta klas SquadView, EditSquadView itp. (bez zmian)
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
        
    # POPRAWKA KOLORU: używamy 0xFFFFFF (biały) - rozwiązuje błąd Colour.white
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
    # ZMIANA: Uruchomienie managera timera
    client.loop.create_task(countdown_manager.run_update_loop())
    
    # Przywracanie widoków
    
    # 1. SQUAD VIEWS
    if squads:
        print(f"Próba przywrócenia {len(squads)} widoków Squad.")
        for msg_id, data in squads.items():
             try:
                 # Ważne: musimy ustawić message obiekt, aby móc edytować
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     data["message"] = await channel.fetch_message(msg_id)
                     # ZMIANA: Dodajemy widok
                     client.add_view(SquadView(msg_id, data["role_id"]))
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
                     # ZMIANA: Dodajemy widok CapturesView
                     client.add_view(CapturesView(msg_id, data["author_name"]))
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
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku AirDrop {msg_id}: {e}")
                 
    # Synchronizacja komend
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Komenda SQUAD
@tree.command(name="create-squad", description="Tworzy ogłoszenie o składzie z możliwością edycji.")
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
async def create_squad(interaction: discord.Interaction, rola: discord.Role, tytul: str = "Main Squad"):
    # ... reszta komendy create-squad
    await interaction.response.defer(ephemeral=True) 

    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do tworzenia squadu! (Wymagany Admin)", ephemeral=True)
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


# Captures
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures z timerem, który automatycznie aktualizuje czas.")
@app_commands.describe(czas_minut="Czas trwania zapisu w minutach (np. 20). Min: 1, Max: 360 (6h)")
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
async def create_capt(interaction: discord.Interaction, czas_minut: app_commands.Range[int, 1, 360]):
    # KLUCZOWA POPRAWKA: Defer
    await interaction.response.defer(ephemeral=True) 
    
    # 1. Oblicz czas zakończenia
    end_time = datetime.now(POLAND_TZ) + timedelta(minutes=czas_minut)
    
    author_name = interaction.user.display_name
    # Ważne: message_id=0 zostanie ustawione później na sent.id
    view = CapturesView(0, author_name) 
    
    # Tymczasowe dane do utworzenia pierwszego embeda
    temp_data = {"participants": [], "author_name": author_name, "end_time": end_time}
    
    # Używamy make_embed z CapturesView, ale w celu uzyskania samego embeda musimy przekazać obiekt data
    embed = view.make_embed(interaction.guild)
    
    # Jeśli make_embed zwrócił Embed (co powinno się zdarzyć)
    if isinstance(embed, discord.Embed):
        sent = await interaction.channel.send(content="@everyone", embed=embed, view=view)
    else:
        # Ten warunek jest potrzebny, bo make_embed zwraca krotkę w nowym kodzie.
        # W tej chwili wiemy, że czas jeszcze nie minął, więc bezpiecznie używamy elementu 0
        sent = await interaction.channel.send(content="@everyone", embed=embed[0], view=view)
    
    # 2. Zapisz wszystkie dane, w tym message i end_time
    captures[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "author_name": author_name,
        "end_time": end_time # ZAPISANY CZAS KOŃCA!
    }
    
    # Aktualizacja View z poprawnym ID wiadomości i custom_id
    view.capture_id = sent.id 
    view.custom_id = f"captures_view:{sent.id}"
    await sent.edit(view=view) 
    
    await interaction.followup.send(f"Ogłoszenie o captures na **{czas_minut} minut** wysłane!", ephemeral=True)

# AirDrop
# ZMIANA: Na razie nie dodajemy timera do AirDrop, by nie komplikować zbyt wielu rzeczy naraz
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie")
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
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
# ... reszta komend (bez zmian)
@tree.command(name="ping-zancudo", description="Wysyła ogłoszenie o ataku na Fort Zancudo.")
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
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
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
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
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
async def list_all(interaction: discord.Interaction):
    # ... reszta komendy list-all

# Set status
@tree.command(name="set-status", description="Zmienia status i aktywność bota (tylko admini)")
async def set_status(interaction: discord.Interaction, status: str, opis_aktywnosci: str = None, typ_aktywnosci: str = None, url_stream: str = None):
    # ... reszta komendy set-status

# Wypisz z capt
class RemoveEnrollmentView(ui.View):
    # ... reszta klasy RemoveEnrollmentView

@tree.command(name="wypisz-z-capt", description="Wypisuje użytkownika z dowolnego aktywnego zapisu (Captures, AirDrop, Event).")
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
async def remove_from_enrollment(interaction: discord.Interaction, członek: discord.Member):
    # ... reszta komendy remove_from_enrollment

# Wpisz na capt
class AddEnrollmentView(ui.View):
    # ... reszta klasy AddEnrollmentView

@tree.command(name="wpisz-na-capt", description="Wpisuje użytkownika na dowolny aktywny zapis (Captures, AirDrop, Event).")
@is_allowed_role() # DODANO: Sprawdzenie wymaganej roli
async def add_to_enrollment(interaction: discord.Interaction, członek: discord.Member):
    # ... reszta komendy add_to_enrollment


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
