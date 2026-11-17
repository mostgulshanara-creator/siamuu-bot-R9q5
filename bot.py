import os
import math
import random
import time
import io
import aiohttp
import discord
import aiosqlite

from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont

# ==============================
# SIAMUUU BOT CONFIGURATION
# ==============================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE = "siamuu_xp.db"

MESSAGE_XP_MIN = 15
MESSAGE_XP_MAX = 25
MESSAGE_COOLDOWN = 60

VOICE_XP_PER_MINUTE = 5
DAILY_XP = 100

# Level reward roles configuration
ROLE_REWARDS = {
    5: 1572305312248111134,    # 🥉『𝐁𝐑𝐎𝐍𝐙𝐄』
    10: 1572305712309207040,   # 🥈『𝐒𝐈𝐋𝐕𝐄𝐑』
    20: 1572306206012346448,   # 🥇『𝐆𝐎𝐋𝐃』
    50: 1572306274924757002,   # 💎『𝐃𝐈𝐀𝐌𝐎𝐍𝐃』
    100: 1572306323247206490   # 🔥『𝐍𝐄𝐓𝐇𝐄𝐑𝐈𝐓𝐄』
}

# ==============================
# BOT SETUP
# ==============================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

db = None


# ==============================
# DATABASE
# ==============================

async def setup_database():
    global db

    if db is None:
        db = await aiosqlite.connect(DATABASE)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                guild_id INTEGER,
                user_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                last_message REAL DEFAULT 0,
                last_daily REAL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        await db.commit()


async def get_user(guild_id, user_id):
    await setup_database()

    async with db.execute(
        "SELECT xp, level, last_message, last_daily "
        "FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        await db.execute(
            "INSERT INTO users (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id)
        )
        await db.commit()

        return (0, 0, 0, 0)

    return row


async def get_user_rank(guild_id, user_id):
    await setup_database()
    async with db.execute("""
        SELECT user_id FROM users
        WHERE guild_id=?
        ORDER BY xp DESC
    """, (guild_id,)) as cursor:
        rows = await cursor.fetchall()
    
    for index, row in enumerate(rows, start=1):
        if row[0] == user_id:
            return index
    return len(rows)


# ==============================
# LEVEL SYSTEM & PERFECTED PNG CARD
# ==============================

def calculate_level(xp):
    return int(math.sqrt(xp / 100))


def xp_for_next_level(level):
    return 100 * ((level + 1) ** 2)


async def generate_level_up_card(member, old_level, new_level, rank_num, current_xp):
    width, height = 750, 210
    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    radius = 30
    # সঠিক কাঠামোর ভেতরে ব্যাকগ্রাউন্ড ও বর্ডার ড্র করা যাতে বাইরে না যায়
    draw.rounded_rectangle([(2, 2), (width - 3, height - 3)], radius, fill=(15, 15, 22, 255))
    draw.rounded_rectangle([(2, 2), (width - 3, height - 3)], radius, outline=(0, 180, 255, 120), width=2)

    avatar_url = member.display_avatar.replace(size=128, format="png").url
    avatar_img = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()
                    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    except Exception:
        pass

    if avatar_img:
        avatar_img = avatar_img.resize((130, 130), Image.Resampling.LANCZOS)
        
        mask = Image.new("L", (130, 130), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 130, 130), fill=255)
        
        card.paste(avatar_img, (35, 40), mask)
        draw.ellipse((33, 38, 166, 172), outline=(0, 162, 255), width=4)

    try:
        font_title = ImageFont.truetype("arial.ttf", 32)
        font_name = ImageFont.truetype("arial.ttf", 22)
        font_med = ImageFont.truetype("arial.ttf", 22)
        font_bold = ImageFont.truetype("arial.ttf", 36)
    except IOError:
        font_title = ImageFont.load_default()
        font_name = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    username = member.display_name
    if len(username) > 15:
        username = username[:15] + "..."
        
    draw.text((185, 38), "LEVEL UP!", fill=(0, 220, 255), font=font_title)
    draw.text((185, 80), f"{username}", fill=(200, 200, 210), font=font_name)

    # লেভেল আপ বক্স
    draw.rounded_rectangle([(445, 35), (595, 105)], 20, fill=(25, 25, 35, 255))
    
    draw.text((462, 50), str(old_level), fill=(130, 130, 140), font=font_med)
    draw.text((502, 48), "->", fill=(0, 162, 255), font=font_med)
    draw.text((538, 46), str(new_level), fill=(0, 255, 120), font=font_bold)

    # র‍্যাংক ব্যাজ
    draw.rounded_rectangle([(615, 35), (715, 105)], 20, fill=(35, 25, 45, 255))
    draw.text((635, 48), f"#{rank_num}", fill=(255, 180, 0), font=font_bold)

    # প্রোগ্রেস বার (ফিক্সড ও স্মিথ রেন্ডারিং)
    bar_x, bar_y, bar_w, bar_h = 185, 145, 530, 18
    draw.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], 9, fill=(30, 30, 40, 255))
    
    curr_lvl_xp = 100 * (new_level ** 2)
    next_lvl_xp = xp_for_next_level(new_level)
    needed = next_lvl_xp - curr_lvl_xp
    gained = current_xp - curr_lvl_xp
    
    if needed <= 0:
        pct = 1.0
    else:
        pct = max(0.05, min(1.0, gained / needed)) # মিনিমাম ৫% ভিজুয়াল ফিল রাখবে যাতে সবসময় বার দেখা যায়
        
    filled_w = int(bar_w * pct)
    if filled_w > 9:
        draw.rounded_rectangle([(bar_x, bar_y), (bar_x + filled_w, bar_y + bar_h)], 9, fill=(0, 162, 255, 255))

    draw.text((185, 175), f"Total XP: {current_xp:,}", fill=(150, 150, 160), font=font_name)

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def award_xp(member, amount, announce_channel=None):
    if member.bot or member.guild is None:
        return

    await setup_database()

    old_xp, old_level, last_message, last_daily = await get_user(
        member.guild.id,
        member.id
    )

    new_xp = old_xp + amount
    new_level = calculate_level(new_xp)

    await db.execute("""
        UPDATE users
        SET xp=?, level=?
        WHERE guild_id=? AND user_id=?
    """, (new_xp, new_level, member.guild.id, member.id))

    await db.commit()

    if new_level > old_level:
        channel = announce_channel or member.guild.system_channel

        if channel is None:
            channel = next(
                (
                    c for c in member.guild.text_channels
                    if c.permissions_for(member.guild.me).send_messages
                ),
                None
            )

        if channel:
            rank_num = await get_user_rank(member.guild.id, member.id)
            card_buffer = await generate_level_up_card(member, old_level, new_level, rank_num, new_xp)
            
            file = discord.File(card_buffer, filename="levelup.png")
            await channel.send(content=f"🎉 Congratulations {member.mention}!", file=file)

        new_role_id = ROLE_REWARDS.get(new_level)

        if new_role_id:
            role_to_add = member.guild.get_role(new_role_id)
            if role_to_add:
                all_reward_role_ids = list(ROLE_REWARDS.values())
                roles_to_remove = []

                for rid in all_reward_role_ids:
                    if rid != new_role_id:
                        r = member.guild.get_role(rid)
                        if r and r in member.roles:
                            roles_to_remove.append(r)

                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Higher rank obtained, removing previous XP rank roles.")

                if role_to_add not in member.roles:
                    await member.add_roles(role_to_add, reason=f"Reached level {new_level}")

    return new_xp, new_level


