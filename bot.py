import asyncio
import os
import random
import discord
from discord.ext import commands
from tox_block.prediction import make_single_prediction

bot = commands.Bot('Q ', description='iQ Bot')

showlist = ['Support Bot']

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=random.choice(showlist)))
    print(bot.user.id)

@bot.event
async def on_message(message):
    try:
      aimessage = make_single_prediction(message.content, rescale=True)
      print(message.content)
      toxic = aimessage["toxic"]
      severe_toxic = aimessage["severe_toxic"]
      obscene = aimessage["obscene"]
      threat = aimessage["threat"]
      insult = aimessage["insult"]
      if round(toxic, 2) > 0.8:
        print(f'Bad {toxic * 100}%')
      else:
        print('Approved')
    except:
      pass

@bot.command()
async def ping(ctx):
    ping = round(bot.latency*1000)
    await ctx.send(f"{ctx.author.mention} The ping of this bot is {ping} ms")

@bot.command()
async def Help(ctx):
  await ctx.send(f'<@{ctx.author.id}> How can I help you?')


@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.errors.CommandError):
    await ctx.send(f'```{error}```')

token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)  
