import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
# ZMIANA: Dodajemy asyncio i timedelta
import asyncio
from datetime import datetime, timedelta 
import re 
import pytz # Potrzebne do obsługi stref czasowych, aby uniknąć błędów

# Ustawienie polskiej strefy czasowej
POLAND_TZ = pytz.timezone("Europe/Warsaw")

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
# ZMIANA: Dodanie "end_time" i "task"
captures = {}   
airdrops = {}   
events = {"zancudo": {}, "cayo": {}} 
squads = {}     

# <<< KLASA ZADANIA DLA TIMERA >>>
class CountdownTask:
    def __init__(self, message: discord.Message, data_dict: dict, item_id: int, view_class, embed_generator):
        self.message = message
        self.data_dict = data_dict # airdrops lub captures
        self.item_id = item_id
        self.view_class = view_class
        self.embed_generator = embed_generator
        self._task = client.loop.create_task(self.run_countdown())
        
    def cancel(self):
        self._task.cancel()

    async def run_countdown(self):
        await client.wait_until_ready()
        
        # Pobieramy czas zakończenia z danych
        end_time = self.data_dict.get(self.item_id, {}).get("end_time")
        if not end_time or not isinstance(end_time, datetime):
            print(f"Błąd timera: Brak poprawnego end_time dla {self.item_id}")
            return
            
        is_airdrop = 'voice_channel_id' in self.data_dict.get(self.item_id, {})
        
        while True:
            now = datetime.now(POLAND_TZ)
            time_left: timedelta = end_time - now
            
            # Weryfikacja czy wiadomość nadal istnieje
            if not self.message or not self.data_dict.get(self.item_id):
                 print(f"Zatrzymanie timera: Wiadomość/Dane dla {self.item_id} zaginęły.")
                 break

            if time_left.total_seconds() <= 0:
                print(f"Timer zakończony dla {self.item_id}")
                
                # Ostatnia aktualizacja embeda
                new_embed = self.embed_generator(self.message.guild, end_time)
                
                # Dodajemy informację o zakończeniu w wiadomości
                content_prefix = "**❗ CZAS MINĄŁ! ZACZYNAMY! ❗**" 
                
                # Blokujemy przyciski po zakończeniu (opcjonalnie)
                if self.message.view:
                    for item in self.message.view.children:
                        item.disabled = True
                    
                    # Edytujemy wiadomość
                    await self.message.edit(content=content_prefix, embed=new_embed, view=self.message.view)
                else:
                    await self.message.edit(content=content_prefix, embed=new_embed)
                    
                # Usuwamy zadanie z pamięci
                del self.data_dict[self.item_id]['task']
                break
                
            try:
                # Edycja wiadomości
                new_embed = self.embed_generator(self.message.guild, end_time)
                
                # Sprawdzamy, czy potrzebny jest nowy widok do edycji
                view_to_edit = self.message.view
                if not view_to_edit:
                    # Tworzymy nowy widok, jeśli z jakiegoś powodu zaginął (np. po restarcie bez trwałego widoku)
                    data = self.data_dict[self.item_id]
                    if is_airdrop:
                        voice_channel = client.get_channel(data["voice_channel_id"])
                        view_to_edit = self.view_class(self.item_id, data["description"], voice_channel, data["author_name"])
                        view_to_edit.participants = data["participants"]
                    else:
                        view_to_edit = self.view_class(self.item_id, data["author_name"])
                        
                await self.message.edit(embed=new_embed, view=view_to_edit)
                
            except discord.HTTPException as e:
                # Obsługa błędów, np. jeśli wiadomość została usunięta
                if e.status == 404:
                    print(f"Zatrzymanie timera: Wiadomość {self.item_id} została usunięta.")
                    break
                print(f"Błąd edycji wiadomości dla {self.item_id}: {e}")

            # Ustawienie interwału odświeżania
            if time_left.total_seconds() < 60:
                await asyncio.sleep(1) # Odświeżanie co 1 sekundę poniżej 1 minuty
            else:
                await asyncio.sleep(60) # Odświeżanie co 60 sekund (1 minuta)
                
        # Zawsze usuwamy po zakończeniu pętli, jeśli coś poszło nie tak
        if self.item_id in self.data_dict and 'task' in self.data_dict[self.item_id]:
             del self.data_dict[self.item_id]['task']


