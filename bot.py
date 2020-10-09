import asyncio
import os
import random
import discord
from datetime import datetime
from discord.ext import commands
from discord.utils import get
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
from uptime import uptime

import youtube_dl
import functools
import itertools
import math
import uuid
from async_timeout import timeout

cred = credentials.Certificate('FrBase.json')
firebase_admin.initialize_app(cred)

city_name = 'Monterey'
api_key = "549b0eaf0ba1e27619cf96fb0ba32a1b"
base_url = "http://api.openweathermap.org/data/ 2.5/weather?"

db = firestore.client()

play_next_song = asyncio.Event()
songs = asyncio.Queue()
#https://discord.com/api/oauth2/authorize?client_id=743495325968498689&permissions=8&scope=bot

#uptime
start = time.time()

bot = commands.Bot(
    '&', description='Ultimate Moderation Bot', case_insensitive=True)
colors = [0xAD303F, 0xBE3B4A, 0x9D2533, 0xD83144]
showlist = ['& Help']
bot.remove_command('help')

# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'worstaudio/worst',
        'extractaudio': True,
        'audioformat': 'wav',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options':
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options':
        '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self,
                 ctx: commands.Context,
                 source: discord.FFmpegPCMAudio,
                 *,
                 data: dict,
                 volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '{0.title} by {0.uploader}'.format(self)

    @classmethod
    async def create_source(cls,
                            ctx: commands.Context,
                            search: str,
                            *,
                            loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(
            cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError(
                'Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError(
                    'Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(
            cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.
                                    format(webpage_url))

        return cls(
            ctx,
            discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS),
            data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return ', '.join(duration)


class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(
            title='Now Playing',
            description='```\n{0.source.title}\n```'.format(self),
            color=random.choice(colors)))

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(
                itertools.islice(self._queue, item.start, item.stop,
                                 item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(180):  # 3 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(
                embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage(
                'This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context,
                                error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='ForceJoin')
    async def _summon(self,
                      ctx: commands.Context,
                      *,
                      channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.

        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError(
                'You are neither connected to a voice channel nor specified a channel to join.'
            )

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        ctx.voice_state.volume = volume / 100
        await ctx.send('`Volume of the player set to {}%`'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name='pause')
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='resume')
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 3:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send(
                    '`Skip vote added, currently at {}/3`'.format(total_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.

        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('`Empty queue.`')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(
                ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [{1.source.title}]({1.source.url})\n'.format(
                i + 1, song)

        embed = (discord.Embed(
            color=random.choice(colors),
            description='{} tracks:\n\n{}'.format(
                len(ctx.voice_state.songs), queue)).set_footer(
                    text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('`Empty queue.`')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('`Empty queue.`')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.

        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('`Nothing being played at the moment.`')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')

    @commands.command(name='play')
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.

        If there are songs in the queue, this will be queued until the
        other songs finished playing.

        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        try:
            source = await YTDLSource.create_source(
                ctx, search, loop=self.bot.loop)
        except YTDLError as e:
            await ctx.send(
                'An error occurred while processing this request: {}'.
                format(str(e)))
        else:
            song = Song(source)

            await ctx.voice_state.songs.put(song)
            embed = embed = discord.Embed(
                description='```Added {} to queue```'.format(str(source)),
                color=random.choice(colors))
            await ctx.send(embed=embed)

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError(
                '`You are not connected to any voice channel.`')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError(
                    '`Bot is already in a voice channel.`')

@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, name=random.choice(showlist)))
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
            u'Pro': u'Base',
            u'Booster': u'None',
            u'Credits': 10,
            u'ModRole': 'None',
            u'WelcomeMessage': 'None',
            u'ModerationChannel': 'None',
            u'AutoRole': 'None',
            u'Warns': 3,
            u'Joined': dt_string,
        })
        try:
            await guild.create_role(name="Muted")
        except:
            pass
    
    for member in guild.members:
        docs = db.collection(u'UserData').document(str(member.id))
        if docs.get().exists:
            pass
        else:
            if member.bot:
                pass
            else:
                dt_string = datetime.now().strftime("%d/%m/%Y")
                try:     
                  docs.set({
                      u'ID': str(member.id),
                      u'Pro': u'Base',
                      u'Boosts': 0,
                      u'Level': 1,
                      u'Job': u'None',
                      u'Cash': 100,
                      u'XP': 0,
                      u'Joined': dt_string,
                      u'Claimed': dt_string,
                  })
                except: 
                  pass

@bot.command()
async def setupacount(ctx):
    for member in ctx.guild.members:
        docs = db.collection(u'UserData').document(str(member.id))
        if docs.get().exists:
            pass
        else:
            if member.bot:
                pass
            else:
                print(f"Creating account for: {member.name}")
                dt_string = datetime.now().strftime("%d/%m/%Y")
                docs.set({
                      u'ID': str(member.id),
                      u'Pro': u'Base',
                      u'Boosts': 0,
                      u'Level': 1,
                      u'Job': u'None',
                      u'Cash': 100,
                      u'XP': 0,
                      u'Joined': dt_string,
                      u'Claimed': dt_string,
                })
                print(f"{member.name} is in")
    await ctx.channel.purge(limit=1)

@bot.command()
async def daily(ctx):
  docs = db.collection(u'UserData').document(str(ctx.author.id))
  claimed = u'{}'.format(docs.get({u'Claimed'}).to_dict()['Claimed']) 
  dt_string = datetime.now().strftime("%d/%m/%Y")
  if str(claimed) == dt_string:
    await ctx.send('`You can only claim every 24 hours!`')
  else:  
    cash = u'{}'.format(docs.get({u'Cash'}).to_dict()['Cash'])
    level = u'{}'.format(docs.get({u'Level'}).to_dict()['Level'])
    if int(level) < 11:
      earning = random.randrange(0, 11)
    else:
      earning = random.randrange(0, int(level))
    cash = int(cash) + earning
    docs.set({
      u'Cash': cash,
      u'Claimed': dt_string,
    },merge=True)
    embed = discord.Embed(
        title="Daily Claimed",
        description=f'You were paid ${str(earning)}. Check back tomorrow!',
        color=random.choice(colors))
    await ctx.send(embed=embed)
    
@bot.command()
async def ping(ctx):
    ping = round(bot.latency * 1000)
    await ctx.send(f"{ctx.author.mention} The ping of this bot is {ping} ms")

@bot.command()
async def Play(ctx):
    await ctx.send("Music Commands disabled until further notice!")

@bot.command()
async def Add(ctx, choice='none', field='Mod'):
    if choice == 'none':
        await ctx.send('```You need to specify what to add```')
    if choice == 'ModLog':
        guild = ctx.message.guild
        overwrites = {
            guild.default_role:
            discord.PermissionOverwrite(send_messages=False),
            guild.me: discord.PermissionOverwrite(send_messages=True)
        }
        await guild.create_text_channel('iq-log', overwrites=overwrites)
        await ctx.send("`Mod Log Successfully Created `")
    if choice == 'Channel':
        guild = ctx.message.guild
        await guild.create_text_channel(f'{field}')
        await ctx.send("`Channel Successfully Created `")
    if choice == 'ModRole':
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        await ctx.guild.create_role(
            name=f"{field}", colour=discord.Colour(0x88EBFF))
        doc_ref.set({
            u'ModRole': str(field),
        }, merge=True)
        role = discord.utils.get(ctx.guild.roles, name=f"{field}")
        await ctx.author.add_roles(role)
        await ctx.send("`Mod Role Successfully Created `")

@bot.command()
async def Get(ctx, choice='none', field='none'):
    if choice == 'none':
        await ctx.send('```You need to specify what to Get```')
    if choice == 'Channel':
        await ctx.send(
            f'`{ctx.message.channel.name}: {ctx.message.channel.id}`')

@bot.command()
async def ModRole(ctx, field='None',rolename = "iQ-Mod"):
  if field == "None":
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    moderationRole = u'{}'.format(doc_ref.get({u'ModRole'}).to_dict()['ModRole']) 
    if moderationRole == "None":
      await ctx.send("ModRole not set! You can set it by typing `&Modrole Create`")
    else:
      embed = discord.Embed(
        title="ModRole",
        description=f'The {str(moderationRole)} role is reqired for moderation commands',
        color=random.choice(colors))
      await ctx.send(embed=embed)
  elif field == "Create" or "Create":
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'ModRole': str(rolename),
        }, merge=True)
        role = discord.utils.get(ctx.guild.roles, name=f"{rolename}")
        await ctx.author.add_roles(role)
        await ctx.send("`Mod Role Successfully Set `")

@bot.command()
async def ModLog(ctx, field='None',modname = "iQ-Log"):
  if field == "None":
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    moderationChannel = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel']) 
    if moderationChannel == "None":
      await ctx.send("Moderation Channel not set! You can set it by typing `&ModLog Create (optional name)`")
    else:
      embed = discord.Embed(
        title="ModLog",
        description=f'Moderation commands will be logged in <#{str(moderationChannel)}>',
        color=random.choice(colors))
      await ctx.send(embed=embed)
  elif field == "Create" or "Create":
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'ModerationChannel': str(modname),
        }, merge=True)
        await ctx.send('`Mod Log Successfully Set`')

