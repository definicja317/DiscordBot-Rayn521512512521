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
STATUS_ADMINS = [1184620388425138183, 1409225386998501480, 1007732573063098378, 364869132526551050]  # <<< wpisz swoje ID
# <<< NOWA ZMIANA - UŻYCIE STATUS_ADMINS RÓWNIEŻ DO WPISYWANIA/WYPISYWANIA
ADMIN_ROLES = STATUS_ADMINS
# >>>
ZANCUDO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414194392214011974/image.png"
CAYO_IMAGE_URL = "https://cdn.discordapp.com/attachments/1224129510535069766/1414204332747915274/image.png"
LOGO_URL = "https://cdn.discordapp.com/attachments/1184622314302754857/1420796249484824757/RInmPqb.webp?ex=68d6b31e&is=68d5619e&hm=0cdf3f7cbb269b12c9f47d7eb034e40a8d830ff502ca9ceacb3d7902d3819413&"

# --- Discord Client ---
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Pamięć zapisów ---
# WAŻNA ZMIANA: Aby ułatwić zarządzanie przez admina, captures również przechowuje IDs
captures = {}   # {msg_id: {"participants": [member_ids], "message": discord.Message, "channel_id": int}}
airdrops = {}   # {msg_id: {"participants": [ids], "message": discord.Message, "channel_id": int}}
events = {"zancudo": {}, "cayo": {}}  # {event_type: {msg_id: {"participants": [ids], "message": discord.Message, "channel_id": int}}}

# <<< NOWA FUNKCJA - WSPARCIE DLA ZARZĄDZANIA ADMINA >>>
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
        self.action = action # 'add' lub 'remove'
        enrollments = get_all_active_enrollments()
        options = []
        
        for name, msg_id, data in enrollments:
            count = len(data.get("participants", []))
            # Wartość opcji to: "typ_zapisu-id_wiadomości"
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
        # Ta część będzie obsłużona w komendach
        pass 

# >>> KONIEC NOWEJ FUNKCJI - WSPARCIE DLA ZARZĄDZANIA ADMINA

