import asyncio
import os
import random
import discord
from datetime import datetime
from discord.ext import commands
#from tox_block.prediction import make_single_prediction
from keep_alive import keep_alive

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

cred = credentials.Certificate('FrBase.json')
firebase_admin.initialize_app(cred)

db = firestore.client()

#https://discord.com/api/oauth2/authorize?client_id=743495325968498689&permissions=8&scope=bot

bot = commands.Bot('Q ', description='iQ Bot',case_insensitive=True )
colors=[0xCABDA6,0x908775,0xF4E6C9,0x5B574F,0x6D5F42,0xBBA475]
showlist = ['ESSENTIAL']
@bot.event
async def on_guild_join(guild):
  doc_ref = db.collection(u'Servers').document(str(guild.id))
  if doc_ref.get().exists:
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            await channel.send(':)')
        break
  else:
    dt_string = datetime.now().strftime("%d/%m/%Y")
    doc_ref.set({
      u'ID': str(guild.id),
      u'PG': u'No',
      u'Credits': 10,
      u'ModerationChannel': 'None',
      u'Warns': 3,
      u'Joined': dt_string,
    })
          

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=random.choice(showlist)))
    print(bot.user.id)
    #for guild in bot.guilds:
    #  if guild.name == '743495325968498689':
    #    break


'''
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
      embed = discord.Embed(title="Message Flagged", description=f"Message bad", color=0xFFCD00)
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
      embed.set_footer(text="A Synapse Bot")
      await channel.send(embed = embed)
    else:
      print(f'Approved {round(toxic, 2)}')
  except:
    pass
  await bot.process_commands(message)
'''

@bot.command()
async def ping(ctx):
    ping = round(bot.latency*1000)
    await ctx.send(f"{ctx.author.mention} The ping of this bot is {ping} ms")

@bot.command()
async def Add(ctx,choice='none',field='none'):  
  if choice == 'none':
    await ctx.send('```You need to specify what to add```')
  if choice == 'ModLog':
    guild = ctx.message.guild
    overwrites = {
          guild.default_role: discord.PermissionOverwrite(send_messages=False),
          guild.me: discord.PermissionOverwrite(send_messages=True)
    }
    await guild.create_text_channel('iq-log', overwrites=overwrites)

@bot.command()
async def Set(ctx,choice='none',field='none'):  
  if choice == 'none':
    await ctx.send('```You need to specify what to set```')
  if choice == 'ModLog':
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    doc_ref.set({
      u'ModerationChannel': str(field),
    },merge=True)

@bot.command()
async def server(ctx):
    await ctx.send(ctx.guild.id)

@bot.command()
async def clear(ctx, amount=5):
    amount = amount + 1
    upperLimit = 59
    if amount > upperLimit:
        await ctx.send("`Clears cannot excced 59`")

    if upperLimit >= amount:
        await ctx.channel.purge(limit=amount)
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        if doc_ref.get().exists:
          server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
          modchannel = bot.get_channel(int(server))
          embed = discord.Embed(title=f"Cleared", description= f"{ctx.author.name} Deleted {amount} messages",color=0x4BC3FF)
          await modchannel.send(embed=embed)

@bot.command(pass_context=True)
async def warn(ctx, member: discord.Member, *, content):
    channel = await member.create_dm()
    embed = discord.Embed(
        title="Warning", description="You are receiving a warning for the following reason: " + content + " If you keep up this behavior it may result in a kick/ban.", color=0xFFFF4B)
    await asyncio.sleep(1)
    await channel.send(embed=embed)
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    if doc_ref.get().exists:
      server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
      modchannel = bot.get_channel(int(server))
      embed = discord.Embed(title=f"Warned", description= f"{member.mention} has been warned for {content} by {ctx.author.mention}",color=0xFFFF4B)
      await modchannel.send(embed=embed)

@bot.command()
async def kick(ctx, member: discord.Member, reason=None):
    if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! !kick <User> <Reason>', color=0xFF7373)

        await ctx.send(embed=embed)
    else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Kicked", description="You are receiving a Kick for the following reason: " + reason , color=0xFF7373)
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        if doc_ref.get().exists:
          server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
          modchannel = bot.get_channel(int(server))
          embed = discord.Embed(title=f"Kicked", description= f"{member.mention} has been kicked for {reason} by {ctx.author.mention}",color=0xFF7373)
          await modchannel.send(embed=embed)
        await member.kick()
        embed = discord.Embed(
            title="Removed", description=f"Successfully kicked {member} for {reason}", color=0xFF7373)

        await ctx.send(embed=embed)

@bot.command()
async def ban(ctx, member: discord.Member, reason=None):
    if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! !ban <User> <Reason>', color=0xFF4B4B)

        await ctx.send(embed=embed)
    else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Banned", description="You are receiving a BAN for the following reason: " + reason , color=0xFF4B4B)
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        if doc_ref.get().exists:
          server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
          modchannel = bot.get_channel(int(server))
          embed = discord.Embed(title=f"Banned", description= f"{member.mention} has been banned for {reason} by {ctx.author.mention}",color=0xFF4B4B)
          await modchannel.send(embed=embed)
        await member.ban()
        embed = discord.Embed(
            title="BANNED", description=f"Successfully banned {member} for {reason}", color=0xFF4B4B)

        await ctx.send(embed=embed)

@bot.command()
async def HelpMe(ctx):
  await ctx.send(f'<@{ctx.author.id}> How can I help you?')

@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.errors.CommandError):
    await ctx.send(f'```{error}```')

keep_alive()
token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)  
