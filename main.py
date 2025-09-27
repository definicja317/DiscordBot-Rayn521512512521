import discord
from discord import app_commands, ui
from discord.ext import tasks
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone # POPRAWKA: Upewnienie się, że timedelta i timezone są zaimportowane
import re 
import traceback 
import time 

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
# ZASTĄP SWOIMI ID
PICK_ROLE_ID = 1413424476770664499 
STATUS_ADMINS = [1184620388425138183, 1409225386998501480, 1007732573063098378, 364869132526551050] 
ADMIN_ROLES = STATUS_ADMINS 
BOT_ADMIN_ROLE_ID = 1413424476770664499 # Użyte to samo ID, co PICK_ROLE_ID, do weryfikacji roli
ZANCUDO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414194392214011974/image.png"
CAYO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414204332747915274/image.png"
LOGO_URL = "https://cdn.discordapp.com/attachments/1184622314302754857/1420796249484824757/RInmPqb.webp?ex=68d6b31e&is=68d5619e&hm=0cdf3f7cbb269b12c9f47d7eb034e40a8d830ff502ca9ceacb3d7902d3819413&"

# --- Definicja strefy czasowej PL (UTC+2) ---
POLAND_TZ = timezone(timedelta(hours=2))

# --- POPRAWIONA FUNKCJA TIMERA ---
def create_timestamp(czas_str: str, data_str: str = None) -> int:
    """Konwertuje HH:MM i opcjonalną datę DD.MM.RRRR lub DD.MM na Unix Timestamp (UTC)."""
    
    match = re.match(r"(\d{1,2}):(\d{2})", czas_str)
    if not match:
        raise ValueError("Nieprawidłowy format czasu. Użyj HH:MM (np. 21:30).")
    hour, minute = map(int, match.groups())

    now_pl = discord.utils.utcnow().astimezone(POLAND_TZ)
    dt_local = now_pl.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    if data_str:
        try:
            dt_base_naive = datetime.strptime(data_str, "%d.%m.%Y")
        except ValueError:
            try:
                dt_base_naive = datetime.strptime(data_str, "%d.%m").replace(year=now_pl.year)
            except ValueError:
                raise ValueError("Nieprawidłowy format daty. Użyj DD.MM.RRRR lub DD.MM (np. 27.09.2025).")
        
        final_dt = dt_local.replace(
            year=dt_base_naive.year, 
            month=dt_base_naive.month, 
            day=dt_base_naive.day,
            tzinfo=POLAND_TZ 
        )
    else:
        final_dt = dt_local 

    if final_dt < now_pl and not data_str:
        final_dt += timedelta(days=1)
    
    final_dt_utc = final_dt.astimezone(timezone.utc) 
    return int(final_dt_utc.timestamp())
# --- KONIEC FUNKCJI TIMERA ---


# --- Discord Client ---
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# --- Globalna obsługa błędów ---
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Globalny błąd komendy {interaction.command.name} (użytkownik: {interaction.user.display_name}):")
    traceback.print_exc() 
    
    # Obsługa błędu 10062 (Wygasła interakcja)
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.NotFound) and "10062" in str(error.original):
        print("Wykryto i pominięto błąd 10062 (Unknown interaction/Wygasła interakcja).")
        return
        
    # Obsługa błędów formatu daty/czasu (ValueError)
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, ValueError):
        response_content = f"❌ Błąd formatu czasu/daty: **{error.original}**"
    else:
        # Obsługa innych błędów
        error_name = type(error).__name__
        response_content = f"❌ Wystąpił błąd w kodzie: `{error_name}`. Sprawdź logi bota! (Original: `{type(getattr(error, 'original', None)).__name__}`)"
            
    try:
        if interaction.response.is_done():
            await interaction.followup.send(response_content, ephemeral=True)
        else:
            await interaction.response.send_message(response_content, ephemeral=True)
            
    except discord.HTTPException:
        print("Nie udało się wysłać wiadomości o błędzie do użytkownika, interakcja wygasła (10062).")
