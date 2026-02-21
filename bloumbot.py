"""
bloum - Discord QOL Bot
Color scheme: #264D37 (deep forest green)
Features: Welcome messages, sticky messages, auto-role, polls, purge, server info, and more.

Requirements:
    pip3 install discord.py

Setup:
    1. Create a bot at https://discord.com/developers/applications
    2. Enable MESSAGE CONTENT INTENT in the bot settings
    3. Set your BOT_TOKEN below (or use environment variable BLOUM_TOKEN)
    4. Invite bot with scopes: bot + applications.commands
    5. Required permissions: Manage Messages, Send Messages, Embed Links,
       Read Message History, Add Reactions, Manage Roles (for auto-role)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
import json
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()
# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv("BLOUM_TOKEN", "")
PREFIX = "!"
BLOUM_COLOR = 0x264D37  # deep forest green

# In-memory stores (replace with a DB for persistence across restarts)
sticky_messages: dict[int, dict] = {}   # channel_id -> {message_id, content}
welcome_config: dict[int, dict] = {}    # guild_id -> {channel_id, message}
auto_roles: dict[int, int] = {}         # guild_id -> role_id

# ─────────────────────────────────────────────
# BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def bloum_embed(title: str, description: str = "", color: int = BLOUM_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="bloum", icon_url="https://cdn.discordapp.com/avatars/1474203444939067633/8f9cfbf94f976e8cab531af3aeedef2f.png?size=1024")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

def error_embed(description: str) -> discord.Embed:
    return bloum_embed("Error", description, color=0xFF4C4C)

def success_embed(description: str) -> discord.Embed:
    return bloum_embed("Done", description)

# ─────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"bloum is online as {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"   Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"   Sync error: {e}")
    bloum_status.start()


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    # ── Welcome message ──────────────────────
    cfg = welcome_config.get(guild.id)
    if cfg:
        channel = guild.get_channel(cfg["channel_id"])
        if channel:
            msg = cfg["message"].replace("{user}", member.mention).replace("{server}", guild.name)
            embed = bloum_embed(f"Welcome to {guild.name}!", msg)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    # ── Auto-role ─────────────────────────────
    role_id = auto_roles.get(guild.id)
    if role_id:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role, reason="bloum auto-role")
            except discord.Forbidden:
                pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    # ── Sticky message logic ──────────────────
    channel_id = message.channel.id
    if channel_id in sticky_messages:
        sticky = sticky_messages[channel_id]
        # Delete old sticky
        try:
            old_msg = await message.channel.fetch_message(sticky["message_id"])
            await old_msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass
        # Re-post sticky at bottom
        embed = bloum_embed("Pinned Message", sticky["content"])
        new_msg = await message.channel.send(embed=embed)
        sticky_messages[channel_id]["message_id"] = new_msg.id


# ─────────────────────────────────────────────
# STATUS ROTATION
# ─────────────────────────────────────────────
STATUS_LIST = [
    discord.Game("with the server"),
    discord.Activity(type=discord.ActivityType.watching, name="Over the community"),
    discord.Game(f"{PREFIX}help for commands"),
]
_status_index = 0

@tasks.loop(seconds=30)
async def bloum_status():
    global _status_index
    await bot.change_presence(activity=STATUS_LIST[_status_index % len(STATUS_LIST)])
    _status_index += 1


# ─────────────────────────────────────────────
# PREFIX COMMANDS
# ─────────────────────────────────────────────

@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    embed = bloum_embed(
        "bloum — Command List",
        "A quality-of-life bot for your server."
    )
    embed.add_field(name="Setup (Admin)", value=(
        f"`{PREFIX}setwelcome #channel [message]` — Set welcome channel & message\n"
        f"`{PREFIX}clearwelcome` — Remove welcome config\n"
        f"`{PREFIX}sticky [message]` — Set sticky message in this channel\n"
        f"`{PREFIX}unsticky` — Remove sticky message\n"
        f"`{PREFIX}autorole @role` — Auto-assign role to new members\n"
        f"`{PREFIX}clearautorole` — Remove auto-role"
    ), inline=False)
    embed.add_field(name="Moderation", value=(
        f"`{PREFIX}purge [amount]` — Delete messages (default 10, max 100)\n"
        f"`{PREFIX}slowmode [seconds]` — Set slowmode (0 to disable)"
    ), inline=False)
    embed.add_field(name="Utility", value=(
        f"`{PREFIX}poll [question] | [opt1] | [opt2] ...` — Create a poll\n"
        f"`{PREFIX}serverinfo` — Show server info\n"
        f"`{PREFIX}userinfo [@user]` — Show user info\n"
        f"`{PREFIX}ping` — Bot latency\n"
        f"`{PREFIX}announce #channel [message]` — Send an announcement embed"
    ), inline=False)
    await ctx.send(embed=embed)


# ── PING ─────────────────────────────────────

@bot.command(name="ping")
async def ping(ctx: commands.Context):
    latency = round(bot.latency * 1000)
    await ctx.send(embed=bloum_embed("Pong!", f"Latency: **{latency}ms**"))


# ── WELCOME SETUP ─────────────────────────────

@bot.command(name="setwelcome")
@commands.has_permissions(manage_guild=True)
async def set_welcome(ctx: commands.Context, channel: discord.TextChannel, *, message: str = "Welcome to **{server}**, {user}!"):
    welcome_config[ctx.guild.id] = {"channel_id": channel.id, "message": message}
    await ctx.send(embed=success_embed(
        f"Welcome messages will be sent to {channel.mention}.\n\n"
        f"**Preview:**\n{message.replace('{user}', ctx.author.mention).replace('{server}', ctx.guild.name)}\n\n"
        f"*Use `{{user}}` for member mention and `{{server}}` for server name.*"
    ))

@bot.command(name="clearwelcome")
@commands.has_permissions(manage_guild=True)
async def clear_welcome(ctx: commands.Context):
    welcome_config.pop(ctx.guild.id, None)
    await ctx.send(embed=success_embed("Welcome messages disabled."))


# ── STICKY MESSAGES ───────────────────────────

@bot.command(name="sticky")
@commands.has_permissions(manage_messages=True)
async def sticky(ctx: commands.Context, *, content: str):
    # Remove old sticky if exists
    if ctx.channel.id in sticky_messages:
        try:
            old = await ctx.channel.fetch_message(sticky_messages[ctx.channel.id]["message_id"])
            await old.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    embed = bloum_embed("Pinned Message", content)
    msg = await ctx.channel.send(embed=embed)
    sticky_messages[ctx.channel.id] = {"message_id": msg.id, "content": content}

    confirm = await ctx.send(embed=success_embed(f"Sticky message set in {ctx.channel.mention}."))
    await asyncio.sleep(5)
    try:
        await confirm.delete()
        await ctx.message.delete()
    except discord.HTTPException:
        pass

@bot.command(name="unsticky")
@commands.has_permissions(manage_messages=True)
async def unsticky(ctx: commands.Context):
    if ctx.channel.id not in sticky_messages:
        return await ctx.send(embed=error_embed("No sticky message in this channel."))
    try:
        old = await ctx.channel.fetch_message(sticky_messages[ctx.channel.id]["message_id"])
        await old.delete()
    except (discord.NotFound, discord.HTTPException):
        pass
    sticky_messages.pop(ctx.channel.id)
    await ctx.send(embed=success_embed("Sticky message removed."))


# ── AUTO-ROLE ─────────────────────────────────

@bot.command(name="autorole")
@commands.has_permissions(manage_roles=True)
async def autorole(ctx: commands.Context, role: discord.Role):
    auto_roles[ctx.guild.id] = role.id
    await ctx.send(embed=success_embed(f"New members will automatically receive {role.mention}."))

@bot.command(name="clearautorole")
@commands.has_permissions(manage_roles=True)
async def clear_autorole(ctx: commands.Context):
    auto_roles.pop(ctx.guild.id, None)
    await ctx.send(embed=success_embed("Auto-role removed."))


# ── PURGE ─────────────────────────────────────

@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def purge(ctx: commands.Context, amount: int = 10):
    amount = min(max(amount, 1), 100)
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=amount)
    msg = await ctx.send(embed=success_embed(f"Deleted **{len(deleted)}** messages."))
    await asyncio.sleep(4)
    try:
        await msg.delete()
    except discord.HTTPException:
        pass


# ── SLOWMODE ──────────────────────────────────

@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx: commands.Context, seconds: int = 0):
    seconds = max(0, min(seconds, 21600))
    await ctx.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await ctx.send(embed=success_embed("Slowmode **disabled**."))
    else:
        await ctx.send(embed=success_embed(f"Slowmode set to **{seconds}s**."))


# ── POLL ─────────────────────────────────────

NUMBER_EMOJIS = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

@bot.command(name="poll")
async def poll(ctx: commands.Context, *, raw: str):
    """Usage: !poll Question | Option 1 | Option 2 | ..."""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 2:
        return await ctx.send(embed=error_embed(
            "Format: `!poll Question | Option 1 | Option 2 | ...`\n"
            "For a yes/no poll just do: `!poll Question`"
        ))

    question = parts[0]
    options = parts[1:]

    if len(options) > 10:
        return await ctx.send(embed=error_embed("Max 10 options allowed."))

    if len(options) == 1:
        # Treat as yes/no poll
        options = ["Yes", "No"]

    description = "\n".join(f"{NUMBER_EMOJIS[i]} {opt}" for i, opt in enumerate(options))
    embed = bloum_embed(f"{question}", description)
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    await ctx.message.delete()
    poll_msg = await ctx.send(embed=embed)

    for i in range(len(options)):
        await poll_msg.add_reaction(NUMBER_EMOJIS[i])


# ── SERVER INFO ───────────────────────────────

@bot.command(name="serverinfo")
async def serverinfo(ctx: commands.Context):
    g = ctx.guild
    embed = bloum_embed(f"{g.name}")
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Owner", value=g.owner.mention if g.owner else "Unknown")
    embed.add_field(name="Members", value=f"{g.member_count:,}")
    embed.add_field(name="Channels", value=str(len(g.channels)))
    embed.add_field(name="Roles", value=str(len(g.roles)))
    embed.add_field(name="Boosts", value=f"{g.premium_subscription_count} (Tier {g.premium_tier})")
    embed.add_field(name="Created", value=f"<t:{int(g.created_at.timestamp())}:D>")
    embed.add_field(name="Verification", value=str(g.verification_level).title())
    await ctx.send(embed=embed)


# ── USER INFO ─────────────────────────────────

@bot.command(name="userinfo")
async def userinfo(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = bloum_embed(f"👤 {member.display_name}")
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Username", value=str(member))
    embed.add_field(name="ID", value=str(member.id))
    embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Unknown")
    embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:D>")
    embed.add_field(name="Bot", value="Yes" if member.bot else "No")
    embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles) if roles else "None", inline=False)
    await ctx.send(embed=embed)


# ── ANNOUNCE ──────────────────────────────────

@bot.command(name="announce")
@commands.has_permissions(manage_messages=True)
async def announce(ctx: commands.Context, channel: discord.TextChannel, *, message: str):
    embed = bloum_embed("Announcement", message)
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await channel.send(embed=embed)
    await ctx.send(embed=success_embed(f"Announcement sent to {channel.mention}."))


# ── SAY ───────────────────────────────────────

@bot.command(name="say")
@commands.has_permissions(manage_messages=True)
async def say(ctx: commands.Context, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)


# ─────────────────────────────────────────────
# ERROR HANDLING
# ─────────────────────────────────────────────

@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=error_embed("You don't have permission to use this command."))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=error_embed(f"Missing argument: `{error.param.name}`.\nSee `{PREFIX}help` for usage."))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=error_embed(f"Invalid argument. See `{PREFIX}help` for usage."))
    elif isinstance(error, commands.CommandNotFound):
        pass  # Silently ignore unknown commands
    else:
        await ctx.send(embed=error_embed(f"An unexpected error occurred: `{error}`"))
        raise error


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

bot.run(BOT_TOKEN)