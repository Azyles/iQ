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
  channel = message.channel
  try:
    aimessage = make_single_prediction(message.content, rescale=True)
    toxic = aimessage["toxic"]
    severe_toxic = aimessage["severe_toxic"]
    obscene = aimessage["obscene"]
    threat = aimessage["threat"]
    insult = aimessage["insult"]
    if round(toxic, 2) > 0.8:
      embed = discord.Embed(title="Message Review", description=f"Message bad", color=0xFFCD00)
      embed.set_thumbnail(url="https://i.imgur.com/79zZez6.png")
      embed.add_field(name="Toxic",
                      value=str(round(toxic, 2)), inline=False)
      embed.add_field(name="Severe Toxic",
                      value=str(round(severe_toxic, 2)), inline=False)
      embed.add_field(name="Insult",
                      value=str(round(insult, 2)), inline=False)
      embed.add_field(name="Obscene",
                      value=str(round(obscene, 2)), inline=False)
      embed.add_field(name="Threat",
                      value=str(round(threat, 2)), inline=False)
      embed.add_field(name="Important Links", value="f links", inline=False)
      embed.set_footer(text="iQ ")
      await channel.send(embed = embed)
    else:
      print(f'Approved {round(toxic, 2)}')
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