# ==============================
# MESSAGE XP
# ==============================

@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    await setup_database()

    user_data = await get_user(
        message.guild.id,
        message.author.id
    )

    last_message = user_data[2]
    current_time = time.time()

    if current_time - last_message >= MESSAGE_COOLDOWN:
        amount = random.randint(
            MESSAGE_XP_MIN,
            MESSAGE_XP_MAX
        )

        await db.execute("""
            UPDATE users
            SET last_message=?
            WHERE guild_id=? AND user_id=?
        """, (
            current_time,
            message.guild.id,
            message.author.id
        ))

        await db.commit()

        await award_xp(
            message.author,
            amount,
            message.channel
        )

    await bot.process_commands(message)


# ==============================
# VOICE XP
# ==============================

@tasks.loop(minutes=1)
async def voice_xp_loop():
    for guild in bot.guilds:
        for channel in guild.voice_channels:
            for member in channel.members:
                if member.bot:
                    continue

                if member.voice.self_deaf or member.voice.deaf:
                    continue

                await award_xp(
                    member,
                    VOICE_XP_PER_MINUTE
                )


@voice_xp_loop.before_loop
async def before_voice_xp():
    await bot.wait_until_ready()


# ==============================
# AUTOMATIC DAILY XP
# ==============================

@tasks.loop(hours=1)
async def automatic_daily_xp():
    await setup_database()
    current_time = time.time()

    for guild in bot.guilds:
        async with db.execute("""
            SELECT user_id, last_message, last_daily
            FROM users
            WHERE guild_id=?
        """, (guild.id,)) as cursor:
            users = await cursor.fetchall()

        for user_id, last_message, last_daily in users:
            if current_time - last_message > 86400:
                continue

            if current_time - last_daily < 86400:
                continue

            member = guild.get_member(user_id)
            if member is None or member.bot:
                continue

            await db.execute("""
                UPDATE users
                SET last_daily=?
                WHERE guild_id=? AND user_id=?
            """, (current_time, guild.id, user_id))
            await db.commit()

            await award_xp(member, DAILY_XP)
            print(f"Automatic daily XP: {member.name} received {DAILY_XP} XP")


@automatic_daily_xp.before_loop
async def before_automatic_daily_xp():
    await bot.wait_until_ready()


# ==============================
# RANK COMMAND
# ==============================

