import asyncio
import os
import random
import discord
from discord.ext import commands
from keep_alive import keep_alive

bot = commands.Bot('Q ', description='iQ Bot')
Bot = commands.Bot(command_prefix="")

showlist = ['Moderation']



@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=random.choice(showlist)))
    print(bot.user.id)

@bot.command()
async def ping(ctx):
    ping = round(bot.latency*1000)
    await ctx.send(f"{ctx.author.mention} The ping of this bot is {ping} ms")



keep_alive()
token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)