@bot.command()
async def AutoRole(ctx, field='None',rolename = "Guest"):
  if field == "None":
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    arole = u'{}'.format(doc_ref.get({u'AutoRole'}).to_dict()['AutoRole']) 
    if arole == "None":
      await ctx.send("Auto Role not set! You can set it by typing `&AutoRole Create (role name)`")
    else:
      embed = discord.Embed(
        title="AutoRole",
        description=f'All new member will be given the {str(arole)} upon joining.',
        color=random.choice(colors))
      await ctx.send(embed=embed)
  elif field == "Create" or "Create":
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'AutoRole': str(rolename),
        }, merge=True)
        await ctx.send('`AutoRole Successfully Set`')        

@bot.command()
async def WelcomeMessage(ctx, field='None',wmessage = "None"):
  if field == "None":
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    welcomeMessage = u'{}'.format(doc_ref.get({u'WelcomeMessage'}).to_dict()['WelcomeMessage']) 
    if welcomeMessage == "None":
      await ctx.send("Welcome Message not set! You can set it by typing `&WelcomeMessage Create (message)`")
    else:
      embed = discord.Embed(
        title="Welcome Message",
        description=f'Welcome Message: {str(welcomeMessage)}',
        color=random.choice(colors))
      await ctx.send(embed=embed)
  elif field == "Create" or "Create":
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'WelcomeMessage': str(wmessage),
        }, merge=True)
        await ctx.send('`Welcome Message Successfully Set`')        

@bot.command()
async def Set(ctx, choice='none', *, field='none'):
    if choice == 'none':
        await ctx.send('```You need to specify what to set```')
    if choice == 'ModRole':
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'ModRole': str(field),
        }, merge=True)
        role = discord.utils.get(ctx.guild.roles, name=f"{field}")
        await ctx.author.add_roles(role)
        await ctx.send("`Mod Role Successfully Set `")
    if choice == 'AutoRole':
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'AutoRole': str(field),
        }, merge=True)
        role = discord.utils.get(ctx.guild.roles, name=f"{field}")
        await ctx.author.add_roles(role)
        await ctx.send("`Auto Role Successfully Set `")
    if choice == 'WelcomeMessage':
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'WelcomeMessage': str(field),
        }, merge=True)
        await ctx.send("`Welcome Message Successfully Set `")
    if choice == 'ModLog':
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        doc_ref.set({
            u'ModerationChannel': str(field),
        }, merge=True)
        await ctx.send('`Mod Log Successfully Set`')

@bot.command()
async def server(ctx):
    await ctx.send(ctx.guild.id)

@bot.command()
async def Buy(ctx, stocksymbol: str, amount: int):
  docus = db.collection(u'Servers').document(str(ctx.guild.id))
  pro = u'{}'.format(docus.get({u'Pro'}).to_dict()['Pro'])
  if pro == "Pro":
    q = requests.get('https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords='+stocksymbol+'&apikey=QWOU4B1BS6VHRKOF')
    f = q.json()
    fe = f["bestMatches"][0]
    fn = fe["2. name"]
    x = fe["1. symbol"]
    r = requests.get('https://finnhub.io/api/v1/quote?symbol=' + x +
                      '&token=bre3nkfrh5rckh454te0')
    j = r.json()
    if "error" in j:
      await ctx.send(j['error'])
    #defs
    docs = db.collection(u'UserData').document(str(ctx.author.id))
    cash = u'{}'.format(docs.get({u'Cash'}).to_dict()['Cash'])
    shareprice = j["c"]
    if amount < int(shareprice):
      await ctx.send(f"`Purchase amount must be more than share price`")
    else:
      if int(cash) < amount:
        await ctx.send("`Purchase amount exceeds balance`")
      else:
        stockdoc = db.collection(u'UserData').document(str(ctx.author.id)).collection(u"Stocks").document(str(x))
        sharesbought = amount/int(shareprice)
        sharesbought = round(sharesbought)
        spent = sharesbought * int(shareprice)
        moneyafterpurchase = int(cash) - spent
        docs.set({
                u'Cash': int(moneyafterpurchase),
        }, merge=True)
        if stockdoc.get().exists:
          sharesowned = u'{}'.format(stockdoc.get({u'Shares'}).to_dict()['Shares'])
          sharesowned = sharesbought + int(sharesowned)
          stockdoc.set({
                u'Shares': int(sharesowned),
          }, merge=True)
          await ctx.send(f'`{sharesbought} shares of {str(fn)} bought at {str(shareprice)} `')
        else:
          stockdoc.set({
                u'Shares': int(sharesbought),
          }, merge=True)
          await ctx.send(f'`{sharesbought} shares of {str(fn)} bought at {str(shareprice)} `')
  else:
    await ctx.send("`Aevus Pro Access required`")
      
@bot.command()
async def Sell(ctx, stocksymbol: str, amount: int):
  docus = db.collection(u'Servers').document(str(ctx.guild.id))
  pro = u'{}'.format(docus.get({u'Pro'}).to_dict()['Pro'])
  if pro == "Pro":  
    q = requests.get('https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords='+stocksymbol+'&apikey=QWOU4B1BS6VHRKOF')
    f = q.json()
    fe = f["bestMatches"][0]
    fn = fe["2. name"]
    x = fe["1. symbol"]
    r = requests.get('https://finnhub.io/api/v1/quote?symbol=' + x +
                      '&token=bre3nkfrh5rckh454te0')
    j = r.json()
    if "error" in j:
      await ctx.send(j['error'])
    shareprice = j["c"]
    sharessold = amount/int(shareprice)
    sharessold = round(sharessold)
    cashearned = int(sharessold) * int(shareprice)
    if int(amount) < int(shareprice):
      await ctx.send(f"`Sell amount must be more than share price`")
    else:
      stockdoc = db.collection(u'UserData').document(str(ctx.author.id)).collection(u"Stocks").document(str(x))
      if stockdoc.get().exists:
        sharesowned = u'{}'.format(stockdoc.get({u'Shares'}).to_dict()['Shares'])
        if int(sharesowned) < int(sharessold):
          if int(sharesowned) < 1:
            await ctx.send('`You dont own any shares of the requested stock`')
          else:
            while int(sharesowned) < int(sharessold):
              sharessold = sharessold - 1
            cashearned = int(sharessold) * int(shareprice)
            sharesowned = int(sharesowned) - sharessold
            docs = db.collection(u'UserData').document(str(ctx.author.id))
            cash = u'{}'.format(docs.get({u'Cash'}).to_dict()['Cash'])
            cashearned = cashearned + int(cash)
            docs.set({
                    u'Cash': int(cashearned),
            }, merge=True)
            
            stockdoc.set({
                    u'Shares': int(sharesowned),
            }, merge=True)
            await ctx.send(f'`{sharessold} shares sold`')
        else:  
          sharesowned = int(sharesowned) - sharessold
          docs = db.collection(u'UserData').document(str(ctx.author.id))
          cash = u'{}'.format(docs.get({u'Cash'}).to_dict()['Cash'])
          cashearned = cashearned + int(cash)
          docs.set({
                  u'Cash': int(cashearned),
          }, merge=True)
          
          stockdoc.set({
                  u'Shares': int(sharesowned),
          }, merge=True)
          await ctx.send(f'`{sharessold} shares sold`')
      else:
        await ctx.send('`You dont own any shares of the requested stock`')
  else:
    await ctx.send("`Aevus Pro Access required`")

