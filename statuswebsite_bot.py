import os
import time
import asyncio
import datetime

import aiohttp
import discord
from discord.ext import tasks

# ================== SETTINGS (edit these) ==================
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = 1556199279377383425          # channel where logs are posted
WEBSITES = {
    "My Website": "https://taho.online/",  # name: url (add as many as you like)
    # "API": "https://api.example.com/health",
}
CHECK_INTERVAL = 60       # seconds between checks
TIMEOUT = 10              # seconds before a request counts as failed
FAILS_BEFORE_OFFLINE = 2  # consecutive failures needed to report OFFLINE
# ===========================================================

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# per-site state
state = {
    name: {"online": None, "fails": 0, "since": time.time()}
    for name in WEBSITES
}


async def check_site(session: aiohttp.ClientSession, url: str):
    """Return (is_online, detail)."""
    try:
        start = time.perf_counter()
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=TIMEOUT), allow_redirects=True
        ) as resp:
            ms = int((time.perf_counter() - start) * 1000)
            if resp.status < 400:
                return True, f"HTTP {resp.status} • {ms} ms"
            return False, f"HTTP {resp.status}"
    except asyncio.TimeoutError:
        return False, "Timed out"
    except Exception as e:
        return False, type(e).__name__


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)


async def post(channel, name, url, online, detail, downtime=None):
    embed = discord.Embed(
        title=f"{'🟢 ONLINE' if online else '🔴 OFFLINE'} — {name}",
        description=url,
        color=discord.Color.green() if online else discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Details", value=detail, inline=False)
    if downtime:
        embed.add_field(name="Was down for", value=downtime, inline=False)
    await channel.send(embed=embed)


@tasks.loop(seconds=CHECK_INTERVAL)
async def monitor():
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("Channel not found. Check CHANNEL_ID and bot permissions.")
        return

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *(check_site(session, url) for url in WEBSITES.values())
        )

    for (name, url), (up, detail) in zip(WEBSITES.items(), results):
        s = state[name]

        if up:
            s["fails"] = 0
            if s["online"] is None:            # first check after start
                s["online"], s["since"] = True, time.time()
                await post(channel, name, url, True, detail + " (monitoring started)")
            elif s["online"] is False:         # recovered
                down_for = fmt_duration(time.time() - s["since"])
                s["online"], s["since"] = True, time.time()
                await post(channel, name, url, True, detail, downtime=down_for)
        else:
            s["fails"] += 1
            if s["online"] is None and s["fails"] >= 1:   # offline at startup
                s["online"], s["since"] = False, time.time()
                await post(channel, name, url, False, detail + " (monitoring started)")
            elif s["online"] and s["fails"] >= FAILS_BEFORE_OFFLINE:
                s["online"], s["since"] = False, time.time()
                await post(channel, name, url, False, detail)


@monitor.before_loop
async def before_monitor():
    await client.wait_until_ready()


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    if not monitor.is_running():
        monitor.start()


client.run(BOT_TOKEN)