# =====================
#       AIRDROP
# =====================
class AirdropView(ui.View):
    def __init__(self, message_id: int, description: str, voice_channel: discord.VoiceChannel, author_name: str):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.description = description
        self.voice_channel = voice_channel
        self.participants: list[int] = [] # Pamięć ID
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
        # Zapisz w lokalnej i globalnej pamięci
        if interaction.user.id in self.participants:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)
            return
        self.participants.append(interaction.user.id)
        airdrops[self.message_id]["participants"].append(interaction.user.id)
        await interaction.message.edit(embed=self.make_embed(interaction.guild), view=self)
        await interaction.response.send_message("✅ Dołączyłeś(aś)!", ephemeral=True)

    @ui.button(label="❌ Opuść", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        # Usuń z lokalnej i globalnej pamięci
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
# <<< ZMIANA - W CapturesView Participants są teraz przechowywani jako ID
# Aby spójnie zarządzać, zmieniamy też to, jak to jest przechowywane.
# W klasach musimy pracować z ID, a nie obiektami Member.
# Zmieniamy też sposób wyświetlania, aby używać IDs z pamięci globalnej.
# >>>
class PlayerSelectMenu(ui.Select):
    def __init__(self, capture_id: int, guild: discord.Guild):
        self.capture_id = capture_id
        # Używamy ID z pamięci globalnej do utworzenia opcji
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
        # Select menu musi być inicjowane w callbacku lub z dostępem do guild
        # Aby to uprościć, inicjujemy go tu, ale przekazujemy go do PickPlayersView
        # Przenosimy inicjalizację do callbacku pick_button
        # self.player_select_menu = PlayerSelectMenu(capture_id) 
        # self.add_item(self.player_select_menu)
        pass # Zostawiamy puste, bo PlayerSelectMenu jest tworzone później

    @ui.button(label="Potwierdź wybór", style=discord.ButtonStyle.green)
    async def confirm_pick(self, interaction: discord.Interaction, button: ui.Button):
        # Ponieważ SelectMenu było dynamicznie tworzone, musimy je znaleźć po interakcji
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
    def __init__(self, capture_id: int):
        super().__init__(timeout=None)
        self.capture_id = capture_id

    @ui.button(label="✅ Wpisz się", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id not in captures.get(self.capture_id, {}).get("participants", []):
            captures.setdefault(self.capture_id, {"participants": []})["participants"].append(user_id)
            await interaction.response.send_message("Zostałeś(aś) zapisany(a)!", ephemeral=True)
        else:
            await interaction.response.send_message("Już jesteś zapisany(a).", ephemeral=True)

    @ui.button(label="❌ Wypisz się", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id in captures.get(self.capture_id, {}).get("participants", []):
            captures[self.capture_id]["participants"].remove(user_id)
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
        # Dodajemy PlayerSelectMenu dynamicznie, bo musi mieć dostęp do guild
        pick_view.add_item(PlayerSelectMenu(self.capture_id, interaction.guild))
        
        await interaction.response.send_message("Wybierz do 25 graczy:", view=pick_view, ephemeral=True)


# =====================
#       KOMENDY
# =====================
@client.event
async def on_ready():
    # <<< ZMIANA - Wczytanie widoków (jeśli wiadomości przetrwały restart) >>>
    # Wymaga to pewnych zmian w sposobie przechowywania danych, 
    # ale na razie dla celów demonstracyjnych pomijamy trwałe wczytywanie widoków,
    # ponieważ nie mamy backendu do trwałego zapisu wszystkich danych.
    # W przypadku bota hostowanego na Render, po restarcie dane będą puste.
    await tree.sync()
    print(f"✅ Zalogowano jako {client.user}")

# Captures
@tree.command(name="create-capt", description="Tworzy ogłoszenie o captures.")
async def create_capt(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True) # Defer, aby wysłać content
    embed = discord.Embed(title="CAPTURES!", description="Kliknij przycisk, aby się zapisać!", color=discord.Color(0xFFFFFF))
    # Wysyłamy wiadomość, a potem edytujemy widok
    sent = await interaction.channel.send(content="@everyone", embed=embed, view=CapturesView(0))
    # Pamięć: ID, Message Object, Channel ID
    captures[sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await sent.edit(view=CapturesView(sent.id))
    await interaction.followup.send("Ogłoszenie o captures wysłane!", ephemeral=True)

# AirDrop
@tree.command(name="airdrop", description="Tworzy ogłoszenie o AirDropie")
async def airdrop_command(interaction: discord.Interaction, channel: discord.TextChannel, voice: discord.VoiceChannel, role: discord.Role, opis: str):
    await interaction.response.defer(ephemeral=True)
    view = AirdropView(0, opis, voice, interaction.user.display_name)
    embed = view.make_embed(interaction.guild)
    sent = await channel.send(content=f"{role.mention}", embed=embed, view=view)
    view.message_id = sent.id
    # Pamięć: ID, Message Object, Channel ID
    airdrops[sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ AirDrop utworzony!", ephemeral=True)

# Eventy Zancudo / Cayo
# Zmiana: Aby móc nimi zarządzać, dodajemy też je do pamięci "events"
@tree.command(name="ping-zancudo", description="Wysyła ogłoszenie o ataku na Fort Zancudo.")
async def ping_zancudo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="Atak na FORT ZANCUDO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFF0000))
    embed.set_image(url=ZANCUDO_IMAGE_URL)
    sent = await interaction.channel.send(content=f"{role.mention}", embed=embed)
    # Pamięć: ID, Message Object, Channel ID
    events["zancudo"][sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

@tree.command(name="ping-cayo", description="Wysyła ogłoszenie o ataku na Cayo Perico.")
async def ping_cayo(interaction: discord.Interaction, role: discord.Role, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="Atak na CAYO PERICO!", description=f"Zapraszamy na {channel.mention}!", color=discord.Color(0xFFAA00))
    embed.set_image(url=CAYO_IMAGE_URL)
    sent = await interaction.channel.send(content=f"{role.mention}", embed=embed)
    # Pamięć: ID, Message Object, Channel ID
    events["cayo"][sent.id] = {"participants": [], "message": sent, "channel_id": sent.channel.id}
    await interaction.followup.send("✅ Ogłoszenie o ataku wysłane!", ephemeral=True)

# Lista wszystkich zapisanych
@tree.command(name="list-all", description="Pokazuje listę wszystkich zapisanych")
async def list_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    desc = ""
    # Używamy nowej funkcji do pobrania wszystkich zapisów
    for name, mid, data in get_all_active_enrollments():
        desc += f"\n**{name} (msg {mid})**: {len(data['participants'])} osób"
        
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

# ===============================================
# <<< NOWA KOMENDA - WYPISZ-Z-CAPT >>>
# ===============================================
class RemoveEnrollmentView(ui.View):
    def __init__(self, member_to_remove: discord.Member):
        super().__init__(timeout=180)
        self.member_to_remove = member_to_remove
        self.add_item(EnrollmentSelectMenu("remove"))

    @ui.button(label="Potwierdź usunięcie", style=discord.ButtonStyle.red)
    async def confirm_remove(self, interaction: discord.Interaction, button: ui.Button):
        # Sprawdzamy, czy wybrano element z Select Menu
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not select_menu or not select_menu.values:
            await interaction.response.send_message("⚠️ Najpierw wybierz zapis z listy!", ephemeral=True)
            return

        # Wartość to: "typ_zapisu-id_wiadomości"
        type_str, msg_id_str = select_menu.values[0].split('-')
        msg_id = int(msg_id_str)
        user_id = self.member_to_remove.id
        
        # Znajdź właściwy słownik danych
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

        # Usuń użytkownika
        participants.remove(user_id)
        
        # Próbujemy odświeżyć wiadomość
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
            # Jeśli to AirDrop, użyjemy jego funkcji make_embed
            if type_str == "airdrop":
                # Musimy odtworzyć obiekt widoku
                view_obj = AirdropView(msg_id, message.embeds[0].description, message.guild.get_channel(data_dict["channel_id"]), message.embeds[0].footer.text.replace("Wystawione przez ", ""))
                view_obj.participants = participants
                # Zmieniamy treść w globalnej pamięci
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
            # W przypadku Captures, musimy tylko usunąć ID z pamięci
            elif type_str == "captures":
                 # Captures nie odświeża embeda z listą, więc wystarczy usunięcie z pamięci.
                 captures[msg_id]["participants"] = participants
            # Eventy Zancudo/Cayo nie mają interaktywnego embeda, więc wystarczy usunięcie z pamięci.
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

# ===============================================
# <<< NOWA KOMENDA - WPISZ-NA-CAPT >>>
# ===============================================
class AddEnrollmentView(ui.View):
    def __init__(self, member_to_add: discord.Member):
        super().__init__(timeout=180)
        self.member_to_add = member_to_add
        self.add_item(EnrollmentSelectMenu("add"))

    @ui.button(label="Potwierdź dodanie", style=discord.ButtonStyle.green)
    async def confirm_add(self, interaction: discord.Interaction, button: ui.Button):
        # Sprawdzamy, czy wybrano element z Select Menu
        select_menu = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not select_menu or not select_menu.values:
            await interaction.response.send_message("⚠️ Najpierw wybierz zapis z listy!", ephemeral=True)
            return

        # Wartość to: "typ_zapisu-id_wiadomości"
        type_str, msg_id_str = select_menu.values[0].split('-')
        msg_id = int(msg_id_str)
        user_id = self.member_to_add.id
        
        # Znajdź właściwy słownik danych
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

        # Dodaj użytkownika
        participants.append(user_id)
        
        # Próbujemy odświeżyć wiadomość
        message = data_dict.get("message")
        if message and hasattr(message, 'edit'):
             if type_str == "airdrop":
                # Musimy odtworzyć obiekt widoku
                view_obj = AirdropView(msg_id, message.embeds[0].description, message.guild.get_channel(data_dict["channel_id"]), message.embeds[0].footer.text.replace("Wystawione przez ", ""))
                view_obj.participants = participants
                # Zmieniamy treść w globalnej pamięci
                airdrops[msg_id]["participants"] = participants
                await message.edit(embed=view_obj.make_embed(message.guild), view=view_obj)
             # W przypadku Captures, musimy tylko dodać ID do pamięci
             elif type_str == "captures":
                 captures[msg_id]["participants"] = participants
             # Eventy Zancudo/Cayo nie mają interaktywnego embeda, więc wystarczy dodanie do pamięci.
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
