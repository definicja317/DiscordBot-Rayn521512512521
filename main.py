import discord
from discord import app_commands, ui
import os
import sys
import threading
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime, timedelta
import re 
import asyncio
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
# <<< UTILITY FUNCTIONS >>>
# =====================

def parse_mention_id(text: str, type: Literal["role", "channel"]) -> int | None:
    """Ekstrahuje ID z wzmianki (np. @rola, #kanał)."""
    if type == "role":
        match = re.search(r'<@&(\d+)>', text)
    elif type == "channel":
        match = re.search(r'<#(\d+)>', text)
    return int(match.group(1)) if match else None

def parse_timer_minutes(text: str) -> int:
    """Ekstrahuje minuty z tekstu (np. '20 min')."""
    match = re.search(r'(\d+)\s*(min|minut)', text, re.I)
    return int(match.group(1)) if match else 0

# =====================
# <<< DYNAMICZNY TIMER (Core Fix) >>>
# =====================

async def update_timer_embed(message_id: int, event_type: str, guild: discord.Guild, data: dict, view_class):
    """Asynchronicznie aktualizuje wiadomość z timerem."""
    
    end_time: datetime = data["timer_end_time"]
    channel: discord.TextChannel = data["message"].channel
    initial_message: discord.Message = data["message"]
    role_mention = f"<@&{data['role_id']}>" if data.get("role_id") else "@everyone"
    
    while datetime.now() < end_time:
        remaining_seconds = (end_time - datetime.now()).total_seconds()
        
        # Obliczanie pozostałego czasu w minutach
        minutes_remaining = int(remaining_seconds // 60)
        
        # Czas, po jakim nastąpi kolejna aktualizacja (co 60 sekund lub mniej)
        sleep_time = max(1, min(remaining_seconds % 60 + 1, 60))
        
        try:
            # Tworzenie odpowiedniego widoku i embeda z aktualnym czasem
            if event_type == "captures":
                view = view_class(message_id, data.get("author_name", "Admin"))
            elif event_type == "airdrop":
                view = view_class(message_id, data["description"], data["voice_channel_id"], data.get("author_name", "Admin"))
            elif event_type in ["zancudo", "cayo"]:
                 view = view_class(message_id, event_type, data.get("author_name", "Admin"))
            else:
                break 

            embed = view.make_embed(guild, minutes_remaining)
            await initial_message.edit(embed=embed, view=view)
            
            if remaining_seconds < 1:
                break
                
            await asyncio.sleep(sleep_time)

        except discord.NotFound:
            print(f"Wiadomość {message_id} usunięta, anulowanie timera.")
            break
        except Exception as e:
            # W przypadku błędu (np. edycja zbyt szybko/za rzadko), odczekaj i spróbuj ponownie
            print(f"Błąd podczas aktualizacji timera {message_id}: {e}")
            await asyncio.sleep(10) 
            
    # Ostateczna aktualizacja i ping po zakończeniu timera
    if initial_message and data.get("is_active"):
        try:
            # Ostateczny Embed (0 minut)
            if event_type == "captures":
                view = view_class(message_id, data.get("author_name", "Admin"))
            elif event_type == "airdrop":
                view = view_class(message_id, data["description"], data["voice_channel_id"], data.get("author_name", "Admin"))
            elif event_type in ["zancudo", "cayo"]:
                 view = view_class(message_id, event_type, data.get("author_name", "Admin"))
            
            final_embed = view.make_embed(guild, 0)
            await initial_message.edit(embed=final_embed)
            
            # Wysłanie pingu/ostatecznego ogłoszenia
            await channel.send(f"{role_mention} **CZAS UPŁYNĄŁ!** Zbiórka! (Ogłoszenie po timerze dla {event_type.upper()})", delete_after=300)

            # Oznacz jako nieaktywne
            data["is_active"] = False

        except Exception as e:
            print(f"Błąd podczas finalnej aktualizacji timera: {e}")

# =====================
# <<< VIEWS Z DYNAMICZNYM TIMEREM >>>
# =====================

class CapturesView(ui.View):
    def __init__(self, capture_id: int, author_name: str): 
        super().__init__(timeout=None)
        self.capture_id = capture_id
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild, timer_minutes: int | None = None):
        participants_ids = captures.get(self.capture_id, {}).get("participants", [])
        data = captures.get(self.capture_id, {})
        
        # POPRAWKA 1: Opis
        description_text = "**Kliknij przycisk, aby się zapisać!**"
        
        embed = discord.Embed(title="CAPTURES!", description=description_text, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL) 
        
        if data.get("image_url"):
            embed.set_image(url=data["image_url"])
        
        if participants_ids:
            lines = []
            for uid in participants_ids:
                member = guild.get_member(uid)
                lines.append(f"- {member.mention}" if member else f"- <@{uid}>")
            embed.add_field(name=f"Zapisani ({len(participants_ids)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
            
        footer_text = f"Wystawione przez {self.author_name}"
        # POPRAWKA 2: Dynamiczny Timer w Stopce
        if timer_minutes is not None:
            if timer_minutes > 0:
                footer_text += f" | ⏰ Pozostało: {timer_minutes} minut"
            else:
                 footer_text += f" | ⚠️ ZBIÓRKA! CZAS UPŁYNĄŁ!"
                 
        embed.set_footer(text=footer_text)
        return embed

    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = captures.get(self.capture_id, {}).get("participants", [])
        
        if user_id not in participants:
            await interaction.response.defer() 
            captures.setdefault(self.capture_id, {"participants": []})["participants"].append(user_id)
            # Używamy make_embed z czasem pozostałym (jeśli timer jest aktywny)
            data = captures.get(self.capture_id, {})
            time_left = int((data.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
            await interaction.message.edit(embed=self.make_embed(interaction.guild, time_left), view=self)
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
            # Używamy make_embed z czasem pozostałym (jeśli timer jest aktywny)
            data = captures.get(self.capture_id, {})
            time_left = int((data.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
            await interaction.message.edit(embed=self.make_embed(interaction.guild, time_left), view=self)
            await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)
            
    # Przycisk Pickuj... (bez zmian)
    @ui.button(label="🎯 Pickuj osoby", style=discord.ButtonStyle.blurple)
    async def pick_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Logika pickowania bez zmian (wymaga implementacji SelectMenu).", ephemeral=True)


class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel_id: int, author_name: str):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.description = description
        self.voice_channel_id = voice_channel_id
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild, timer_minutes: int | None = None):
        participants_ids = airdrops.get(self.message_id, {}).get("participants", [])
        voice_channel = guild.get_channel(self.voice_channel_id)
        
        embed = discord.Embed(title="🎁 AirDrop!", description=self.description, color=discord.Color(0xFFFFFF))
        embed.set_thumbnail(url=LOGO_URL)
        embed.add_field(name="Kanał głosowy:", value=f"🔊 {voice_channel.mention if voice_channel else 'Nieznany kanał'}", inline=False)
        
        if participants_ids:
            lines = []
            for uid in participants_ids:
                member = guild.get_member(uid)
                lines.append(f"- {member.mention}" if member else f"- <@{uid}>")
            embed.add_field(name=f"Zapisani ({len(participants_ids)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
            
        footer_text = f"Wystawione przez {self.author_name}"
        # Dynamiczny Timer w Stopce
        if timer_minutes is not None:
            if timer_minutes > 0:
                footer_text += f" | ⏰ Rozpoczęcie za: {timer_minutes} minut"
            else:
                 footer_text += f" | ⚠️ CZAS UPŁYNĄŁ! Rozpoczęcie!"

        embed.set_footer(text=footer_text)
        return embed
    
    # join/leave buttons zaktualizowane o logikę timera
    @ui.button(label="✅ Dołącz", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        participants = airdrops.get(self.message_id, {}).get("participants", [])
        
        if interaction.user.id in participants:
            await interaction.followup.send("Już jesteś zapisany(a).", ephemeral=True)
            return
        
        airdrops.setdefault(self.message_id, {"participants": []})["participants"].append(interaction.user.id)
        data = airdrops.get(self.message_id, {})
        time_left = int((data.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
        await interaction.message.edit(embed=self.make_embed(interaction.guild, time_left), view=self)
        await interaction.followup.send("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer() 
        participants = airdrops.get(self.message_id, {}).get("participants", [])
        
        if interaction.user.id not in participants:
            await interaction.followup.send("Nie jesteś zapisany(a).", ephemeral=True)
            return
            
        airdrops[self.message_id]["participants"].remove(interaction.user.id)
        data = airdrops.get(self.message_id, {})
        time_left = int((data.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
        await interaction.message.edit(embed=self.make_embed(interaction.guild, time_left), view=self)
        await interaction.followup.send("❌ Opuściłeś(aś).", ephemeral=True)


class EventView(ui.View):
    def __init__(self, message_id: int, event_type: str, author_name: str): 
        super().__init__(timeout=None)
        self.message_id = message_id
        self.event_type = event_type
        self.author_name = author_name

    def make_embed(self, guild: discord.Guild, timer_minutes: int | None = None):
        participants_ids = events[self.event_type].get(self.message_id, {}).get("participants", [])
        data = events[self.event_type].get(self.message_id, {})
        
        title = "PING ZANCUDO" if self.event_type == "zancudo" else "PING CAYO"
        image_url = ZANCUDO_IMAGE_URL if self.event_type == "zancudo" else CAYO_IMAGE_URL
        
        voice_channel = guild.get_channel(data.get("voice_channel_id"))
        
        description_text = f"🚨 **Zbiórka na: {voice_channel.mention if voice_channel else 'Nieznany kanał'}**."
        
        embed = discord.Embed(title=title, description=description_text, color=discord.Color.red())
        embed.set_image(url=image_url)
        
        if participants_ids:
            lines = []
            for uid in participants_ids:
                member = guild.get_member(uid)
                lines.append(f"- {member.mention}" if member else f"- <@{uid}>")
            embed.add_field(name=f"Zapisani ({len(participants_ids)}):", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Zapisani:", value="Brak uczestników", inline=False)
            
        footer_text = f"Wystawione przez {self.author_name}"
        # Dynamiczny Timer w Stopce
        if timer_minutes is not None:
            if timer_minutes > 0:
                footer_text += f" | ⏰ Rozpoczęcie za: {timer_minutes} minut"
            else:
                 footer_text += f" | ⚠️ CZAS UPŁYNĄŁ! Rozpoczęcie!"
                 
        embed.set_footer(text=footer_text)
        return embed

    # join/leave buttons zaktualizowane o logikę timera
    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        participants = events[self.event_type].get(self.message_id, {}).get("participants", [])
        
        if user_id not in participants:
            await interaction.response.defer() 
            events[self.event_type].setdefault(self.message_id, {"participants": []})["participants"].append(user_id)
            data = events[self.event_type].get(self.message_id, {})
            time_left = int((data.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
            await interaction.message.edit(embed=self.make_embed(interaction.guild, time_left), view=self)
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
            data = events[self.event_type].get(self.message_id, {})
            time_left = int((data.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
            await interaction.message.edit(embed=self.make_embed(interaction.guild, time_left), view=self)
            await interaction.followup.send("Zostałeś(aś) wypisany(a).", ephemeral=True)
        else:
            await interaction.response.send_message("Nie jesteś zapisany(a).", ephemeral=True)


# =====================
# <<< MODALE (FORMULARZE - Core Fix) >>>
# =====================

class CapturesModal(ui.Modal, title="Utwórz Ogłoszenie CAPTURES"):
    channel_mention = ui.TextInput(label="Kanał tekstowy (#kanał)", placeholder="#ogłoszenia", required=True)
    role_mention = ui.TextInput(label="Rola do spingowania (@rola)", placeholder="@Gracze", required=True)
    image_url = ui.TextInput(label="Link do obrazka w tle (opcjonalnie)", required=False)
    timer_minutes = ui.TextInput(label="Timer (np. 5 min)", placeholder="5 min", required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        channel_id = parse_mention_id(str(self.channel_mention), "channel")
        role_id = parse_mention_id(str(self.role_mention), "role")
        timer = parse_timer_minutes(str(self.timer_minutes))
        image_url = str(self.image_url) if str(self.image_url) else None
        
        if not channel_id or not role_id or timer <= 0:
            await interaction.followup.send("❌ Błąd parsowania danych. Upewnij się, że kanał i rola są wzmiankami (#kanał/@rola), a timer to liczba minut (np. '5 min').", ephemeral=True)
            return
            
        channel = interaction.guild.get_channel(channel_id)
        role = interaction.guild.get_role(role_id)
        
        if not channel or not role:
            await interaction.followup.send("❌ Nie znaleziono kanału lub roli o podanym ID/wzmianki.", ephemeral=True)
            return

        author_name = interaction.user.display_name
        
        view = CapturesView(0, author_name)
        embed = view.make_embed(interaction.guild, timer)
        
        # POPRAWKA 1: Treść wiadomości to tylko ping
        content_message = f"{role.mention}" 
        
        try:
            message = await channel.send(content=content_message, embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości: {e}", ephemeral=True)
            return

        # Zapisanie do pamięci
        end_time = datetime.now() + timedelta(minutes=timer)
        captures[message.id] = {
            "participants": [],
            "author": interaction.user.id,
            "channel_id": channel.id,
            "message": message,
            "role_id": role.id,
            "image_url": image_url,
            "timer_end_time": end_time, # NOWA ZMIENNA DLA TIMERA
            "is_active": True,
            "author_name": author_name
        }
        
        # Aktualizacja view z poprawnym ID
        await message.edit(view=CapturesView(message.id, author_name))
        
        # Uruchomienie dynamicznego timera (Core Fix)
        client.loop.create_task(update_timer_embed(
            message.id, "captures", interaction.guild, captures[message.id], CapturesView
        ))

        await interaction.followup.send(f"✅ Ogłoszenie **CAPTURES** (Timer: {timer} min) wysłano na {channel.mention}.", ephemeral=True)


class AirdropModal(ui.Modal, title="Utwórz Ogłoszenie AirDrop"):
    channel_text = ui.TextInput(label="Kanał tekstowy (#kanał)", placeholder="#ogłoszenia", required=True)
    channel_voice = ui.TextInput(label="Kanał głosowy (#kanał-głosowy)", placeholder="#głosowy-zbiórka", required=True)
    role_mention = ui.TextInput(label="Rola do spingowania (@rola)", placeholder="@Gracze", required=True)
    description = ui.TextInput(label="Opis (Zasady/Info)", placeholder="RPK, 30 min, 5 osób", style=discord.TextStyle.long, required=True, max_length=500)
    timer_minutes = ui.TextInput(label="Timer do rozpoczęcia (np. 10 min)", placeholder="10 min", required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        channel_id = parse_mention_id(str(self.channel_text), "channel")
        voice_channel_id = parse_mention_id(str(self.channel_voice), "channel")
        role_id = parse_mention_id(str(self.role_mention), "role")
        timer = parse_timer_minutes(str(self.timer_minutes))
        description = str(self.description)
        
        if not channel_id or not voice_channel_id or not role_id or timer <= 0:
             await interaction.followup.send("❌ Błąd parsowania danych. Upewnij się, że kanały i rola są wzmiankami, a timer to liczba minut.", ephemeral=True)
             return
            
        channel = interaction.guild.get_channel(channel_id)
        voice_channel = interaction.guild.get_channel(voice_channel_id)
        role = interaction.guild.get_role(role_id)
        
        if not channel or not voice_channel or not role:
            await interaction.followup.send("❌ Nie znaleziono kanału/kanału głosowego lub roli o podanym ID/wzmianki.", ephemeral=True)
            return

        author_name = interaction.user.display_name
        view = AirdropView(0, description, voice_channel.id, author_name)
        embed = view.make_embed(interaction.guild, timer)
        
        content_message = f"{role.mention}"
        
        try:
            message = await channel.send(content=content_message, embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości: {e}", ephemeral=True)
            return

        # Zapisanie do pamięci
        end_time = datetime.now() + timedelta(minutes=timer)
        airdrops[message.id] = {
            "participants": [],
            "author": interaction.user.id,
            "channel_id": channel.id,
            "voice_channel_id": voice_channel.id,
            "description": description,
            "message": message,
            "role_id": role.id,
            "timer_end_time": end_time, 
            "is_active": True,
            "author_name": author_name
        }
        
        # Aktualizacja view z poprawnym ID
        await message.edit(view=AirdropView(message.id, description, voice_channel.id, author_name))
        
        # Uruchomienie dynamicznego timera (Core Fix)
        client.loop.create_task(update_timer_embed(
            message.id, "airdrop", interaction.guild, airdrops[message.id], AirdropView
        ))

        await interaction.followup.send(f"✅ Ogłoszenie **AIRDROP** (Timer: {timer} min) wysłano na {channel.mention}.", ephemeral=True)


class EventModal(ui.Modal, title="Utwórz Ping Eventu (Zancudo/Cayo)"):
    def __init__(self, event_type: Literal["zancudo", "cayo"]):
        super().__init__(title=f"Utwórz Ping {event_type.capitalize()}")
        self.event_type = event_type

        self.role_mention = ui.TextInput(label="Rola do spingowania (@rola)", placeholder="@Gracze", required=True)
        self.channel_voice = ui.TextInput(label="Kanał głosowy (#kanał-głosowy)", placeholder="#głosowy-zbiórka", required=True)
        self.timer_minutes = ui.TextInput(label="Timer (np. 5 min)", placeholder="5 min", required=True, max_length=10)
        
        self.add_item(self.role_mention)
        self.add_item(self.channel_voice)
        self.add_item(self.timer_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        voice_channel_id = parse_mention_id(str(self.channel_voice), "channel")
        role_id = parse_mention_id(str(self.role_mention), "role")
        timer = parse_timer_minutes(str(self.timer_minutes))
        
        if not voice_channel_id or not role_id or timer <= 0:
             await interaction.followup.send("❌ Błąd parsowania danych. Upewnij się, że kanał i rola są wzmiankami, a timer to liczba minut.", ephemeral=True)
             return

        voice_channel = interaction.guild.get_channel(voice_channel_id)
        role = interaction.guild.get_role(role_id)

        if not voice_channel or not role:
            await interaction.followup.send("❌ Nie znaleziono kanału głosowego lub roli o podanym ID/wzmianki.", ephemeral=True)
            return

        author_name = interaction.user.display_name
        view = EventView(0, self.event_type, author_name)
        embed = view.make_embed(interaction.guild, timer)
        
        content_message = f"{role.mention}"
        
        try:
            message = await interaction.channel.send(content=content_message, embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd podczas wysyłania wiadomości: {e}", ephemeral=True)
            return

        # Zapisanie do pamięci
        end_time = datetime.now() + timedelta(minutes=timer)
        events[self.event_type][message.id] = {
            "participants": [],
            "author": interaction.user.id,
            "channel_id": interaction.channel.id,
            "voice_channel_id": voice_channel.id,
            "message": message,
            "role_id": role.id,
            "timer_end_time": end_time, 
            "is_active": True,
            "author_name": author_name
        }
        
        # Aktualizacja view z poprawnym ID
        await message.edit(view=EventView(message.id, self.event_type, author_name))
        
        # Uruchomienie dynamicznego timera (Core Fix)
        client.loop.create_task(update_timer_embed(
            message.id, self.event_type, interaction.guild, events[self.event_type][message.id], EventView
        ))

        await interaction.followup.send(f"✅ Ogłoszenie **{self.event_type.upper()}** (Timer: {timer} min) wysłano na {interaction.channel.mention}.", ephemeral=True)

# =====================
# <<< PANEL ZARZĄDZANIA (ManagementPanelView) >>>
# =====================
class ManagementPanelView(ui.View):
    def __init__(self, admin_id: int):
        super().__init__(timeout=180)
        self.admin_id = admin_id

    @ui.button(label="📝 Utwórz Captures", style=discord.ButtonStyle.green, row=0)
    async def create_capt_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CapturesModal())
        
    @ui.button(label="🎁 Utwórz AirDrop", style=discord.ButtonStyle.blurple, row=0)
    async def create_airdrop_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AirdropModal())

    @ui.button(label="🚁 Ping Zancudo", style=discord.ButtonStyle.red, row=1)
    async def ping_zancudo_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(EventModal("zancudo"))
        
    @ui.button(label="🏝️ Ping Cayo", style=discord.ButtonStyle.red, row=1)
    async def ping_cayo_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(EventModal("cayo"))
        
    @ui.button(label="👥 Utwórz Squad", style=discord.ButtonStyle.blurple, row=2)
    async def create_squad_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/create-squad @rola 'Tytuł'**, aby utworzyć ogłoszenie o składzie.", 
            ephemeral=True
        )
        
    @ui.button(label="➕ Wpisz gracza na zapis", style=discord.ButtonStyle.green, row=3)
    async def add_enroll_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Użyj komendy **/wpisz-na-capt @użytkownik**, aby dodać gracza do aktywnego zapisu. Po jej użyciu pojawi się menu wyboru zapisu.",
            ephemeral=True
        )
        
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
# <<< ZARZĄDZANIE ZAPISAMI (Admin Fix) >>>
# =====================

def get_all_active_enrollments():
    """Zbiera wszystkie aktywne zapisy (z włączonym is_active)."""
    all_enrollments = []
    for msg_id, data in captures.items():
        if data.get("is_active", True): all_enrollments.append(("Captures", msg_id, data))
    for msg_id, data in airdrops.items():
        if data.get("is_active", True): all_enrollments.append(("AirDrop", msg_id, data))
    for etype, msgs in events.items():
        for msg_id, data in msgs.items():
             if data.get("is_active", True): all_enrollments.append((etype.capitalize(), msg_id, data))
    return all_enrollments

class EnrollmentSelectMenu(ui.Select):
    """Menu wyboru aktywnego zapisu dla komend admina."""
    def __init__(self, action: str):
        self.action = action 
        enrollments = get_all_active_enrollments()
        options = []
        for name, msg_id, data in enrollments:
            count = len(data.get("participants", []))
            # Wyświetlamy typ zapisu i ID dla administratora
            options.append(
                discord.SelectOption(
                    label=f"{name} (ID: {msg_id}) - {count} os.", 
                    value=f"{name.lower()}-{msg_id}" # np. captures-123456789
                )
            )
        super().__init__(
            placeholder=f"Wybierz zapis:",
            max_values=1,
            min_values=1,
            options=options
        )
        
    async def callback(self, interaction: discord.Interaction):
        # Callback jest obsługiwany przez Confirm button w Add/RemoveEnrollmentView
        pass 

# Reszta logiki Squads i Pick (bez timera)

# =====================
# <<< WIDOKI DLA KOMEND ADMINA (/wpisz-na-capt, /wypisz-z-capt) >>>
# =====================
# Wypisz z capt
class RemoveEnrollmentView(ui.View):
    def __init__(self, member_to_remove: discord.Member):
        super().__init__(timeout=180)
        self.member_to_remove = member_to_remove
        self.add_item(EnrollmentSelectMenu("remove"))

    @ui.button(label="Potwierdź usunięcie", style=discord.ButtonStyle.red)
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
        if type_str == "captures": data_dict = captures.get(msg_id)
        elif type_str == "airdrop": data_dict = airdrops.get(msg_id)
        elif type_str in events: data_dict = events[type_str].get(msg_id)

        if not data_dict:
            await interaction.followup.edit_message(content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.", view=None)
            return

        participants = data_dict.get("participants", [])
        if user_id not in participants:
            await interaction.followup.edit_message(content=f"⚠️ **{self.member_to_remove.display_name}** nie jest zapisany(a) na ten **{type_str.capitalize()}**.", view=None)
            return

        participants.remove(user_id)
        
        # Aktualizacja embeda z nową listą
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
            time_left = int((data_dict.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
            if type_str == "airdrop":
                view_obj = AirdropView(msg_id, data_dict["description"], data_dict["voice_channel_id"], data_dict["author_name"])
                await message.edit(embed=view_obj.make_embed(message.guild, time_left), view=view_obj)
            elif type_str == "captures":
                 view_obj = CapturesView(msg_id, data_dict["author_name"])
                 await message.edit(embed=view_obj.make_embed(message.guild, time_left), view=view_obj)

        await interaction.followup.edit_message(
            content=f"✅ Pomyślnie wypisano **{self.member_to_remove.display_name}** z **{type_str.capitalize()}** (ID: `{msg_id}`).", 
            view=None
        )

# Wpisz na capt
class AddEnrollmentView(ui.View):
    def __init__(self, member_to_add: discord.Member):
        super().__init__(timeout=180)
        self.member_to_add = member_to_add
        self.add_item(EnrollmentSelectMenu("add"))

    @ui.button(label="Potwierdź dodanie", style=discord.ButtonStyle.green)
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
        if type_str == "captures": data_dict = captures.get(msg_id)
        elif type_str == "airdrop": data_dict = airdrops.get(msg_id)
        elif type_str in events: data_dict = events[type_str].get(msg_id)

        if not data_dict:
            await interaction.followup.edit_message(content="❌ Błąd: Nie znaleziono aktywnego zapisu o tym ID.", view=None)
            return

        participants = data_dict.get("participants", [])
        if user_id in participants:
            await interaction.followup.edit_message(content=f"⚠️ **{self.member_to_add.display_name}** jest już zapisany(a) na ten **{type_str.capitalize()}**.", view=None)
            return

        participants.append(user_id)
        
        # Aktualizacja embeda z nową listą
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
            time_left = int((data_dict.get("timer_end_time", datetime.now()) - datetime.now()).total_seconds() // 60)
            if type_str == "airdrop":
                view_obj = AirdropView(msg_id, data_dict["description"], data_dict["voice_channel_id"], data_dict["author_name"])
                await message.edit(embed=view_obj.make_embed(message.guild, time_left), view=view_obj)
            elif type_str == "captures":
                 view_obj = CapturesView(msg_id, data_dict["author_name"])
                 await message.edit(embed=view_obj.make_embed(message.guild, time_left), view=view_obj)

        await interaction.followup.edit_message(
            content=f"✅ Pomyślnie wpisano **{self.member_to_add.display_name}** na **{type_str.capitalize()}** (ID: `{msg_id}`).", 
            view=None
        )

# =====================
# <<< KOMENDY (Slash Commands) >>>
# =====================

@tree.command(name="panel", description="Wyświetla panel do tworzenia ogłoszeń (tylko Admini).")
async def panel_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in ADMIN_ROLES:
        await interaction.followup.send("⛔ Brak uprawnień do użycia tej komendy!", ephemeral=True)
        return
    embed = discord.Embed(
        title="🛠️ Panel Zarządzania Ogłoszeniami", 
        description="Wybierz opcję, aby otworzyć **formularz** (Modal).",
        color=discord.Color.dark_green()
    )
    await interaction.followup.send(
        embed=embed, 
        view=ManagementPanelView(interaction.user.id), 
        ephemeral=True
    )

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

@tree.command(name="wypisz-z-capt", description="Wypisuje użytkownika z dowolnego aktywnego zapisu (Captures, AirDrop, Event).")
@app_commands.describe(członek="Użytkownik, którego chcesz wypisać.")
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
    
# --- Event: On Ready i Uruchomienie Bota ---
@client.event
async def on_ready():
    # ... Logika przywracania widoków ...
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

def run_discord_bot():
    try:
        # Zapisz SquadView, aby uniknąć błędów
        class SquadView(ui.View):
             def __init__(self, message_id: int, role_id: int):
                 super().__init__(timeout=None)
             @ui.button(label="Zarządzaj składem (ADMIN)", style=discord.ButtonStyle.blurple)
             async def manage_squad_button(self, interaction: discord.Interaction, button: ui.Button):
                 await interaction.response.send_message("Logika Squad jest tymczasowo uproszczona.", ephemeral=True)

        for msg_id, data in captures.items():
            if data.get("is_active"): client.add_view(CapturesView(msg_id, data["author_name"]))
        for msg_id, data in airdrops.items():
            if data.get("is_active"): client.add_view(AirdropView(msg_id, data["description"], data["voice_channel_id"], data["author_name"]))
        for msg_id, data in events["zancudo"].items():
            if data.get("is_active"): client.add_view(EventView(msg_id, "zancudo", data["author_name"]))
        for msg_id, data in events["cayo"].items():
            if data.get("is_active"): client.add_view(EventView(msg_id, "cayo", data["author_name"]))
        for msg_id, data in squads.items():
            client.add_view(SquadView(msg_id, data["role_id"]))
            
        client.run(token)
    except Exception as e:
        print(f"Błąd uruchomienia bota: {e}")

threading.Thread(target=run_discord_bot).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