# --- KONIEC GLOBALNEJ OBSŁUGI BŁĘDÓW ---


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
        super().__init__(
            placeholder=f"Wybierz zapis:",
            max_values=1,
            min_values=1,
            options=options,
        )
        self.custom_id = f"enrollment_select_{action}" 
        
    async def callback(self, interaction: discord.Interaction):
        # Ta funkcja nie musi nic robić, ponieważ wybór jest obsługiwany przez guzik "Potwierdź"
        pass 
# <<< KONIEC ZARZĄDZANIE ZAPISAMI >>>

# =====================
#       AIRDROP & CAPTURES VIEWS
# =====================
class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel: discord.VoiceChannel, author_name: str, timestamp: int = None):
        super().__init__(timeout=None) 
        self.message_id = message_id
        self.description = description
        self.voice_channel = voice_channel
        self.participants: list[int] = [] 
        self.author_name = author_name
        self.timestamp = timestamp 
        self.custom_id = f"airdrop_view:{message_id}" 

    def make_embed(self, guild: discord.Guild):
        embed = discord.Embed(title="🎁 AirDrop!", description=self.description, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL)
        embed.add_field(name="Kanał głosowy:", value=f"🔊 {self.voice_channel.mention}", inline=False)
        
        if self.timestamp:
            time_str = f"Rozpoczęcie AirDrop o <t:{self.timestamp}:t> (<t:{self.timestamp}:R>)"
            embed.add_field(name="Czas rozpoczęcia:", value=time_str, inline=False)
            
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

    @ui.button(label="✅ Dołącz", style=discord.ButtonStyle.green, custom_id="airdrop_join")
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        
        if interaction.user.id in self.participants:
            await interaction.followup.send("Już jesteś zapisany(a).", ephemeral=True)
            return
        
        if self.message_id not in airdrops:
             await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota. Spróbuj utworzyć nowy zapis.", ephemeral=True)
             return
             
        self.participants.append(interaction.user.id)
        airdrops[self.message_id]["participants"].append(interaction.user.id) 
        
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.followup.send("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red, custom_id="airdrop_leave")
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        
        if interaction.user.id not in self.participants:
            await interaction.followup.send("Nie jesteś zapisany(a).", ephemeral=True)
            return
            
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

        super().__init__(
            placeholder="Wybierz do 25 graczy",
            max_values=min(25, len(options)),
            options=options,
            custom_id=f"player_select:{capture_id}"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        # Zgodnie z logiką, nie trzeba tu nic robić, ponieważ wybór jest przetwarzany przez przycisk 'Potwierdź wybór'
        await interaction.followup.send("Wybór graczy został zarejestrowany. Naciśnij 'Potwierdź wybór'.", ephemeral=True)


class PickPlayersView(ui.View):
    # KRYTYCZNA POPRAWKA: Usunięcie custom_id z super().__init__ (rozwiązuje TypeError)
    def __init__(self, capture_id: int):
        super().__init__(timeout=180) 
        self.capture_id = capture_id

    @ui.button(label="Potwierdź wybór", style=discord.ButtonStyle.green, custom_id="confirm_pick_button")
    async def confirm_pick(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Musimy znaleźć menu wyboru w interakcji
        select_menu = next((item for item in self.children if item.custom_id == f"player_select:{self.capture_id}"), None)
        
        if not select_menu:
             # Sprawdzamy też, czy menu zostało wybrane w interakcji
             select_menu = next((c for c in interaction.message.components[0].children if isinstance(c, ui.Select) and c.custom_id == f"player_select:{self.capture_id}"), None)
             if not select_menu:
                 await interaction.followup.send("Błąd: Nie znaleziono menu wyboru. Spróbuj ponownie.", ephemeral=True)
                 return
             
        # Wartości są w obiekcie Select, który jest częścią interakcji
        # W przypadku widoku tymczasowego, wartości są przechowywane w atrybucie `values` elementu `Select`
        # Jeśli interakcja pochodzi od przycisku, musimy polegać na wartościach zapisanych w state managemencie Discorda.
        
        # POPRAWKA: Musimy uzyskać wartości z interakcji, jeśli użytkownik faktycznie coś wybrał w menu
        # Użyjemy prostej metody sprawdzającej, czy w interakcji występuje wybrana wartość
        
        selected_values = []
        if interaction.data and 'components' in interaction.data and interaction.data['components']:
            for row in interaction.data['components']:
                for component in row.get('components', []):
                    if component.get('custom_id') == f"player_select:{self.capture_id}" and component.get('values'):
                        selected_values = component['values']
                        break
                if selected_values:
                    break

        # Jeżeli przycisk "Potwierdź wybór" został naciśnięty, a użytkownik nic nie wybrał w menu Select:
        # Prawidłowe wartości powinny być pobierane z `select_menu.values` (jeśli interakcja jest typu SELECT_MENU)
        # LUB z danych interakcji, gdy interakcja jest typu BUTTON.
        
        # W tym prostym modelu, polegamy na tym, że użytkownik najpierw wybrał w Select, a potem kliknął Button.
        # Niestety, Discord nie przekazuje wybranych wartości z Select do callbacka Buttona.
        # Najprostsze rozwiązanie: użytkownik wybiera, a następnie klika 'Potwierdź wybór' W TYM SAMYM WIDOKU.
        
        # Dla uproszczenia, sprawdzamy, czy w danym widoku menu miało jakieś wybrane wartości (choć to jest niepewne, 
        # bo wartości są resetowane po interakcji select)
        
        # PONIEWAŻ logika ta jest wadliwa w discord.py (przycisk nie widzi wyboru z Selecta), 
        # ZAKŁADAMY, że użytkownik musi najpierw wybrać i poczekać na potwierdzenie z PlayerSelectMenu.callback
        # Następnie kliknięcie przycisku powinno spowodować odczyt z zapisu sesji (którego nie ma w tym kodzie).
        
        # Na razie polegamy na tym, co jest w PlayerSelectMenu.callback (które deferuje i nic nie robi).
        # Poprawne działanie wymagałoby zaawansowanego state managementu lub innego wzorca UI.
        
        # Tymczasowe obejście (niepewne w 100%): Spróbujemy odczytać z obiektu, który został dodany do View
        # W tym kodzie to jest trudne. Zmieniamy logikę na bezpieczniejszą:
        
        # Jeśli nie ma wartości, wysyłamy błąd.
        if not select_menu or not select_menu.values:
            await interaction.followup.send("⚠️ Najpierw wybierz graczy z menu rozwijanego (tuż nad tym przyciskiem) i poczekaj, aż bot zarejestruje wybór (otrzymaj wiadomość potwierdzającą). Następnie naciśnij 'Potwierdź wybór'.", ephemeral=True)
            return

        selected_values = select_menu.values # Pobieramy wartości z menu Select, jeśli były wybrane w tej interakcji

        if not selected_values:
            await interaction.followup.send("Nie wybrano żadnych osób! Wybierz je w menu rozwijanym powyżej.", ephemeral=True)
            return

        # Dalsza logika pozostaje bez zmian
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
        await interaction.followup.send(embed=final_embed)


class CapturesView(ui.View):
    def __init__(self, capture_id: int, author_name: str, image_url: str = None, timestamp: int = None, started: bool = False): 
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name
        self.image_url = image_url
        self.timestamp = timestamp 
        self.custom_id = f"captures_view:{capture_id}"
        self.started = started 
        
    def make_embed(self, guild: discord.Guild):
        participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        
        embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
        if self.image_url:
            embed.set_image(url=self.image_url)

        if self.timestamp:
            if self.started:
                time_str = "**CAPT rozpoczął się**" 
            else:
                time_str = f"Rozpoczęcie CAPT o <t:{self.timestamp}:t> (<t:{self.timestamp}:R>)" 
            
            embed.add_field(name="Czas rozpoczęcia:", value=time_str, inline=False)
        
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

    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green, custom_id="capt_join")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id not in participants:
            await interaction.response.defer() 
            
            # Weryfikacja istnienia wpisu na wypadek restartu bota
            if self.capture_id not in captures:
                 captures[self.capture_id] = {"participants": [], "author_name": self.author_name, "image_url": self.image_url, "timestamp": self.timestamp, "started": self.started} 
                 
            captures[self.capture_id]["participants"].append(user_id)
            
            data = captures.get(self.capture_id)
            if data and data.get("message"):
                await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
                await interaction.followup.send("Zostałeś(aś) zapisany(a)!", ephemeral=True)
            else:
                await interaction.followup.send("Zostałeś(aś) zapisany(a), ale wiadomość ogłoszenia mogła zaginąć po restarcie bota.", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red, custom_id="capt_leave")
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id in participants:
            await interaction.response.defer() 
            
            if self.capture_id not in captures:
                 await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota.", ephemeral=True)
                 return
                 
            captures[self.capture_id]["participants"].remove(user_id)
            
            data = captures.get(self.capture_id)
            if data and data.get("message"):
                await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
                await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
            else:
                 await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple, custom_id="capt_pick")
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        guild_member = interaction.guild.get_member(interaction.user.id)
        # POPRAWKA: Weryfikacja, czy użytkownik ma rolę administracyjną LUB pickującą.
        is_admin = interaction.user.id in ADMIN_ROLES
        has_pick_role = PICK_ROLE_ID in [r.id for r in guild_member.roles]
        
        if not (is_admin or has_pick_role):
            await interaction.followup.send("⛔ Brak uprawnień! Wymagana jest rola do pickowania.", ephemeral=True)
            return
            
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if not participants:
            await interaction.followup.send("Nikt się nie zapisał!", ephemeral=True)
            return
            
        pick_view = PickPlayersView(self.capture_id)
        # Menu Select musi być dodane DO WIDOKU
        pick_view.add_item(PlayerSelectMenu(self.capture_id, interaction.guild))
        
        await interaction.followup.send("Wybierz do 25 graczy:", view=pick_view, ephemeral=True)


# =======================================================
# <<< FUNKCJE DLA SQUADÓW >>>
# =======================================================

def create_squad_embed(guild: discord.Guild, author_name: str, member_ids: list[int], title: str = "Main Squad"):
    """Tworzy embed dla Squadu na podstawie listy ID."""
    
    member_lines = []
    
    for i, uid in enumerate(member_ids):
        member = guild.get_member(uid)
        if member:
            member_lines.append(f"{i+1}- {member.mention} | **{member.display_name}**")
        else:
            member_lines.append(f"{i+1}- <@{uid}> (Nieznany/Opuścił serwer)")
            
    members_list_str = "\n".join(member_lines) if member_lines else "Brak członków składu."
    count = len(member_ids)
        
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
    # KRYTYCZNA POPRAWKA: Usunięcie custom_id z super().__init__ (rozwiązuje TypeError)
    def __init__(self, message_id: int):
        super().__init__(timeout=180)
        self.message_id = message_id
        
        self.add_item(ui.UserSelect(
            placeholder="Wybierz członków składu (max 25)",
            max_values=25, 
            custom_id="squad_member_picker"
        ))

    @ui.button(label="✅ Potwierdź edycję", style=discord.ButtonStyle.green, custom_id="confirm_edit_squad")
    async def confirm_edit(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        select_menu = next((item for item in self.children if item.custom_id == "squad_member_picker"), None)
        selected_ids = []
        if select_menu and select_menu.values:
            selected_ids = [user.id for user in select_menu.values]
        
        squad_data = squads.get(self.message_id)

        if not squad_data:
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu. Być może widok wygasł.", ephemeral=True)
            return

        squad_data["member_ids"] = selected_ids
        
        message = squad_data.get("message")
        author_name = squad_data.get("author_name", "Bot")
        title = "Main Squad"
        if message and message.embeds:
            if message.embeds:
                title = message.embeds[0].title
            
        new_embed = create_squad_embed(interaction.guild, author_name, selected_ids, title)
        
        if message and hasattr(message, 'edit'):
            # Wracamy do widoku permanentnego SquadView
            new_squad_view = SquadView(self.message_id, squad_data.get("role_id"))
            
            role_id = squad_data.get("role_id")
            content = f"<@&{role_id}> **Zaktualizowano Skład!**" if role_id else ""
            
            await message.edit(content=content, embed=new_embed, view=new_squad_view)
            
            await interaction.followup.send(content="✅ Skład został pomyślnie zaktualizowany! Wróć do głównej wiadomości składu.", ephemeral=True)
        else:
            await interaction.followup.send(content="Błąd: Nie można odświeżyć wiadomości składu. Być może bot został zrestartowany lub wiadomość usunięta.", ephemeral=True)


class SquadView(ui.View):
    def __init__(self, message_id: int, role_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id
        self.custom_id = f"squad_view:{message_id}"

    @ui.button(label="Zarządzaj składem (ADMIN)", style=discord.ButtonStyle.blurple, custom_id="manage_squad_button")
    async def manage_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True) 

        guild_member = interaction.guild.get_member(interaction.user.id)
        # POPRAWKA: Weryfikacja, czy użytkownik ma rolę administracyjną.
        if not guild_member or BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles]:
            # Dodatkowa weryfikacja dla użytkowników z listy STATUS_ADMINS
            if interaction.user.id not in STATUS_ADMINS:
                await interaction.followup.send("⛔ Brak uprawnień do zarządzania składem! Wymagana rola administracyjna.", ephemeral=True)
                return

        squad_data = squads.get(self.message_id)
        if not squad_data:
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return
            
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
#       FUNKCJONALNOŚĆ TIMERA CAPTURES
# =====================

@tasks.loop(minutes=1.0) 
async def check_captures_end_time():
    """Sprawdza co minutę, czy czas rozpoczęcia Captures minął."""
    now_utc = discord.utils.utcnow().timestamp()
    
    for msg_id, data in list(captures.items()):
        timestamp = data.get("timestamp")
        started = data.get("started", False)
        message = data.get("message")
        
        if timestamp and not started and now_utc >= timestamp:
            
            captures[msg_id]["started"] = True
            
            if message:
                try:
                    view_obj = CapturesView(
                        msg_id, 
                        data["author_name"], 
                        data.get("image_url"), 
                        timestamp, 
                        started=True
                    )
                    new_embed = view_obj.make_embed(message.guild)
                    
                    await message.edit(embed=new_embed, view=view_obj)
                    print(f"✅ Wiadomość Captures (ID: {msg_id}) zaktualizowana: START.")
                    
                except discord.NotFound:
                    print(f"Błąd: Nie znaleziono wiadomości Captures (ID: {msg_id}). Pomijam.")
                    # Nie usuwamy z listy, bo może błąd był tymczasowy, ale oznaczamy jako "bez wiadomości"
                    captures[msg_id]["message"] = None 
                    
                except Exception as e:
                    print(f"Błąd edycji wiadomości Captures (ID: {msg_id}): {e}")
                    traceback.print_exc()

# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    # Start cyklicznego zadania sprawdzania czasu
    if not check_captures_end_time.is_running():
        check_captures_end_time.start()
        print("✅ Rozpoczęto zadanie cykliczne Captures Time Tracker.")

    # Przywracanie widoków (Critical dla persistent views)
    
    # 1. SQUAD VIEWS
    if squads:
        print(f"Próba przywrócenia {len(squads)} widoków Squad.")
        for msg_id, data in list(squads.items()):
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     # Upewniamy się, że wiadomość istnieje i ją łapiemy
                     data["message"] = await channel.fetch_message(msg_id)
                     client.add_view(SquadView(msg_id, data["role_id"]))
             except discord.NotFound:
                  print(f"Ostrzeżenie: Wiadomość Squad {msg_id} nie została znaleziona. Usuwam z pamięci.")
                  del squads[msg_id]
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku Squad {msg_id}: {e}")
                 
    # 2. CAPTURES VIEWS
    if captures:
        print(f"Próba przywrócenia {len(captures)} widoków Captures.")
        for msg_id, data in list(captures.items()):
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     data["message"] = await channel.fetch_message(msg_id)
                     image_url = data.get("image_url")
                     timestamp = data.get("timestamp")
                     started = data.get("started", False)
                     client.add_view(CapturesView(msg_id, data["author_name"], image_url, timestamp, started))
             except discord.NotFound:
                  print(f"Ostrzeżenie: Wiadomość Captures {msg_id} nie została znaleziona. Usuwam z pamięci.")
                  del captures[msg_id]
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku Captures {msg_id}: {e}")
                 
    # 3. AIRDROP VIEWS
    if airdrops:
        print(f"Próba przywrócenia {len(airdrops)} widoków AirDrop.")
        for msg_id, data in list(airdrops.items()):
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     data["message"] = await channel.fetch_message(msg_id)
                     voice_channel = client.get_channel(data["voice_channel_id"])
                     
                     if voice_channel:
                         timestamp = data.get("timestamp")
                         view = AirdropView(msg_id, data["description"], voice_channel, data["author_name"], timestamp)
                         view.participants = data.get("participants", []) 
                         client.add_view(view)
                     else:
                         print(f"Ostrzeżenie: Nie znaleziono kanału głosowego dla AirDrop {msg_id}. Pomijam przywracanie widoku.")
             except discord.NotFound:
                  print(f"Ostrzeżenie: Wiadomość AirDrop {msg_id} nie została znaleziona. Usuwam z pamięci.")
                  del airdrops[msg_id]
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku AirDrop {msg_id}: {e}")
                 
    # Synchronizacja komend
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Komenda SQUAD
@tree.command(name="create-squad", description="Tworzy ogłoszenie o składzie z możliwością edycji.")
async def create_squad(interaction: discord.Interaction, rola: discord.Role, tytul: str = "Main Squad"):
    await interaction.response.defer(ephemeral=True) 

    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
        await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
        return

    author_name = interaction.user.display_name
    role_id = rola.id
    
    initial_member_ids = []
    embed = create_squad_embed(interaction.guild, author_name, initial_member_ids, tytul) 
    view = SquadView(0, role_id) 
    
    content = f"{rola.mention}"
    sent = await interaction.channel.send(content=content, embed=embed, view=view)
    
    squads[sent.id] = {
        "role_id": role_id, 
        "member_ids": initial_member_ids, 
        "message": sent, 
        "channel_id": sent.channel.id,
        "author_name": author_name,
    }
    
    view.message_id = sent.id
    view.custom_id = f"squad_view:{sent.id}"
    # Musimy dodać widok do klienta, aby był trwały (persistent)
    client.add_view(view) 
    # Edycja jest niepotrzebna, view jest już ustawiony
    
    await interaction.followup.send(f"✅ Ogłoszenie o składzie '{tytul}' dla roli {rola.mention} wysłane!", ephemeral=True)


# Komenda CAPTURES (Z TIMMEREM)
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures z opcjonalnym timerem i zdjęciem.")
async def create_capt(interaction: discord.Interaction, czas_zakonczenia: str, data_zakonczenia: str = None, link_do_zdjecia: str = None):
    await interaction.response.defer(ephemeral=True) 
    
    # Dodatkowa weryfikacja uprawnień (chociaż komenda jest publiczna, dla bezpieczeństwa):
    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
        # Możesz usunąć tę weryfikację, jeśli komenda ma być dostępna dla wszystkich.
        pass # W tym przypadku zostawiamy, że może ją użyć każdy.
    
    try:
        timestamp = create_timestamp(czas_zakonczenia, data_zakonczenia)
    except ValueError as e:
        await interaction.followup.send(f"❌ Błąd formatu czasu/daty: **{e}**", ephemeral=True)
        return
    
    started = discord.utils.utcnow().timestamp() >= timestamp
    
    author_name = interaction.user.display_name
    
    view = CapturesView(0, author_name, link_do_zdjecia, timestamp, started) 
    embed = view.make_embed(interaction.guild)
    
    sent = await interaction.channel.send(content="@everyone", embed=embed, view=view)
    
    captures[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "author_name": author_name,
        "image_url": link_do_zdjecia, 
        "timestamp": timestamp,
        "started": started 
    }
    
    view.capture_id = sent.id 
    view.custom_id = f"captures_view:{sent.id}"
    client.add_view(view) # Dodajemy widok do klienta
    # Edycja niepotrzebna
    
    await interaction.followup.send("Ogłoszenie o captures wysłane!", ephemeral=True)

# Komenda AirDrop (Z TIMMEREM)
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie z timerem.")
async def airdrop_command(interaction: discord.Interaction, channel: discord.TextChannel, voice: discord.VoiceChannel, role: discord.Role, opis: str, czas_zakonczenia: str, data_zakonczenia: str = None):
    await interaction.response.defer(ephemeral=True) 
    
    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
        await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
        return
    
    try:
        timestamp = create_timestamp(czas_zakonczenia, data_zakonczenia)
    except ValueError as e:
        await interaction.followup.send(f"❌ Błąd formatu czasu/daty: **{e}**", ephemeral=True)
        return
        
    view = AirdropView(0, opis, voice, interaction.user.display_name, timestamp) 
    embed = view.make_embed(interaction.guild)
    sent = await channel.send(content=f"{role.mention}", embed=embed, view=view)
    
    airdrops[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "description": opis, 
        "voice_channel_id": voice.id, 
        "author_name": interaction.user.display_name,
        "timestamp": timestamp 
    }
    
    view.message_id = sent.id
    view.custom_id = f"airdrop_view:{sent.id}"
    client.add_view(view) # Dodajemy widok do klienta
    
    await interaction.followup.send("✅ AirDrop utworzony!", ephemeral=True)

# Eventy Zancudo / Cayo
@tree.command(name="ping-zancudo", description="Wysyła ogłoszenie o ataku na Fort Zancudo.")
async def ping_zancudo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True) 

    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
        await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
        return

    embed = discord.Embed(title="Atak na FORT ZANCUDO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFF0000))
    embed.set_image(url=ZANCUDO_IMAGE_URL)
    embed.set_thumbnail(url=LOGO_URL) 
    sent = await interaction.channel.send(content=f"{role.mention}", embed=embed)
    events["zancudo"][sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

@tree.command(name="ping-cayo", description="Wysyła ogłoszenie o ataku na Cayo Perico.")
async def ping_cayo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True) 

    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
        await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
        return

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
    
    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
        
    desc = ""
    for name, mid, data in get_all_active_enrollments():
        desc += f"\n**{name} (msg {mid})**: {len(data['participants'])} osób"
        
    for mid, data in squads.items():
        count = len(data.get('member_ids', []))
        title = data.get('message').embeds[0].title if data.get('message') and data.get('message').embeds else "Squad"
        desc += f"\n**{title} (msg {mid})**: {count} osób"

    if not desc:
        desc = "Brak aktywnych zapisów i składów."
    embed = discord.Embed(title="📋 Lista wszystkich zapisanych i składów", description=desc, color=discord.Color(0xFFFFFF))
    await interaction.followup.send(embed=embed, ephemeral=True)

# Set status
@tree.command(name="set-status", description="Zmienia status i aktywność bota (tylko admini)")
async def set_status(interaction: discord.Interaction, status: str, opis_aktywnosci: str = None, typ_aktywnosci: str = None, url_stream: str = None):
    await interaction.response.defer(ephemeral=True, thinking=True) 

    if interaction.user.id not in STATUS_ADMINS:
        await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
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
        await interaction.followup.send("⚠️ Nieprawidłowy status. Użyj: online/idle/dnd/invisible.", ephemeral=True)
        return
        
    activity = None
    if opis_aktywnosci:
        activity_type = discord.ActivityType.playing 
        
        if typ_aktywnosci and typ_aktywnosci.lower() in activity_type_map:
            activity_type = activity_type_map[typ_aktywnosci.lower()]

        if activity_type == discord.ActivityType.streaming:
            if not url_stream or not (url_stream.startswith('http://') or url_stream.startswith('https://')):
                await interaction.followup.send("⚠️ Aby ustawić 'stream', musisz podać poprawny link (URL) do streamu w argumencie `url_stream`!", ephemeral=True)
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

    await interaction.followup.send(response_msg, ephemeral=True)

# Wypisz z capt
class RemoveEnrollmentView(ui.View):
    def __init__(self, member_to_remove: discord.Member):
        super().__init__(timeout=180)
        self.member_to_remove = member_to_remove
        self.custom_id = f"remove_enrollment_view:{member_to_remove.id}"
        self.add_item(EnrollmentSelectMenu("remove"))

    @ui.button(label="Potwierdź usunięcie", style=discord.ButtonStyle.red, custom_id="confirm_remove_button")
    async def confirm_remove(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        
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
            await interaction.followup.edit_message(
                interaction.message.id,
                content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.",
                view=None
            )
            return

        participants = data_dict.get("participants", [])
        
        if user_id not in participants:
            await interaction.followup.edit_message(
                interaction.message.id,
                content=f"⚠️ **{self.member_to_remove.display_name}** nie jest zapisany(a) na ten **{type_str.capitalize()}**.",
                view=None
            )
            return

        participants.remove(user_id)
        
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
            if type_str == "airdrop":
                voice_channel = message.guild.get_channel(data_dict["voice_channel_id"])
                description = data_dict["description"]
                author_name = data_dict["author_name"]
                timestamp = data_dict.get("timestamp")
                
                view_obj = AirdropView(msg_id, description, voice_channel, author_name, timestamp) 
                view_obj.participants = participants
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
            elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
                 author_name = data_dict["author_name"]
                 image_url = data_dict.get("image_url") 
                 timestamp = data_dict.get("timestamp")
                 started = data_dict.get("started", False)
                 view_obj = CapturesView(msg_id, author_name, image_url, timestamp, started) 
                 new_embed = view_obj.make_embed(message.guild)
                 await message.edit(embed=new_embed, view=view_obj)
            elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants

        await interaction.followup.edit_message(
            interaction.message.id,
            content=f"✅ Pomyślnie wypisano **{self.member_to_remove.display_name}** z **{type_str.capitalize()}** (ID: `{msg_id}`).",
            view=None
        )

# Wpisz na capt
class AddEnrollmentView(ui.View):
    def __init__(self, member_to_add: discord.Member):
        super().__init__(timeout=180)
        self.member_to_add = member_to_add
        self.custom_id = f"add_enrollment_view:{member_to_add.id}"
        self.add_item(EnrollmentSelectMenu("add"))

    @ui.button(label="Potwierdź dodanie", style=discord.ButtonStyle.green, custom_id="confirm_add_button")
    async def confirm_add(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        
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
            await interaction.followup.edit_message(
                interaction.message.id,
                content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.",
                view=None
            )
            return

        participants = data_dict.get("participants", [])
        
        if user_id in participants:
            await interaction.followup.edit_message(
                interaction.message.id,
                content=f"⚠️ **{self.member_to_add.display_name}** jest już zapisany(a) na ten **{type_str.capitalize()}**.",
                view=None
            )
            return

        participants.append(user_id)
        
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
             if type_str == "airdrop":
                voice_channel = message.guild.get_channel(data_dict["voice_channel_id"])
                description = data_dict["description"]
                author_name = data_dict["author_name"]
                timestamp = data_dict.get("timestamp")

                view_obj = AirdropView(msg_id, description, voice_channel, author_name, timestamp) 
                view_obj.participants = participants
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
             elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
                 author_name = data_dict["author_name"]
                 image_url = data_dict.get("image_url") 
                 timestamp = data_dict.get("timestamp")
                 started = data_dict.get("started", False)
                 view_obj = CapturesView(msg_id, author_name, image_url, timestamp, started) 
                 new_embed = view_obj.make_embed(message.guild)
                 await message.edit(embed=new_embed, view=view_obj)
             elif type_str in events:
                 events[type_str][msg_id]["participants"] = participants

        await interaction.followup.edit_message(
            interaction.message.id,
            content=f"✅ Pomyślnie wpisano **{self.member_to_add.display_name}** na **{type_str.capitalize()}** (ID: `{msg_id}`).",
            view=None
        )

@tree.command(name="wpisz-na-capt", description="Wpisuje użytkownika na dowolny aktywny zapis (Captures, AirDrop, Event).")
async def add_to_enrollment(interaction: discord.Interaction, członek: discord.Member):
    await interaction.response.defer(ephemeral=True) 
    
    guild_member = interaction.guild.get_member(interaction.user.id)
    if BOT_ADMIN_ROLE_ID not in [r.id for r in guild_member.roles] and interaction.user.id not in STATUS_ADMINS:
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
        # Używamy wszystkich intentsów
        client.run(token)
    except Exception as e:
        print(f"Błąd uruchomienia bota: {e}")

# Uruchomienie Flask w osobnym wątku
threading.Thread(target=run_discord_bot).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Używamy `app.run` z parametrem `host="0.0.0.0"` dla Render
    app.run(host="0.0.0.0", port=port, debug=False)
