import asyncio
import os
import random
import discord
from datetime import datetime
from discord.ext import commands
#from tox_block.prediction import make_single_prediction
from keep_alive import keep_alive
import time
import platform
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import logzero
from logzero import logger

cred = credentials.Certificate('FrBase.json')
firebase_admin.initialize_app(cred)

db = firestore.client()

play_next_song = asyncio.Event()
songs = asyncio.Queue()
#https://discord.com/api/oauth2/authorize?client_id=743495325968498689&permissions=8&scope=bot

#uptime
start = time.time()

bot = commands.Bot('Q ', description='iQ Bot',case_insensitive=True )
colors=[0xD0BCAB,0xB9AA9E ]
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
    try:
      await guild.create_role(name="Muted")
    except:
      pass    

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=random.choice(showlist)))
    print(bot.user.id)
    #for guild in bot.guilds:
    #  if guild.name == '743495325968498689':
    #    break
    start = time.time()



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
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Cleared", description= f"{ctx.author.name} Deleted {amount} messages",color=random.choice(colors))
            embed.set_footer(text="iQ Bot : Q Help")
            await modchannel.send(embed=embed)
        except:
          pass
@bot.command(pass_context=True)
async def warn(ctx, member: discord.Member, *, content):
    channel = await member.create_dm()
    embed = discord.Embed(
        title="Warning", description="You are receiving a warning for the following reason: " + content + " If you keep up this behavior it may result in a kick/ban.", color=random.choice(colors))
    await asyncio.sleep(1)
    embed.set_footer(text="iQ Bot : Q Help")
    await channel.send(embed=embed)
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
      if doc_ref.get().exists:
        server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
        modchannel = bot.get_channel(int(server))
        embed = discord.Embed(title=f"Warned", description= f"{member.mention} has been warned for {content} by {ctx.author.mention}",color=random.choice(colors))
        embed.set_footer(text="iQ Bot : Q Help")
        await modchannel.send(embed=embed)
    except:
      pass

@bot.command()
async def kick(ctx, member: discord.Member, reason=None):
    if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! !kick <User> <Reason>', color=random.choice(colors))
        embed.set_footer(text="iQ Bot : Q Help")
        await ctx.send(embed=embed)
    else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Kicked", description="You are receiving a Kick for the following reason: " + reason , color=random.choice(colors))
          embed.set_footer(text="iQ Bot : Q Help")
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Kicked", description= f"{member.mention} has been kicked for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot : Q Help")
            await modchannel.send(embed=embed)
          await member.kick()
          embed = discord.Embed(
              title="Removed", description=f"Successfully kicked {member} for {reason}", color=random.choice(colors))
          embed.set_footer(text="iQ Bot : Q Help")
          await ctx.send(embed=embed)
        except:
          pass
          
@bot.command()
async def ban(ctx, member: discord.Member, reason=None):
    if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! !ban <User> <Reason>', color=random.choice(colors))
        embed.set_footer(text="iQ Bot : Q Help")
        await ctx.send(embed=embed)
    else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Banned", description="You are receiving a BAN for the following reason: " + reason , color=random.choice(colors))
          embed.set_footer(text="iQ Bot : Q Help")
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Banned", description= f"{member.mention} has been banned for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot : Q Help")
            await modchannel.send(embed=embed)
          await member.ban()
          embed = discord.Embed(
              title="BANNED", description=f"Successfully banned {member} for {reason}", color=random.choice(colors))
          embed.set_footer(text="iQ Bot : Q Help")
          await ctx.send(embed=embed)
        except:
          pass
          
@bot.command()
async def HelpMe(ctx):
  await ctx.send(f'<@{ctx.author.id}> How can I help you?')


@bot.command()
async def dm(ctx, server: int, * message):
  channel = bot.get_channel(server)
  await channel.send(message)


@bot.event
async def on_message(message):
  role = discord.utils.find(lambda r: r.name == 'Muted', message.guild.roles)
  if role in message.author.roles:
    await message.delete()
    try:
      channel = await message.author.create_dm()
      embed = discord.Embed(
        title="Muted", description="You are muted in the channel! Messages you send will be deleted immediately.", color=0x00FFCD)
      embed.set_footer(text="iQ Bot : Q Help")
      await asyncio.sleep(1)
      await channel.send(embed=embed)
    except:
      pass
  else:
    await bot.process_commands(message)

@bot.command()
async def Mute(ctx,member: discord.Member):
  role = discord.utils.get(ctx.guild.roles, name="Muted")
  await member.add_roles(role)

@bot.command()
async def Requst(ctx, * message):
  #await member.add_roles(role)
  await ctx.send(message)


@bot.command()
async def Host(ctx):  
  done = time.time()
  elapsed = done - start
  embed = discord.Embed(title="ACTIVE", description= "Specs",color=random.choice(colors))
  ping = round(bot.latency * 1000)
  #embed.set_thumbnail(url="https://i.imgur.com/c6nh2sN.png")
  embed.add_field(name="Machine",
                    value=str(platform.machine()), inline=False)
  embed.add_field(name="Version",
                    value=str(platform.version()), inline=False)
  embed.add_field(name="Platform",
                    value=str(platform.platform()), inline=False)
  embed.add_field(name="System",
                    value=str(platform.system()), inline=False)
  embed.add_field(name="Processor",
                    value=str(platform.processor()), inline=False)
  embed.add_field(name="Ping",
                    value=str(ping), inline=False)
  embed.add_field(name="Uptime",
                    value=str(round(elapsed,2)), inline=False)     
  try:
    doc_ref = db.collection(u'ServerData').document(u'Settings')
    if doc_ref.get().exists:
      embed.add_field(name="Server",
                        value='Online', inline=False)                    
    else:
      embed.add_field(name="Server",
                        value='Offline', inline=False)
  except:
    pass
  embed.set_footer(text="iQ Bot : Q Help")
  await ctx.send(embed=embed)



@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.errors.CommandError):
    await ctx.send(f'```{error}```')
  logzero.logfile("rotating-logfile.log", maxBytes=1e6, backupCount=3)
  # Log messages
  logger.error(f'{ctx.author.id}: {error}')
  print(f'{ctx.author.id}: {error}')


extensions = [
	#'cogs.cogs'  # Same name as it would be if you were importing it
]

if __name__ == '__main__':  # Ensures this is the file being ran
	for extension in extensions:
		bot.load_extension(extension)  # Loades every extension.


keep_alive()
token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)  