def format_time_left(end_time: datetime) -> str:
    """Formatuje czas pozostały do końca na podstawie EndTime."""
    now = datetime.now(POLAND_TZ)
    time_left: timedelta = end_time - now
    total_seconds = int(time_left.total_seconds())

    if total_seconds <= 0:
        return "**CZAS MINĄŁ!**"
    
    if total_seconds < 60:
        # Sekundy (poniżej 1 minuty)
        return f"⏳ **{total_seconds}** sek. do startu!"
    else:
        # Minuty i sekundy (lub tylko minuty, gdy >= 1 min)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"⏱️ **{minutes}** min. **{seconds}** sek. do startu!"
        
# <<< KONIEC KLASY ZADANIA DLA TIMERA >>>


# =====================
#       AIRDROP & CAPTURES VIEWS
# =====================

# ZMIANA: Dodanie end_time
class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel: discord.VoiceChannel, author_name: str):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.description = description
        self.voice_channel = voice_channel
        self.participants: list[int] = airdrops.get(message_id, {}).get("participants", []) # POBIERA ZAWSZE Z PAMIĘCI
        self.author_name = author_name
        self.custom_id = f"airdrop_view:{message_id}" 

    # ZMIANA: Dodanie end_time
    def make_embed(self, guild: discord.Guild, end_time: datetime = None):
        embed = discord.Embed(title="🎁 AirDrop!", description=self.description, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL)
        embed.add_field(name="Kanał głosowy:", value=f"🔊 {self.voice_channel.mention}", inline=False)
        
        # ZMIANA: DODANIE TIMERA
        if end_time:
             embed.add_field(name="Pozostały czas", value=format_time_left(end_time), inline=False)

        # Używamy zaktualizowanej listy uczestników z pamięci
        current_participants = airdrops.get(self.message_id, {}).get("participants", [])
        
        if current_participants:
            lines = []
            for uid in current_participants:
                member = guild.get_member(uid)
                if member:
                    lines.append(f"- {member.mention} | **{member.display_name}**")
                else:
                    lines.append(f"- <@{uid}> (Użytkownik opuścił serwer)")
            embed.add_field(name=f"Zapisani ({len(current_participants)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
            
        embed.set_footer(text=f"Wystawione przez {self.author_name}")
        return embed

    @ui.button(label="✅ Dołącz", style=discord.ButtonStyle.green, custom_id="airdrop_join")
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        
        data = airdrops.get(self.message_id)
        if not data:
             await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota. Spróbuj utworzyć nowy zapis.", ephemeral=True)
             return
             
        if interaction.user.id in data["participants"]:
            await interaction.followup.send("Już jesteś zapisany(a).", ephemeral=True)
            return
        
        data["participants"].append(interaction.user.id)
        
        # Wymagamy end_time do generowania embeda z timera
        end_time = data.get("end_time")
        await interaction.message.edit(embed=self.make_embed(interaction.guild, end_time=end_time), view=self)
        await interaction.followup.send("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red, custom_id="airdrop_leave")
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        
        data = airdrops.get(self.message_id)
        if not data:
             await interaction.followup.send("Błąd: Dane zapisu zaginęły po restarcie bota. Spróbuj utworzyć nowy zapis.", ephemeral=True)
             return
             
        if interaction.user.id not in data["participants"]:
            await interaction.followup.send("Nie jesteś zapisany(a).", ephemeral=True)
            return
            
        data["participants"].remove(interaction.user.id)
        
        # Wymagamy end_time do generowania embeda z timera
        end_time = data.get("end_time")
        await interaction.message.edit(embed=self.make_embed(interaction.guild, end_time=end_time), view=self)
        await interaction.followup.send("❌ Opuściłeś(aś).", ephemeral=True)


# ZMIANA: Dodanie end_time
class CapturesView(ui.View):
    def __init__(self, capture_id: int, author_name: str): 
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name
        self.custom_id = f"captures_view:{capture_id}"

    # ZMIANA: Dodanie end_time
    def make_embed(self, guild: discord.Guild, end_time: datetime = None):
        
        # Używamy zaktualizowanej listy uczestników z pamięci
        current_participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        
        embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
        # ZMIANA: DODANIE TIMERA
        if end_time:
             embed.add_field(name="Pozostały czas", value=format_time_left(end_time), inline=False)
        
        if current_participants_ids:
            lines = []
            for uid in current_participants_ids:
                member = guild.get_member(uid)
                if member:
                    lines.append(f"- {member.mention} | **{member.display_name}**")
                else:
                    lines.append(f"- <@{uid}> (Użytkownik opuścił serwer)")
            embed.add_field(name=f"Zapisani ({len(current_participants_ids)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
            
        embed.set_footer(text=f"Wystawione przez {self.author_name}")
        return embed

    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green, custom_id="capt_join")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        data = captures.get(self.capture_id)
        
        if not data:
             await interaction.response.send_message("Błąd: Dane zapisu zaginęły po restarcie bota.", ephemeral=True)
             return
             
        if user_id not in data["participants"]:
            await interaction.response.defer() 
            data["participants"].append(user_id)
            
            # Wymagamy end_time do generowania embeda z timera
            end_time = data.get("end_time")
            if data.get("message"):
                await interaction.message.edit(embed=self.make_embed(interaction.guild, end_time=end_time), view=self)
                await interaction.followup.send("Zostałeś(aś) zapisany(a)!", ephemeral=True)
            else:
                await interaction.followup.send("Zostałeś(aś) zapisany(a), ale wiadomość ogłoszenia mogła zaginąć po restarcie bota.", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red, custom_id="capt_leave")
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        data = captures.get(self.capture_id)
        
        if not data:
             await interaction.response.send_message("Błąd: Dane zapisu zaginęły po restarcie bota.", ephemeral=True)
             return
             
        if user_id in data["participants"]:
            await interaction.response.defer() 
            data["participants"].remove(user_id)
            
            # Wymagamy end_time do generowania embeda z timera
            end_time = data.get("end_time")
            if data.get("message"):
                await interaction.message.edit(embed=self.make_embed(interaction.guild, end_time=end_time), view=self)
                await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
            else:
                 await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple, custom_id="capt_pick")
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        if PICK_ROLE_ID not in [r.id for r in interaction.user.roles]:
            await interaction.followup.send("⛔ Brak uprawnień!", ephemeral=True)
            return
            
        participants = captures.get(self.capture_id, {}).get("participants", [])
        if not participants:
            await interaction.followup.send("Nikt się nie zapisał!", ephemeral=True)
            return
            
        # UWAGA: Ten widok nie musi być trwały, więc nie ruszamy custom_id.
        pick_view = PickPlayersView(self.capture_id)
        pick_view.add_item(PlayerSelectMenu(self.capture_id, interaction.guild))
        
        await interaction.followup.send("Wybierz do 25 graczy:", view=pick_view, ephemeral=True)
# ... reszta klas (PlayerSelectMenu, PickPlayersView, SquadView, EditSquadView) pozostaje bez zmian
# Zostawiam resztę klas tak, jak były, ponieważ nie dotyczą Timera.

# =======================================================
# <<< FUNKCJE DLA SQUADÓW >>>
# (Bez zmian)
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
    def __init__(self, message_id: int):
        super().__init__(timeout=180, custom_id=f"edit_squad_view:{message_id}") 
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
            await interaction.followup.send("Błąd: Nie znaleziono danych tego składu.", ephemeral=True)
            return

        squad_data["member_ids"] = selected_ids
        
        message = squad_data.get("message")
        author_name = squad_data.get("author_name", "Bot")
        title = "Main Squad"
        if message and message.embeds:
            title = message.embeds[0].title
            
        new_embed = create_squad_embed(interaction.guild, author_name, selected_ids, title)
        
        if message and hasattr(message, 'edit'):
            new_squad_view = SquadView(self.message_id, squad_data.get("role_id"))
            
            role_id = squad_data.get("role_id")
            content = f"<@&{role_id}> **Zaktualizowano Skład!**" if role_id else ""
            
            await message.edit(content=content, embed=new_embed, view=new_squad_view)
            
            await interaction.followup.send(content="✅ Skład został pomyślnie zaktualizowany! Wróć do głównej wiadomości składu.", ephemeral=True)
        else:
            await interaction.followup.send(content="Błąd: Nie można odświeżyć wiadomości składu. Być może bot został zrestartowany.", ephemeral=True)


class SquadView(ui.View):
    def __init__(self, message_id: int, role_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id
        self.custom_id = f"squad_view:{message_id}"

    @ui.button(label="Zarządzaj składem (ADMIN)", style=discord.ButtonStyle.blurple, custom_id="manage_squad_button")
    async def manage_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True) 

        if interaction.user.id not in ADMIN_ROLES:
            await interaction.followup.send("⛔ Brak uprawnień do zarządzania składem!", ephemeral=True)
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

# ... reszta kodu z AddEnrollmentView, RemoveEnrollmentView, EnrollmentSelectMenu, PlayerSelectMenu, PickPlayersView

# =======================================================
# <<< KONIEC FUNKCJI DLA SQUADÓW >>>
# =======================================================
# ... (pozostałe klasy bez zmian dla zwięzłości, zakładamy, że są w pliku)
# ...

# KLASY ZARZĄDZANIA ZAPISAMI (POZOSTAJĄ BEZ ZMIAN)

# ...

# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    # Przywracanie widoków i zadań timera
    
    # 1. SQUAD VIEWS
    if squads:
        print(f"Próba przywrócenia {len(squads)} widoków Squad.")
        for msg_id, data in squads.items():
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     data["message"] = await channel.fetch_message(msg_id)
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
                     message = await channel.fetch_message(msg_id)
                     data["message"] = message
                     
                     # ZMIANA: Dodajemy widok CapturesView
                     view = CapturesView(msg_id, data["author_name"])
                     client.add_view(view)
                     
                     # ZMIANA: Przywracamy zadanie timera
                     end_time = data.get("end_time")
                     if end_time and end_time > datetime.now(POLAND_TZ):
                         print(f"Przywracanie timera Captures {msg_id}...")
                         data["task"] = CountdownTask(
                             message, 
                             captures, 
                             msg_id, 
                             CapturesView, 
                             view.make_embed
                         )
                     
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku Captures {msg_id}: {e}")
                 
    # 3. AIRDROP VIEWS
    if airdrops:
        print(f"Próba przywrócenia {len(airdrops)} widoków AirDrop.")
        for msg_id, data in airdrops.items():
             try:
                 channel = client.get_channel(data["channel_id"])
                 if channel:
                     message = await channel.fetch_message(msg_id)
                     data["message"] = message
                     voice_channel = client.get_channel(data["voice_channel_id"])
                     
                     if voice_channel:
                         # ZMIANA: Dodajemy widok AirdropView
                         view = AirdropView(msg_id, data["description"], voice_channel, data["author_name"])
                         view.participants = data.get("participants", [])
                         client.add_view(view)
                         
                         # ZMIANA: Przywracamy zadanie timera
                         end_time = data.get("end_time")
                         if end_time and end_time > datetime.now(POLAND_TZ):
                              print(f"Przywracanie timera AirDrop {msg_id}...")
                              data["task"] = CountdownTask(
                                 message, 
                                 airdrops, 
                                 msg_id, 
                                 AirdropView, 
                                 view.make_embed
                             )
                     else:
                         print(f"Ostrzeżenie: Nie znaleziono kanału głosowego dla AirDrop {msg_id}. Pomijam przywracanie widoku.")
             except Exception as e:
                 print(f"Błąd przy przywracaniu widoku AirDrop {msg_id}: {e}")

    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")


# Captures
# ZMIANA: Dodanie argumentu czas_trwania_minuty
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures z odliczaniem.")
@app_commands.describe(czas_trwania_minuty="Czas do rozpoczęcia w minutach (np. 20)")
async def create_capt(interaction: discord.Interaction, czas_trwania_minuty: app_commands.Range[int, 1]):
    await interaction.response.defer(ephemeral=True) 
    
    author_name = interaction.user.display_name
    view = CapturesView(0, author_name) 
    
    # ZMIANA: Obliczanie czasu zakończenia
    end_time = datetime.now(POLAND_TZ) + timedelta(minutes=czas_trwania_minuty)
    embed = view.make_embed(interaction.guild, end_time=end_time)
    
    sent = await interaction.channel.send(content="@everyone", embed=embed, view=view)
    
    captures[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "author_name": author_name,
        "end_time": end_time, # ZAPIS END TIME
        "task": None # Placeholder dla zadania timera
    }
    
    # Aktualizacja View z poprawnym ID wiadomości i custom_id
    view.capture_id = sent.id 
    view.custom_id = f"captures_view:{sent.id}"
    await sent.edit(view=view) 
    
    # ZMIANA: Uruchomienie zadania timera
    captures[sent.id]["task"] = CountdownTask(
        sent, 
        captures, 
        sent.id, 
        CapturesView, 
        view.make_embed
    )
    
    await interaction.followup.send(f"Ogłoszenie o captures wysłane! Start za **{czas_trwania_minuty}** minut.", ephemeral=True)


# AirDrop
# ZMIANA: Dodanie argumentu czas_trwania_minuty
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie z odliczaniem.")
@app_commands.describe(
    channel="Kanał tekstowy, na którym ogłosić", 
    voice="Kanał głosowy na którym odbędzie się AirDrop", 
    role="Rola do pingowania (@role)", 
    opis="Opis wydarzenia",
    czas_trwania_minuty="Czas do rozpoczęcia w minutach (np. 20)"
)
async def airdrop_command(interaction: discord.Interaction, channel: discord.TextChannel, voice: discord.VoiceChannel, role: discord.Role, opis: str, czas_trwania_minuty: app_commands.Range[int, 1]):
    await interaction.response.defer(ephemeral=True)
    
    # ZMIANA: Obliczanie czasu zakończenia
    end_time = datetime.now(POLAND_TZ) + timedelta(minutes=czas_trwania_minuty)
    
    view = AirdropView(0, opis, voice, interaction.user.display_name)
    embed = view.make_embed(interaction.guild, end_time=end_time) # Przekazanie end_time
    
    sent = await channel.send(content=f"{role.mention}", embed=embed, view=view)
    
    # Zapisanie danych AirDrop
    airdrops[sent.id] = {
        "participants": [], 
        "message": sent, 
        "channel_id": sent.channel.id, 
        "description": opis, 
        "voice_channel_id": voice.id, 
        "author_name": interaction.user.display_name,
        "end_time": end_time, # ZAPIS END TIME
        "task": None # Placeholder dla zadania timera
    }
    
    # Aktualizacja View z poprawnym ID wiadomości i custom_id
    view.message_id = sent.id
    view.custom_id = f"airdrop_view:{sent.id}"
    await sent.edit(view=view)
    
    # ZMIANA: Uruchomienie zadania timera
    airdrops[sent.id]["task"] = CountdownTask(
        sent, 
        airdrops, 
        sent.id, 
        AirdropView, 
        view.make_embed
    )
    
    await interaction.followup.send(f"✅ AirDrop utworzony! Start za **{czas_trwania_minuty}** minut.", ephemeral=True)

# ... reszta komend (Squad, List-all, Set-status, Wypisz/Wpisz) pozostaje bez zmian
# ...

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