@bot.command()
async def Profile(ctx):
    embed = discord.Embed(
        title=f"{ctx.author.name}",
        description=
        "iQ is the ultimate moderation bot! It has everything relating to server management. ",
        color=random.choice(colors))
    await asyncio.sleep(1)
    embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
    embed.set_footer(text="Aevus: &Help")
    doc_ref = db.collection(u'UserData').document(f'{ctx.author.id}')
    if doc_ref.get().exists:
        embed.add_field(name="Name", value=f'{ctx.author.name}', inline=False)
        cash = u'{}'.format(doc_ref.get({u'Cash'}).to_dict()['Cash'])
        embed.add_field(name="Cash", value=f'{str(cash)}', inline=False)
        level = u'{}'.format(doc_ref.get({u'Level'}).to_dict()['Level'])
        embed.add_field(name="Level", value=f'{str(level)}', inline=False)
        boost = u'{}'.format(doc_ref.get({u'Boosts'}).to_dict()['Boosts'])
        embed.add_field(name="Upgrade Tokens", value=f'{str(boost)}', inline=False)
        #pro = u'{}'.format(doc_ref.get({u'Pro'}).to_dict()['Pro'])
        #embed.add_field(name="Account Type", value=f'{str(pro)}', inline=False)
        joined = u'{}'.format(doc_ref.get({u'Joined'}).to_dict()['Joined'])
        embed.add_field(name="Joined", value=f'{str(joined)}', inline=False)
        users_ref = db.collection("UserData").document(str(ctx.author.id)).collection(u"Stocks")
        docs = users_ref.stream()
        for doc in docs:
            stock = doc.id
            r = requests.get('https://finnhub.io/api/v1/quote?symbol=' +
                             str(stock) + '&token=bre3nkfrh5rckh454te0')
            j = r.json()
            sharevalue = j['c']
            stockRef = db.collection("UserData").document(str(ctx.author.id)).collection(u"Stocks").document(str(stock))
            sharesownded = u'{}'.format(stockRef.get({u'Shares'}).to_dict()['Shares'])
            shareownedvalue = int(sharesownded) * int(sharevalue)
            embed.add_field(name=f"{str(stock)}", value=f'${str(shareownedvalue)}', inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def Stock(ctx, stocksymbol: str):
    q = requests.get('https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords='+stocksymbol+'&apikey=QWOU4B1BS6VHRKOF')
    f = q.json()
    fe = f["bestMatches"][0]
    fn = fe["2. name"]
    x = fe["1. symbol"]
    r = requests.get('https://finnhub.io/api/v1/quote?symbol=' + x +
                     '&token=bre3nkfrh5rckh454te0')
    j = r.json()
    if "error" in j:
      await ctx.send(j['error'])
    embed = discord.Embed(
        title=f"{str(fn)}", description="Stock Analysis", color=random.choice(colors))
    embed.set_author(
        name=f"Invite Synapse!",
        url="https://discord.com/oauth2/authorize?client_id=712515532682952735&permissions=457792&scope=bot",
        icon_url=
        "https://i.imgur.com/EbVR81i.png"
    )
    embed.set_thumbnail(url="https://i.imgur.com/EbVR81i.png")
    embed.add_field(name="Current Price", value=j["c"], inline=False)
    embed.add_field(name="Open Price", value=j["o"], inline=False)
    embed.add_field(name="High Price", value=j["h"], inline=False)
    embed.add_field(name="Low Price", value=j["l"], inline=False)
    embed.add_field(name="Previous Close Price", value=j["pc"], inline=False)
    embed.set_footer(text="Command by Synapse Bot. Check out Sybapse for more info!")
    await ctx.send(embed=embed)

@bot.command()
async def clear(ctx, amount=5):
    docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
        moderationRole = u'{}'.format(
            docs.get({u'ModRole'}).to_dict()['ModRole'])
    except:
        moderationRole = 'None'
    if str(moderationRole) == 'None':
        amount = amount + 1
        upperLimit = 59
        if amount > upperLimit:
            await ctx.send("`Clears cannot excced 59`")

        if upperLimit >= amount:
            await ctx.channel.purge(limit=amount)
            doc_ref = db.collection(u'Servers').document(
                str(ctx.message.guild.id))
            try:
                if doc_ref.get().exists:
                    server = u'{}'.format(
                        doc_ref.get({u'ModerationChannel'
                                     }).to_dict()['ModerationChannel'])
                    modchannel = bot.get_channel(int(server))
                    embed = discord.Embed(
                        title=f"Cleared",
                        description=
                        f"{ctx.author.name} Deleted {amount} messages",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await modchannel.send(embed=embed)
            except:
                pass
    else:
        role = discord.utils.find(lambda r: r.name == f'{moderationRole}',
                                  ctx.guild.roles)
        if role in ctx.author.roles:
            amount = amount + 1
            upperLimit = 59
            if amount > upperLimit:
                await ctx.send("`Clears cannot excced 59`")
            if upperLimit >= amount:
                await ctx.channel.purge(limit=amount)
                doc_ref = db.collection(u'Servers').document(
                    str(ctx.message.guild.id))
                try:
                    if doc_ref.get().exists:
                        server = u'{}'.format(
                            doc_ref.get({u'ModerationChannel'
                                         }).to_dict()['ModerationChannel'])
                        modchannel = bot.get_channel(int(server))
                        embed = discord.Embed(
                            title=f"Cleared",
                            description=
                            f"{ctx.author.name} Deleted {amount} messages",
                            color=random.choice(colors))
                        embed.set_footer(text="Aevus: &Help")
                        await modchannel.send(embed=embed)
                except:
                    pass
        else:
            await ctx.send("`Missing Permissions`")

@bot.command(pass_context=True)
async def warn(ctx, member: discord.Member, *, content):
    docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
        moderationRole = u'{}'.format(
            docs.get({u'ModRole'}).to_dict()['ModRole'])
    except:
        moderationRole = 'None'
    if str(moderationRole) == 'None':
        channel = await member.create_dm()
        embed = discord.Embed(
            title="Warning",
            description="You are receiving a warning for the following reason: "
            + content +
            " If you keep up this behavior it may result in a kick/ban.",
            color=random.choice(colors))
        await asyncio.sleep(1)
        embed.set_footer(text="Aevus: &Help")
        await channel.send(embed=embed)
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
            if doc_ref.get().exists:
                server = u'{}'.format(
                    doc_ref.get(
                        {u'ModerationChannel'}).to_dict()['ModerationChannel'])
                modchannel = bot.get_channel(int(server))
                embed = discord.Embed(
                    title=f"Warned",
                    description=
                    f"{member.mention} has been warned for {content} by {ctx.author.mention}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await modchannel.send(embed=embed)
        except:
            pass
    else:
        role = discord.utils.find(lambda r: r.name == f'{moderationRole}',
                                  ctx.guild.roles)
        if role in ctx.author.roles:
            channel = await member.create_dm()
            embed = discord.Embed(
                title="Warning",
                description=
                "You are receiving a warning for the following reason: " +
                content +
                " If you keep up this behavior it may result in a kick/ban.",
                color=random.choice(colors))
            await asyncio.sleep(1)
            embed.set_footer(text="Aevus: &Help")
            await channel.send(embed=embed)
            doc_ref = db.collection(u'Servers').document(
                str(ctx.message.guild.id))
            try:
                if doc_ref.get().exists:
                    server = u'{}'.format(
                        doc_ref.get({u'ModerationChannel'
                                     }).to_dict()['ModerationChannel'])
                    modchannel = bot.get_channel(int(server))
                    embed = discord.Embed(
                        title=f"Warned",
                        description=
                        f"{member.mention} has been warned for {content} by {ctx.author.mention}",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await modchannel.send(embed=embed)
            except:
                pass
        else:
            await ctx.send("`Missing Permissions`")

@bot.command()
async def kick(ctx, member: discord.Member, reason=None):
    docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
        moderationRole = u'{}'.format(
            docs.get({u'ModRole'}).to_dict()['ModRole'])
    except:
        moderationRole = 'None'
    if str(moderationRole) == 'None':
        if reason == None:
            embed = discord.Embed(
                title="Error",
                description='Please specify reason! !kick <User> <Reason>',
                color=random.choice(colors))
            embed.set_footer(text="Aevus: &Help")
            await ctx.send(embed=embed)
        else:
            try:
                channel = await member.create_dm()
                embed = discord.Embed(
                    title="Kicked",
                    description=
                    "You are receiving a Kick for the following reason: " +
                    reason,
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await channel.send(embed=embed)
            except:
                pass
            doc_ref = db.collection(u'Servers').document(
                str(ctx.message.guild.id))
            try:
                if doc_ref.get().exists:
                    server = u'{}'.format(
                        doc_ref.get({u'ModerationChannel'
                                     }).to_dict()['ModerationChannel'])
                    modchannel = bot.get_channel(int(server))
                    embed = discord.Embed(
                        title=f"Kicked",
                        description=
                        f"{member.mention} has been kicked for {reason} by {ctx.author.mention}",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await modchannel.send(embed=embed)
                await member.kick()
                embed = discord.Embed(
                    title="Removed",
                    description=f"Successfully kicked {member} for {reason}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await ctx.send(embed=embed)
            except:
                pass

    else:
        role = discord.utils.find(lambda r: r.name == f'{moderationRole}',
                                  ctx.guild.roles)
        if role in ctx.author.roles:
            if reason == None:
                embed = discord.Embed(
                    title="Error",
                    description='Please specify reason! !kick <User> <Reason>',
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await ctx.send(embed=embed)
            else:
                try:
                    channel = await member.create_dm()
                    embed = discord.Embed(
                        title="Kicked",
                        description=
                        "You are receiving a Kick for the following reason: " +
                        reason,
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await channel.send(embed=embed)
                except:
                    pass
                doc_ref = db.collection(u'Servers').document(
                    str(ctx.message.guild.id))
                try:
                    if doc_ref.get().exists:
                        server = u'{}'.format(
                            doc_ref.get({u'ModerationChannel'
                                         }).to_dict()['ModerationChannel'])
                        modchannel = bot.get_channel(int(server))
                        embed = discord.Embed(
                            title=f"Kicked",
                            description=
                            f"{member.mention} has been kicked for {reason} by {ctx.author.mention}",
                            color=random.choice(colors))
                        embed.set_footer(text="Aevus: &Help")
                        await modchannel.send(embed=embed)
                    await member.kick()
                    embed = discord.Embed(
                        title="Removed",
                        description=
                        f"Successfully kicked {member} for {reason}",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await ctx.send(embed=embed)
                except:
                    pass
        else:
            await ctx.send("`Missing Permissions`")

@bot.command()
async def ban(ctx, member: discord.Member, reason=None):
    docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
        moderationRole = u'{}'.format(
            docs.get({u'ModRole'}).to_dict()['ModRole'])
    except:
        moderationRole = 'None'
    if str(moderationRole) == 'None':
        if reason == None:
            embed = discord.Embed(
                title="Error",
                description='Please specify reason! `&ban <User> <Reason>`',
                color=random.choice(colors))
            embed.set_footer(text="Aevus: &Help")
            await ctx.send(embed=embed)
        else:
            try:
                channel = await member.create_dm()
                embed = discord.Embed(
                    title="Banned",
                    description=
                    "You are receiving a BAN for the following reason: " +
                    reason,
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await channel.send(embed=embed)
            except:
                pass
            doc_ref = db.collection(u'Servers').document(
                str(ctx.message.guild.id))
            try:
                if doc_ref.get().exists:
                    server = u'{}'.format(
                        doc_ref.get({u'ModerationChannel'
                                     }).to_dict()['ModerationChannel'])
                    modchannel = bot.get_channel(int(server))
                    embed = discord.Embed(
                        title=f"Banned",
                        description=
                        f"{member.mention} has been banned for {reason} by {ctx.author.mention}",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await modchannel.send(embed=embed)
                await member.ban()
                embed = discord.Embed(
                    title="BANNED",
                    description=f"Successfully banned {member} for {reason}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await ctx.send(embed=embed)
            except:
                pass

    else:
        role = discord.utils.find(lambda r: r.name == f'{moderationRole}',
                                  ctx.guild.roles)
        if role in ctx.author.roles:
            try:
                channel = await member.create_dm()
                embed = discord.Embed(
                    title="Banned",
                    description=
                    "You are receiving a BAN for the following reason: " +
                    reason,
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await channel.send(embed=embed)
            except:
                pass
            doc_ref = db.collection(u'Servers').document(
                str(ctx.message.guild.id))
            try:
                if doc_ref.get().exists:
                    server = u'{}'.format(
                        doc_ref.get({u'ModerationChannel'
                                     }).to_dict()['ModerationChannel'])
                    modchannel = bot.get_channel(int(server))
                    embed = discord.Embed(
                        title=f"Banned",
                        description=
                        f"{member.mention} has been banned for {reason} by {ctx.author.mention}",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await modchannel.send(embed=embed)
                await member.ban()
                embed = discord.Embed(
                    title="BANNED",
                    description=f"Successfully banned {member} for {reason}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await ctx.send(embed=embed)
            except:
                pass
        else:
            await ctx.send("`Missing Permissions`")

@bot.event
async def on_member_join(member):
    docs = db.collection(u'UserData').document(str(member.id))
    guilddocs = db.collection(u'Servers').document(str(member.guild.id))
    if docs.get().exists:
        autorole = u'{}'.format(
            guilddocs.get({u'AutoRole'}).to_dict()['AutoRole'])
        welcomemessage = u'{}'.format(
            guilddocs.get({u'WelcomeMessage'}).to_dict()['WelcomeMessage'])
        if str(autorole) == "None":
            if str(welcomemessage) == "None":
                channel = await member.create_dm()
                embed = discord.Embed(
                    title=f"Welcome to {member.guild.name}",
                    description=f"{member.guild.name} is moderated by iQ.",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await asyncio.sleep(1)
                await channel.send(embed=embed)
            else:
                channel = await member.create_dm()
                embed = discord.Embed(
                    title=f"Welcome to {member.guild.name}",
                    description=
                    f"{str(welcomemessage)}.{member.guild.name} is moderated by iQ.",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await asyncio.sleep(1)
                await channel.send(embed=embed)
        else:
            autorole = u'{}'.format(
                guilddocs.get({u'AutoRole'}).to_dict()['AutoRole'])
            welcomemessage = u'{}'.format(
                guilddocs.get({u'WelcomeMessage'}).to_dict()['WelcomeMessage'])
            rolee = discord.utils.get(
                member.guild.roles, name=f"{str(autorole)}")
            await member.add_roles(rolee)

            if str(welcomemessage) == "None":
                channel = await member.create_dm()
                embed = discord.Embed(
                    title=f"Welcome to {member.guild.name}",
                    description=f"{member.guild.name} is moderated by iQ.",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await asyncio.sleep(1)
                await channel.send(embed=embed)
            else:
                channel = await member.create_dm()
                embed = discord.Embed(
                    title=f"Welcome to {member.guild.name}",
                    description=
                    f"{str(welcomemessage)}.{member.guild.name} is moderated by iQ.",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await asyncio.sleep(1)
                await channel.send(embed=embed)
    else:
        if member.bot:
            pass
        else:
            dt_string = datetime.now().strftime("%d/%m/%Y")
            docs.set({
                u'ID': str(member.id),
                u'Pro': u'Base',
                      u'Boosts': 0,
                      u'Level': 1,
                      u'Job': u'None',
                      u'Cash': 100,
                      u'XP': 0,
                      u'Joined': dt_string,
                      u'Claimed': dt_string,
            })
            autorole = u'{}'.format(
                guilddocs.get({u'AutoRole'}).to_dict()['AutoRole'])
            welcomemessage = u'{}'.format(
                guilddocs.get({u'WelcomeMessage'}).to_dict()['WelcomeMessage'])
            if str(autorole) == "None":
                if str(welcomemessage) == "None":
                    channel = await member.create_dm()
                    embed = discord.Embed(
                        title=f"Welcome to {member.guild.name}",
                        description=f"{member.guild.name} is moderated by iQ.",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await asyncio.sleep(1)
                    await channel.send(embed=embed)
                else:
                    channel = await member.create_dm()
                    embed = discord.Embed(
                        title=f"Welcome to {member.guild.name}",
                        description=
                        f"{str(welcomemessage)}.{member.guild.name} is moderated by iQ.",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await asyncio.sleep(1)
                    await channel.send(embed=embed)
            else:
                autorole = u'{}'.format(
                    guilddocs.get({u'AutoRole'}).to_dict()['AutoRole'])
                welcomemessage = u'{}'.format(
                    guilddocs.get(
                        {u'WelcomeMessage'}).to_dict()['WelcomeMessage'])
                rolee = discord.utils.get(
                    member.guild.roles, name=f"{str(autorole)}")
                await member.add_roles(rolee)

                if str(welcomemessage) == "None":
                    channel = await member.create_dm()
                    embed = discord.Embed(
                        title=f"Welcome to {member.guild.name}",
                        description=f"{member.guild.name} is moderated by iQ.",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await asyncio.sleep(1)
                    await channel.send(embed=embed)
                else:
                    channel = await member.create_dm()
                    embed = discord.Embed(
                        title=f"Welcome to {member.guild.name}",
                        description=
                        f"{str(welcomemessage)}.{member.guild.name} is moderated by iQ.",
                        color=random.choice(colors))
                    embed.set_footer(text="Aevus: &Help")
                    await asyncio.sleep(1)
                    await channel.send(embed=embed)

@bot.command()
async def coupon(ctx, actype='GuildPro', count=0):
    tokennn = str(uuid.uuid4())
    docs = db.collection(u'Coupon').document(str(tokennn))
    dt_string = datetime.now().strftime("%d/%m/%Y")
    docs.set({
        u'Token': str(tokennn),
        u'Type': actype,
        u'Status': 'Active',
        u'Boosts': count,
        u'Created': dt_string,
    })
    await ctx.send(f"`Created {tokennn}`")

@bot.command()
async def claim(ctx, code: str):
    docs = db.collection(u'Coupon').document(str(code))
    userdocs = db.collection(u'UserData').document(str(ctx.author.id))
    guilddocs = db.collection(u'Servers').document(str(ctx.guild.id))
    dt_string = datetime.now().strftime("%d/%m/%Y")
    if docs.get().exists:
        claimed = u'{}'.format(docs.get({u'Status'}).to_dict()['Status'])
        if str(claimed) == "Active":
            gvtype = u'{}'.format(docs.get({u'Type'}).to_dict()['Type'])
            if str(gvtype) == "AccPro":
                userstatus = u'{}'.format(
                    userdocs.get({u'Pro'}).to_dict()['Pro'])
                if str(userstatus) == "Pro":
                    await ctx.send("You already have Pro")
                else:
                    docs.set({
                        u'Status': f"Claimed {dt_string}",
                    }, merge=True)
                    userdocs.set({
                        u'Pro': f"Pro",
                    }, merge=True)
                    await ctx.send("`Claimed`")

            if str(gvtype) == "GuildPro":
                userstatus = u'{}'.format(
                    guilddocs.get({u'Pro'}).to_dict()['Pro'])
                if str(userstatus) == "Pro":
                    await ctx.send(f"{ctx.guild.name} is already Pro")
                else:
                    docs.set({
                        u'Status': f"Claimed {dt_string}",
                    }, merge=True)
                    guilddocs.set({
                        u'Pro': f"Pro",
                    }, merge=True)
                    await ctx.send("`Claimed`")
            if str(gvtype) == "Boost":
                currentboosts = u'{}'.format(
                    userdocs.get({u'Boosts'}).to_dict()['Boosts'])
                giftedboosts = u'{}'.format(
                    docs.get({u'Boosts'}).to_dict()['Boosts'])
                newboosts = int(currentboosts) + int(giftedboosts)
                docs.set({
                    u'Status': f"Claimed {dt_string}",
                }, merge=True)
                userdocs.set({
                    u'Boosts': newboosts,
                }, merge=True)
                await ctx.send("`Claimed`")

        else:
            await ctx.send("`Already Used`")

@bot.command()
async def Store(ctx):
  #store server check
  storestatus = db.collection("ServerData").document("Settings")
  storeonline = u'{}'.format(storestatus.get({u'Store'}).to_dict()['Store'])
  if str(storeonline) == 'Online':
    users_ref = db.collection("Store")
    docs = users_ref.stream()
    embed = discord.Embed(title="Store", description= "Add desc",color=random.choice(colors))
    for doc in docs:
      try:
        storedata = db.collection(u'Store').document(str(doc.id))
        objname = u'{}'.format(storedata.get({u'Name'}).to_dict()['Name'])
        cost = u'{}'.format(storedata.get({u'Cost'}).to_dict()['Cost'])
        amount = u'{}'.format(storedata.get({u'Amount'}).to_dict()['Amount'])
        objtype = u'{}'.format(storedata.get({u'Type'}).to_dict()['Type'])
        embed.add_field(name=str(objname),
          value=f'TYPE: **{objtype}** COST: **{cost}** Stock: **{amount}** ', inline=False)
      except:
        pass
    await ctx.send(embed=embed)
  else:
    await ctx.send('`❌ Store Offline`')
  

@bot.command()
async def StoreAdd(ctx):
  #store server check
  if str(ctx.author.id) == '408753256014282762':
    users_ref = db.collection("Store")
    docs = users_ref.stream()
    embed = discord.Embed(title="Store", description= "Add desc",color=random.choice(colors))
    for doc in docs:
      try:
        storedata = db.collection(u'Store').document(str(doc.id))
        objname = u'{}'.format(storedata.get({u'Name'}).to_dict()['Name'])
        cost = u'{}'.format(storedata.get({u'Cost'}).to_dict()['Cost'])
        amount = u'{}'.format(storedata.get({u'Amount'}).to_dict()['Amount'])
        objtype = u'{}'.format(storedata.get({u'Type'}).to_dict()['Type'])
        embed.add_field(name=str(objname),
          value=f'TYPE: **{objtype}** COST: **{cost}** Stock: **{amount}** ', inline=False)
      except:
        pass
    await ctx.send(embed=embed)
  else:
    await ctx.send('`Only Aevus Developers can use this command`')

@bot.command()
async def Upgrade(ctx, upgradetype="Guild"):
    docs = db.collection(u'UserData').document(str(ctx.author.id))
    guilddocs = db.collection(u'Servers').document(str(ctx.guild.id))
    currentboosts = u'{}'.format(docs.get({u'Boosts'}).to_dict()['Boosts'])
    if int(currentboosts) < 1:
        await ctx.send("`No Upgrade Tokens remaining`")
    elif int(currentboosts) > 0:
        print('a')
        serverstatus = u'{}'.format(guilddocs.get({u'Pro'}).to_dict()['Pro'])
        print('b')
        booster = u'{}'.format(
            guilddocs.get({u'Booster'}).to_dict()['Booster'])
        print('c')
        if str(serverstatus) == "Pro":
            await ctx.send(f"{str(booster)} already upgraded the server")
        else:
            print('d')
            newboost = int(currentboosts) - 1
            print('e')
            docs.set({
                u'Boosts': newboost,
            }, merge=True)
            guilddocs.set({
                u'Pro': f"Pro",
                u'Booster': str(ctx.author.id),
            },
                          merge=True)
            try:
                server = u'{}'.format(
                    docs.get(
                        {u'ModerationChannel'}).to_dict()['ModerationChannel'])
                modchannel = bot.get_channel(int(server))
                embed = discord.Embed(
                    title=f"Boosted",
                    description=
                    f"{ctx.guild.name} upgraded the server to PRO! Thanks to {ctx.author.mention}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await modchannel.send(embed=embed)
            except:
                await ctx.send(
                    f"{ctx.guild.name} upgraded the server to PRO! Thanks to {ctx.author.mention}"
                )

@bot.event
async def on_message(message):
    try:
        role = discord.utils.find(lambda r: r.name == 'Muted',
                                  message.guild.roles)
        if role in message.author.roles:
            await message.delete()
            try:
                channel = await message.author.create_dm()
                embed = discord.Embed(
                    title="Muted",
                    description=
                    f"You are muted from {message.guild.name}! Messages you send will be deleted immediately.",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await asyncio.sleep(1)
                await channel.send(embed=embed)
            except:
                pass
        else:
            if message.content.startswith('&'):
                f = open("status.txt", "r")
                status = f.read()
                if status == "1":
                    await bot.process_commands(message)
                elif message.content.startswith('&Admin'):
                    await bot.process_commands(message)
                else:
                    await message.channel.send(
                        "`IQ is currently offline, please try again later!`")
            elif message.content.startswith('Q '):
                      await message.channel.send("`prefix changed from Q Command to &Command`")
    except:
        if message.content.startswith('&'):
            f = open("status.txt", "r")
            status = f.read()
            if status == "1":
                await bot.process_commands(message)
            elif message.content.startswith('&Admin'):
                await bot.process_commands(message)
            else:
                await message.channel.send(
                    "`IQ is currently offline, please try again later!`")

@bot.command()
async def Mute(ctx, members: discord.Member, *, reason):
    docs = db.collection(u'Servers').document(str(ctx.author.guild.id))
    moderationRole = u'{}'.format(
            docs.get({u'ModRole'}).to_dict()['ModRole'])
    if str(moderationRole) == 'None':
        rolee = discord.utils.get(ctx.guild.roles, name="Muted")
        await members.add_roles(rolee)
        if docs.get().exists:
            server = u'{}'.format(
                docs.get(
                    {u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(
                title=f"Muted",
                description=
                f"{members.mention} has been muted for {reason} by {ctx.author.mention}",
                color=random.choice(colors))
            embed.set_footer(text="Aevus: &Help")
            await modchannel.send(embed=embed)
    else:
        role = discord.utils.find(lambda r: r.name == f'{moderationRole}',
                                  ctx.guild.roles)
        if role in ctx.author.roles:
            rolee = discord.utils.get(ctx.guild.roles, name="Muted")
            await members.add_roles(rolee)
            if docs.get().exists:
                server = u'{}'.format(
                    docs.get(
                        {u'ModerationChannel'}).to_dict()['ModerationChannel'])
                modchannel = bot.get_channel(int(server))
                embed = discord.Embed(
                    title=f"Muted",
                    description=
                    f"{members.mention} has been muted for **{reason}** by {ctx.author.mention}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await modchannel.send(embed=embed)
        else:
            await ctx.send("`Missing Permissions`")

@bot.command()
async def UnMute(ctx, member: discord.Member):
    docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
        moderationRole = u'{}'.format(
            docs.get({u'ModRole'}).to_dict()['ModRole'])
    except:
        moderationRole = 'None'
    if str(moderationRole) == 'None':
        rolee = discord.utils.get(ctx.guild.roles, name="Muted")
        await member.remove_roles(rolee)
        if docs.get().exists:
            server = u'{}'.format(
                docs.get(
                    {u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(
                title=f"UnMuted",
                description=
                f"{member.mention} has been unmuted by {ctx.author.mention}",
                color=random.choice(colors))
            embed.set_footer(text="Aevus: &Help")
            await modchannel.send(embed=embed)
    else:
        role = discord.utils.find(lambda r: r.name == f'{moderationRole}',
                                  ctx.guild.roles)
        if role in ctx.author.roles:
            rolee = discord.utils.get(ctx.guild.roles, name="Muted")
            await member.remove_roles(rolee)
            if docs.get().exists:
                server = u'{}'.format(
                    docs.get(
                        {u'ModerationChannel'}).to_dict()['ModerationChannel'])
                modchannel = bot.get_channel(int(server))
                embed = discord.Embed(
                    title=f"UnMuted",
                    description=
                    f"{member.mention} has been unmuted by {ctx.author.mention}",
                    color=random.choice(colors))
                embed.set_footer(text="Aevus: &Help")
                await modchannel.send(embed=embed)
        else:
            await ctx.send("`Missing Permissions`")
    role = discord.utils.get(ctx.guild.roles, name="Muted")

@bot.command()
async def Invite(ctx, member=None):
    if member == None:
        invitelink = await ctx.channel.create_invite(max_uses=1, unique=True)
        await ctx.send(invitelink)
    else:
        channel = await member.create_dm()
        #creating invite link
        invitelink = await ctx.channel.create_invite(max_uses=1, unique=True)
        #dming it to the person
        await channel.send(invitelink)


@bot.command()
async def Hire(ctx, jobname="none"):
  jobname = str(jobname.lower())
  print(jobname)
  if jobname == "none":
    users_ref = db.collection("Jobs")
    docs = users_ref.stream()
    embed = discord.Embed(title="Look for a job!", description= "Add desc",color=random.choice(colors))
    for doc in docs:
      try:
        storedata = db.collection(u'Jobs').document(str(doc.id))
        objname = u'{}'.format(storedata.get({u'Name'}).to_dict()['Name'])
        pay = u'{}'.format(storedata.get({u'Pay'}).to_dict()['Pay'])
        amount = u'{}'.format(storedata.get({u'Amount'}).to_dict()['Amount'])
        level = u'{}'.format(storedata.get({u'Level'}).to_dict()['Level'])
        embed.add_field(name=str(objname),
          value=f'Pay: **{pay}** Level Requirment: **{level}** Open Positions: **{amount}** ', inline=False)
      except:
        pass
    await ctx.send(embed=embed)              
  else:
    userref = db.collection("UserData").document(str(ctx.author.id))
    docs = db.collection("Jobs").document(str(jobname))
    if docs.get().exists:
      amount = u'{}'.format(docs.get({u'Amount'}).to_dict()['Amount'])
      activejob = u'{}'.format(userref.get({u'Job'}).to_dict()['Job'])
      
      if str(activejob) == "None":
        if int(amount) > 0:
          minlevel = u'{}'.format(docs.get({u'Level'}).to_dict()['Level'])
          level = u'{}'.format(userref.get({u'Level'}).to_dict()['Level'])
          if int(level) >= int(minlevel):
            userref.set({
              u'Job': str(jobname),
            }, merge=True)
            amount = int(amount) - 1
            docs.set({
              u'Amount': amount,
            }, merge=True),
            await ctx.send(f'<@{ctx.author.id}> has now been hired as a {jobname}')    
          else:
            await ctx.send('`You dont meet the qualifications for this career`')
        else:
          await ctx.send('`Job is currently full :(`')
      else:
        await ctx.send('`You already have an active job!`')
    else:
      await ctx.send('`Job does not exist`')

@bot.command()
@commands.cooldown(1, 1800, commands.BucketType.user)
async def Work(ctx):
  userref = db.collection("UserData").document(str(ctx.author.id))
  activejob = u'{}'.format(userref.get({u'Job'}).to_dict()['Job'])
  if activejob == "None":
    await ctx.send("`You need a job to work!`")
  else:
    docs = db.collection("Jobs").document(str(activejob))
    cash = u'{}'.format(userref.get({u'Cash'}).to_dict()['Cash'])
    xp = u'{}'.format(userref.get({u'XP'}).to_dict()['XP'])
    pay = u'{}'.format(docs.get({u'Pay'}).to_dict()['Pay'])
    cash = int(cash) + int(pay)
    xp = int(xp) + random.randrange(5, 20)
    if (int(xp)/1000).is_integer():
      level = u'{}'.format(userref.get({u'Level'}).to_dict()['Level'])
      level = int(level) + 1
      userref.set({
        u'Level': int(level)
      }, merge=True)
    userref.set({
      u'Cash': int(cash)
    }, merge=True)
    await ctx.send(f"`You were payed ${pay}. Keep up the great work! `")
  
@bot.command()
async def CreateJob(ctx, name=str,amount=int,pay=int,lvl=int):
  if str(ctx.author.id) == "408753256014282762":
    jbref = db.collection("Jobs").document(str(name))
    if jbref.get().exists:
      await ctx.send(f"`Job already exists`")
    else:
      jbref.set({
        u'Name': name,
        u'Level': lvl,
        u'Pay': pay,
        u'Amount': amount,
      })
    
    

@bot.command()
async def Migrate(ctx):
  await ctx.channel.purge(limit=1)
  embed = discord.Embed(
        title="iQ --> Aevus", description="```iQ is now Aevus! iQ is merging with Synapse('Stock Analysis Bot') as a new entity known as Aevus.```", color=0xFC224A)
  embed.add_field(
        name="What does this mean for iQ?", value="```iQ will still exist as Aevus! All userdata and commands will remain unchanged. Synapse will still exists as a seperate entity for users not interested in iQ commands.```", inline=False)
  
  embed.add_field(
        name="Why Merge", value="```As a developer of synapse & iQ it is a pain working on both bots. When working on two bots what ends up happening is that one bot gets left behind. It will be much easier to develop the bot as a single entity. What does this mean for the user? New commands faster and more congruence between iQ/Synapse commands!```", inline=False)

  embed.add_field(
        name="How long will this take?", value="```I cannot put a fixed time on this process at the moment. I predict the migration should be complete within 2 weeks. The goal is to move the more stable commands first and redo the older less stable commands. As more progress is made I can provide a fixed time soon. ```", inline=False)
  
  embed.add_field(
        name="Anything I Should look out for?", value="```During the migration some existing commands might be disabled temporarily. The reason for this is I want to make sure existing userdata is not lost and conduct the migration with least risk possible. Some commands may go through a name change but I 111will make sure to notify in optimal before-hand.```", inline=False)
  

  embed.add_field(
        name="Promotion?", value="```My vision with Aevus is to create a bot that can do all! It is currently limited to a few servers but soon enough I will release it! As for all the early access users YOU WILL BE GIFTED prior to the release for helping me in the development process.```", inline=False)
  embed.add_field(
        name="What to look out for?", value="```Aevus will be the greatest bot I have ever made. I have a large list of amazing and unique commands planned out and all I ask for is your patience. I wouldnt expect a release date anytime this month as I really want to make sure the bot is perfect! If you have any ideas please dm me and we can work on a plan together!```", inline=False)
  embed.add_field(
        name="Support contacts!", value="<@408753256014282762>", inline=False)
  

  embed.set_footer(text="Aevus: &Help")
  await ctx.send(embed=embed)

@bot.command()
async def Admin(ctx, tokenn: str, cmnd: str):
    if tokenn == os.environ.get("TOKENN"):
        if cmnd == 'Disable':
            text_file = open("status.txt", "w")
            text_file.write("0")
            text_file.close()

            await ctx.send('`Disabled`')
        elif cmnd == 'Enable':
            text_file = open("status.txt", "w")
            text_file.write("1")
            text_file.close()

            await ctx.send('`Enabled`')
        else:
            await ctx.send('`Command Not Found`')
    else:
        await ctx.send('`Panel Access Denied`')

@bot.command()
async def Feedback(ctx, *, message: str):
    today = date.today()
    datetoday = today.strftime("%m/%d/%y")
    logzero.logfile("feedback.log", maxBytes=1e6, backupCount=3)
    logger.info(f"{datetoday} {ctx.author.id} {str(message)}")
    channel = await ctx.author.create_dm()
    await channel.send('Thanks for the feedback')
    await channel.send('Support Server: https://discord.gg/nVBdeQb')
    time.sleep(1)
    await channel.send(
        f'Received as: `{datetoday} {ctx.author.id} {str(message)}`')

@bot.command()
async def Host(ctx):
    done = time.time()
    true_member_count = len([m for m in ctx.guild.members if not m.bot])
    elapsed = done - start
    embed = discord.Embed(
        title="ACTIVE", description="Specs", color=random.choice(colors))
    ping = round(bot.latency * 1000)
    #embed.set_thumbnail(url="https://i.imgur.com/c6nh2sN.png")
    embed.add_field(
        name="Machine", value=str(platform.machine()), inline=False)
    embed.add_field(
        name="Host Version", value=str(platform.version()), inline=False)
    embed.add_field(
        name="Platform", value=str(platform.platform()), inline=False)
    embed.add_field(name="System", value=str(platform.system()), inline=False)
    embed.add_field(
        name="Processor", value=str(platform.processor()), inline=False)
    embed.add_field(name="Ping", value=str(ping), inline=False)
    embed.add_field(name="Uptime", value=str(round(elapsed, 2)), inline=False)
    embed.add_field(
        name="Servers In", value=str(len(bot.guilds)), inline=False)
    try:
        doc_ref = db.collection(u'ServerData').document(u'Settings')
        serverstatus = u'{}'.format(
            doc_ref.get({u'Status'}).to_dict()['Status'])
        if str(serverstatus) == "Online":
            embed.add_field(name="Server", value='Online', inline=False)
        else:
            embed.add_field(name="Server", value='Offline', inline=False)
    except:
        pass
    try:
        doc_ref = db.collection(u'ServerData').document(u'Settings')
        version = u'{}'.format(doc_ref.get({u'Version'}).to_dict()['Version'])
        embed.add_field(name="Version", value=str(version), inline=False)
    except:
        pass
    embed.add_field(
        name="Guild Members", value=str(true_member_count), inline=False)
    embed.set_footer(text="Aevus: &Help")
    await ctx.send(embed=embed)

@bot.command()
async def Members(ctx):
    embed = discord.Embed(
        title="Members",
        description=
        "iQ is the ultimate moderation bot! It has everything relating to server management. ",
        color=random.choice(colors))
    embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
    embed.set_footer(text="Aevus: &Help")
    doc_ref = db.collection(u'Servers').document(f'{ctx.guild.id}')
    modrole = u'{}'.format(doc_ref.get({u'ModRole'}).to_dict()['ModRole'])
    for member in ctx.guild.members:
        if member.bot:
            embed.add_field(
                name=f"{str(member.name)}", value="Bot", inline=False)
        else:
            role = discord.utils.find(lambda r: r.name == 'Muted',
                                      ctx.guild.roles)
            if role in member.roles:
                embed.add_field(
                    name=f"{str(member.name)}", value=f"Muted", inline=False)
            else:
                embed.add_field(
                    name=f"{str(member.name)}", value='User', inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def Weather(ctx, *, City):
    complete_url = base_url + "appid=" + api_key + "&q=" + City
    response = requests.get(complete_url)
    x = response.json()
    if x["cod"] != "404":
        y = x["main"]
        current_temperature = str(round(y["temp"] - 273.15, 2))
        current_pressure = y["pressure"]
        current_humidiy = y["humidity"]
        min_temp = format(round(y["temp_min"] - 273.15, 2))
        max_temp = format(round(y["temp_max"] - 273.15, 2))
        feels_like = format(round(y["feels_like"] - 273.15, 2))
        z = x["weather"]
        icon = z[0]["icon"]
        weather_description = z[0]["description"]
        weather_main = z[0]["main"]
        w = x["wind"]
        wind = w["speed"]
        wind_deg = w["deg"]

        def faren(tem):
            tem = float(tem)
            return str(round(tem * 9 / 5 + 32, 2))

        def degDir(d):
            dirs = [
                'N', 'N/NE', 'NE', 'E/NE', 'E', 'E/SE', 'SE', 'S/SE', 'S',
                'S/SW', 'SW', 'W/SW', 'W', 'W/NW', 'NW', 'N/NW'
            ]
            ix = round(d / (360. / len(dirs)))
            return dirs[ix % len(dirs)]

        embed = discord.Embed(
            title=City,
            description=
            "iQ Weather gets information with the help of openweathermap.org",
            color=random.choice(colors))
        embed.set_author(name='iQ', url="https://synapsebot.netlify.app")
        embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
        embed.add_field(
            name="Temperature",
            value=current_temperature + "°C - " + str(
                faren(current_temperature)) + "°F",
            inline=False)
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
            value=str(wind) + " mph " + str(degDir(wind_deg)),
            inline=False)
        embed.add_field(
            name="Humidity", value=str(current_humidiy) + "%", inline=False)
        embed.add_field(
            name="Atmospheric Pressure",
            value=str(current_pressure) + " hPa",
            inline=False)
        embed.add_field(
            name="Description", value=weather_description, inline=False)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Error", description="City Not Found", color=0xFF8080)
        await ctx.send(embed=embed)

@bot.command(pass_context=True)
async def Help(ctx):
    embed = discord.Embed(
        title="iQ",
        description=
        "iQ is the ultimate moderation bot! It has everything relating to server management. ",
        color=random.choice(colors))
    await asyncio.sleep(1)
    embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
    embed.set_footer(text="iQ Bot by Aevus ")
    embed.add_field(
        name="Delete Messages", value="`&Clear (amount)`", inline=False)
    embed.add_field(
        name="Warn", value="`&Warn (mention user) (reason)`", inline=False)
    embed.add_field(
        name="Kick", value="`&Kick (mention user) (reason)`", inline=False)
    embed.add_field(
        name="Ban", value="`&Ban (mention user) (reason)`", inline=False)
    embed.add_field(name="Mute", value="`&Mute (mention user) (Reason)`", inline=False)
    embed.add_field(name="UnMute", value="`&UnMute (mention user)`", inline=False)
    
    embed.add_field(name="Weather", value="`&Weather (City)`", inline=False)
    embed.add_field(
        name="Invite Member to Server", value="`&Invite`", inline=False)
    embed.add_field(name="AutoRole", value="`&Autorole`", inline=False)
    embed.add_field(name="ModLog", value="`&ModLog`", inline=False)
    embed.add_field(name="Welcome Message", value="`&WelcomeMessage`", inline=False)
    embed.add_field(name="Mod Role", value="`&ModRole`", inline=False)
    embed.add_field(name="Claim", value="`&Claim (code)`", inline=False)
    embed.add_field(name="Boost", value="`&Boost`", inline=False)
    embed.add_field(name="View Account", value="`&About`", inline=False)
    embed.add_field(name="Server Info", value="`&Guild`", inline=False)
    embed.add_field(name="Server Panel", value="`&Panel`", inline=False)
    embed.add_field(name="Server Members", value="`&Members`", inline=False)
    
    embed.add_field(
        name="Feedback", value="`&Feedback (Message)`", inline=False)
    embed.add_field(
        name="Jukebox Commands", value="-------------------", inline=False)
    embed.add_field(
        name="Play Song", value="`&Play (Song Name)`", inline=False)
    embed.add_field(name="Skip Song", value="`&Skip`", inline=False)
    embed.add_field(name="Jukebox Queue", value="`&Queue`", inline=False)
    embed.add_field(name="Pause Jukebox", value="`&Pause`  ", inline=False)
    embed.add_field(name="Resume Jukebox", value="`&Resume`  ", inline=False)
    embed.add_field(name="Clear Jukebox", value="`&Stop`", inline=False)
    embed.add_field(name="Current Song", value="`&Now`  ", inline=False)
    embed.add_field(name="Resume Jukebox", value="`&Resume`  ", inline=False)
    embed.add_field(name="Shuffle Jukebox", value="`&Shuffle`", inline=False)
    embed.add_field(
        name="Force Join VC", value="`&ForceJoin (VC Name)`", inline=False)
    embed.add_field(
        name="Advanced Commands", value="-------------------", inline=False)
    embed.add_field(
        name="Get Channel ID", value="`&Get Channel`", inline=False)
    embed.add_field(name="Host Information", value="`&Host`  ", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def Logo(ctx):
    await ctx.send('https://i.imgur.com/f6XzjPE.png')

@bot.command()
async def Guild(ctx):
    embed = discord.Embed(
        title=f"{ctx.guild.name}",
        description=
        "iQ is the ultimate moderation bot! It has everything relating to server management. ",
        color=random.choice(colors))
    await asyncio.sleep(1)
    embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
    embed.set_footer(text="Aevus: &Help")
    doc_ref = db.collection(u'Servers').document(f'{ctx.guild.id}')
    if doc_ref.get().exists:
        embed.add_field(name="Name", value=f'{ctx.guild.name}', inline=False)
        credits = u'{}'.format(doc_ref.get({u'Credits'}).to_dict()['Credits'])
        embed.add_field(name="Credits", value=f'{str(credits)}', inline=False)
        modchannel = u'{}'.format(
            doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])

        pro = u'{}'.format(doc_ref.get({u'Pro'}).to_dict()['Pro'])
        embed.add_field(name="Service", value=f'{str(pro)}', inline=False)
        booster = u'{}'.format(doc_ref.get({u'Booster'}).to_dict()['Booster'])
        if str(booster) == "None":
            pass
        else:
            embed.add_field(
                name="Upgraded by", value=f'<@{str(booster)}>', inline=False)
        embed.add_field(
            name="Mod Channel", value=f'{str(modchannel)}', inline=False)
        modrole = u'{}'.format(doc_ref.get({u'ModRole'}).to_dict()['ModRole'])
        embed.add_field(name="Mod Role", value=f'{str(modrole)}', inline=False)
        pg = u'{}'.format(doc_ref.get({u'PG'}).to_dict()['PG'])
        embed.add_field(name="PG", value=f'{str(pg)}', inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def Panel(ctx):
    embed = discord.Embed(
        title=f"{ctx.guild.name}",
        description=
        "iQ is the ultimate moderation bot! It has everything relating to server management. ",
        color=random.choice(colors))
    embed.set_footer(text="Aevus: &Help")
    doc_ref = db.collection(u'Servers').document(f'{ctx.guild.id}')
    if doc_ref.get().exists:
        autorole = u'{}'.format(
            doc_ref.get({u'AutoRole'}).to_dict()['AutoRole'])
        if str(autorole) == "None":
            embed.add_field(
                name="Auto Role",
                value=
                f'```Auto Role not set. You can do so by typing: &set AutoRole (rolename)```',
                inline=True)
        else:
            embed.add_field(
                name="Auto Role",
                value=
                f'```New users will be given the {str(autorole)} upon joining.```',
                inline=True)

        modlog = u'{}'.format(
            doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
        if str(modlog) == "None":
            embed.add_field(
                name="Mod Log",
                value=
                f'```Mod Log not set. You can do so by typing: &set ModLog (Channel ID)```',
                inline=True)
        else:
            embed.add_field(
                name="Mod Log",
                value=
                f'```All moderation commands will by logged in <#{str(modlog)}>```',
                inline=True)

        modrole = u'{}'.format(doc_ref.get({u'ModRole'}).to_dict()['ModRole'])
        if str(modrole) == "None":
            embed.add_field(
                name="Mod Role",
                value=
                f'```Mod Role not set. You can do so by typing: &set ModRole (role name)```',
                inline=True)
        else:
            embed.add_field(
                name="Mod Role",
                value=
                f'```The {str(modrole)} role will be reqired to perform moderation commands.```',
                inline=True)

        welcomemessage = u'{}'.format(
            doc_ref.get({u'WelcomeMessage'}).to_dict()['WelcomeMessage'])
        if str(welcomemessage) == "None":
            embed.add_field(
                name="Welcome Message",
                value=
                f'```Welcome Message not set. You can do so by typing: &set WelcomeMessage (message)```',
                inline=True)
        else:
            embed.add_field(
                name="Welcome Message",
                value=f'```{str(welcomemessage)}```',
                inline=True)

        pro = u'{}'.format(doc_ref.get({u'Pro'}).to_dict()['Pro'])
        booster = u'{}'.format(doc_ref.get({u'Booster'}).to_dict()['Booster'])
        if str(pro) == "Base":
            embed.add_field(
                name="iQ Pro",
                value=
                f'```This server is missing many fun commands. Boost this server today!```',
                inline=True)
        else:
            embed.add_field(
                name="iQ Pro",
                value=f'`This server is upgraded by <@{str(booster)}>`',
                inline=True)

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
    #'music'  # Same name as it would be if you were importing it
]

if __name__ == '__main__':  # Ensures this is the file being ran
    for extension in extensions:
        bot.load_extension(extension)  # Loades every extension.

#bot.add_cog(Music(bot))
keep_alive()
token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)