@bot.tree.command(
    name="rank",
    description="Check your XP and level"
)
@app_commands.describe(member="Member whose rank you want to see")
async def rank(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    member = member or interaction.user

    xp, level, _, _ = await get_user(
        interaction.guild.id,
        member.id
    )

    next_level_xp = xp_for_next_level(level)
    current_level_xp = 100 * (level ** 2)

    progress = xp - current_level_xp
    required = next_level_xp - current_level_xp

    percentage = int(progress / required * 100) if required > 0 else 100

    filled = max(1, int(percentage / 10)) if percentage > 0 else 0
    filled = min(filled, 10)
    progress_bar = "🟩" * filled + "⬛" * (10 - filled)

    embed = discord.Embed(
        title="🏆 SIAMUUU RANK",
        color=discord.Color.dark_grey()
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=member.mention, inline=False)
    embed.add_field(name="Level", value=f"**{level}**", inline=True)
    embed.add_field(name="Total XP", value=f"**{xp:,}**", inline=True)
    embed.add_field(
        name="Progress",
        value=f"{progress_bar}\n{progress:,} / {required:,} XP ({percentage}%)",
        inline=False
    )
    embed.set_footer(text="SIAMUUU XP SYSTEM")

    await interaction.response.send_message(embed=embed)


# ==============================
# LEADERBOARD COMMAND
# ==============================

@bot.tree.command(
    name="leaderboard",
    description="See the server XP leaderboard"
)
async def leaderboard(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    await setup_database()

    async with db.execute("""
        SELECT user_id, xp, level
        FROM users
        WHERE guild_id=?
        ORDER BY xp DESC
        LIMIT 10
    """, (interaction.guild.id,)) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No XP data available yet!")
        return

    description = ""

    for position, row in enumerate(rows, start=1):
        user_id, xp, level = row
        member = interaction.guild.get_member(user_id)
        username = member.display_name if member else f"Unknown User ({user_id})"

        description += (
            f"**#{position}** {username} — "
            f"Level **{level}** · **{xp:,} XP**\n"
        )

    embed = discord.Embed(
        title="🏆 SIAMUUU LEADERBOARD",
        description=description,
        color=discord.Color.gold()
    )
    embed.set_footer(text="Top 10 XP Members")

    await interaction.response.send_message(embed=embed)


# ==============================
# GIVE XP COMMAND (ADMIN ONLY)
# ==============================

@bot.tree.command(
    name="givexp",
    description="Give XP to a member (Admin Only)"
)
@app_commands.describe(
    member="The member to give XP to",
    amount="Amount of XP to give"
)
@app_commands.default_permissions(administrator=True)
async def givexp(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You do not have permission to use this command!",
            ephemeral=True
        )
        return

    if amount <= 0:
        await interaction.response.send_message(
            "Please specify a positive XP amount!",
            ephemeral=True
        )
        return

    new_xp, new_level = await award_xp(member, amount, interaction.channel)

    embed = discord.Embed(
        title="✨ XP ADDED SUCCESSFULLY",
        description=(
            f"Successfully gave **{amount:,} XP** to {member.mention}!\n\n"
            f"• **New Total XP:** {new_xp:,}\n"
            f"• **Current Level:** {new_level}"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text="SIAMUUU XP SYSTEM")

    await interaction.response.send_message(embed=embed)


# ==============================
# TEST ANNOUNCEMENT CARD COMMAND (ADMIN ONLY)
# ==============================

@bot.tree.command(
    name="testlevelcard",
    description="Preview the level-up announcement card (Admin Only)"
)
@app_commands.describe(
    old_level="The previous level number",
    new_level="The new level number",
    member="Optional member to preview with"
)
@app_commands.default_permissions(administrator=True)
async def testlevelcard(
    interaction: discord.Interaction,
    old_level: int,
    new_level: int,
    member: discord.Member = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You do not have permission to use this command!",
            ephemeral=True
        )
        return

    target_member = member or interaction.user
    rank_num = await get_user_rank(interaction.guild.id, target_member.id)
    
    xp, _, _, _ = await get_user(interaction.guild.id, target_member.id)

    card_buffer = await generate_level_up_card(target_member, old_level, new_level, rank_num, xp)
    file = discord.File(card_buffer, filename="levelup.png")

    await interaction.response.send_message(
        content=f"🧪 **Enhanced Level-up Card Preview** for {target_member.mention}:",
        file=file
    )


# ==============================
# BOT READY
# ==============================

@bot.event
async def on_ready():
    await setup_database()

    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"✅ Synced commands for guild: {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync for {guild.name}: {e}")

    if not voice_xp_loop.is_running():
        voice_xp_loop.start()

    if not automatic_daily_xp.is_running():
        automatic_daily_xp.start()

    print("=" * 40)
    print("SIAMUUU BOT IS ONLINE!")
    print(f"Bot: {bot.user}")
    print(f"Servers: {len(bot.guilds)}")
    print("XP System: ACTIVE (Enhanced PNG Card Enabled)")
    print("=" * 40)


# ==============================
# START BOT
# ==============================

if not TOKEN:
    raise ValueError("Discord token not found in .env file!")

bot.run(TOKEN)