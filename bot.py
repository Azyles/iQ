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
import logging
import requests, json
from datetime import date

cred = credentials.Certificate('FrBase.json')
firebase_admin.initialize_app(cred)

city_name = 'Monterey'
api_key = "549b0eaf0ba1e27619cf96fb0ba32a1b"
base_url = "http://api.openweathermap.org/data/2.5/weather?"

db = firestore.client()

play_next_song = asyncio.Event()
songs = asyncio.Queue()
#https://discord.com/api/oauth2/authorize?client_id=743495325968498689&permissions=8&scope=bot

#uptime
start = time.time()

bot = commands.Bot('Q ', description='iQ Bot',case_insensitive=True )
colors=[0xD0BCAB,0xB9AA9E ]
showlist = ['ESSENTIAL']
bot.remove_command('help')

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
async def Get(ctx,choice='none',field='none'):  
  if choice == 'none':
    await ctx.send('```You need to specify what to Get```')
  if choice == 'Channel':
    await ctx.send(f'`{ctx.message.channel.name}: {ctx.message.channel.id}`')

@bot.command()
async def Set(ctx,choice='none',field='none'):  
  if choice == 'none':
    await ctx.send('```You need to specify what to set```')
  if choice == 'ModLog':
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    doc_ref.set({
      u'ModerationChannel': str(field),
    },merge=True)
    await bot.get_channel(field).send('`Mod Log Successfully Set`')

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
async def Invite(ctx, member: discord.Member):
    channel = await member.create_dm()
    #creating invite link
    invitelink = await ctx.channel.create_invite(max_uses=1,unique=True)
    #dming it to the person
    await channel.send(invitelink)

@bot.command()
async def Feedback(ctx, * message):
  today = date.today()
  datetoday = today.strftime("%m/%d/%y")
  logzero.logfile("feedback.log", maxBytes=10000, backupCount=3)
  logger.info(f"{datetoday} {ctx.author.id} {message}")
  channel = await ctx.author.create_dm()
  await channel.send('Thanks for the feedback')
  time.sleep(5)
  await channel.send(f'Received`{datetoday} {ctx.author.id} {message}`')


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


@bot.command()
async def Weather(ctx, *, City):
    complete_url = base_url + "appid=" + api_key + "&q=" + City
    response = requests.get(complete_url)
    x = response.json()
    if x["cod"] != "404": 
        y = x["main"] 
        current_temperature = str(round(y["temp"]-273.15,2))
        current_pressure = y["pressure"] 
        current_humidiy = y["humidity"]
        min_temp = format(round(y["temp_min"]-273.15,2))
        max_temp = format(round(y["temp_max"]-273.15,2))
        feels_like = format(round(y["feels_like"]-273.15,2))
        z = x["weather"] 
        icon = z[0]["icon"]
        weather_description = z[0]["description"] 
        weather_main = z[0]["main"] 
        w = x["wind"]
        wind = w["speed"]
        wind_deg = w["deg"]

        def faren(tem):
          tem = float(tem)
          return str(round(tem*9/5+32,2))

        def degDir(d):
          dirs = ['N', 'N/NE', 'NE', 'E/NE', 'E', 'E/SE', 'SE', 'S/SE', 'S', 'S/SW', 'SW', 'W/SW', 'W', 'W/NW', 'NW', 'N/NW']
          ix = round(d / (360. / len(dirs)))
          return dirs[ix % len(dirs)]


        embed = discord.Embed(
            title=City,
            description=
            "Synapse Weather gets information with the help of openweathermap.org",
            color=random.choice(colors))
        embed.set_author(
            name='Synapse', url="https://synapsebot.netlify.app")
        embed.set_thumbnail(url="https://i.imgur.com/Q66BhxI.png")

        embed.add_field(
            name="Temperature",
            value= current_temperature + "°C - " + str(faren(current_temperature)) + "°F",
            inline = False)
        
        embed.add_field(
            name="Feels Like",
            value=feels_like + "°C - " + str(faren(feels_like)) + "°F",
            inline=False)
        embed.add_field(
            name="Minimum Temperature",
            value=min_temp + "°C - " + str(faren(min_temp)) + "°F",
            inline=False)
        
        embed.add_field(
            name="Maximum Temperature",
            value=max_temp + "°C - " + str(faren(max_temp)) + "°F",
            inline=False)

        embed.add_field(
            name="Wind",
            value=str(wind) + " mph " + str(degDir(wind_deg)),inline=False)
            
        embed.add_field(
            name="Humidity", value= str(current_humidiy) + "%", inline=False)

        embed.add_field(
            name="Atmospheric Pressure",
            value= str(current_pressure) + " hPa",
            inline=False)
          
        embed.add_field(
            name="Description",
            value=weather_description,inline=False)

        await ctx.send(embed=embed)
    else: 
        embed = discord.Embed(
            title="Error", description="City Not Found", color=0xFF8080)
        await ctx.send(embed=embed)

@bot.command(pass_context=True)
async def Help(ctx):
    embed = discord.Embed(
        title="iQ", description="iQ is the ultimate moderation bot! It has everything relating to server management. ", color=random.choice(colors))
    await asyncio.sleep(1)
    embed.set_footer(text="iQ Bot by Synapse")
    embed.add_field(name="Delete Messages", value="`Q Clear (amount)`", inline=False)
    embed.add_field(name="Warn", value="`Q Warn (mention user) (reason)`", inline=False)
    embed.add_field(name="Kick", value="`Q Kick (mention user) (reason)`", inline=False)
    embed.add_field(name="Ban", value="`Q Ban (mention user) (reason)`", inline=False)
    embed.add_field(name="Ban", value="`Q Mute (mention user)`", inline=False)
    embed.add_field(name="Weather", value="`Q Weather (City)`", inline=False)
    embed.add_field(name="Invite to Server", value="`Q Invite`", inline=False)
    embed.add_field(name="Advanced Commands", value="------------", inline=False)
    embed.add_field(name="Get Channel ID", value="`Q Get Channel`", inline=False)
    embed.add_field(name="Set ModLog", value="`Q Set ModLog (channel id)`", inline=False)
    embed.add_field(name="Host Information", value="`Q Host`  ", inline=False)
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
