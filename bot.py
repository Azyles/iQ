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

from async_timeout import timeout

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

bot = commands.Bot('Q ', description='Ultimate Moderation Bot',case_insensitive=True )
colors=[0xAD303F,0xBE3B4A,0x9D2533,0xD83144]
showlist = ['Q Help']
bot.remove_command('help')

# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
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
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
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
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
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
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

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
        embed = (discord.Embed(title='Now Playing',
                               description='```\n{0.source.title}\n```'.format(self),
                               color=random.choice(colors))
                 .add_field(name='Duration', value=self.source.duration)
                 .add_field(name='Requested by', value=self.requester.name))

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
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
            await self.current.source.channel.send(embed=self.current.create_embed())

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
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
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
    @commands.has_permissions(manage_guild=True)
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.

        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError('You are neither connected to a voice channel nor specified a channel to join.')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    @commands.has_permissions(manage_guild=True)
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
    @commands.has_permissions(manage_guild=True)
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='resume')
    @commands.has_permissions(manage_guild=True)
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')
    @commands.has_permissions(manage_guild=True)
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
                await ctx.send('`Skip vote added, currently at {}/3`'.format(total_votes))

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
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [{1.source.title}]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(color=random.choice(colors),description='{} tracks:\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
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

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('An error occurred while processing this request: {}'.format(str(e)))
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
            raise commands.CommandError('`You are not connected to any voice channel.`')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('`Bot is already in a voice channel.`')



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
    await ctx.send("`Mod Log Successfully Created `")
  if choice == 'Server':
    guild = ctx.message.guild
    await guild.create_text_channel(f'{field}')
    await ctx.send("`Server Successfully Created `")
  if choice == 'ModRole':
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    await ctx.guild.create_role(name=f"{field}", colour=discord.Colour(0x88EBFF))
    doc_ref.set({
      u'ModRole': str(field),
    },merge=True)
    role = discord.utils.get(ctx.guild.roles, name=f"{field}")
    await ctx.author.add_roles(role)
    await ctx.send("`Mod Role Successfully Created `")

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
  if choice == 'ModRole':
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    doc_ref.set({
      u'ModRole': str(field),
    },merge=True)
    role = discord.utils.get(ctx.guild.roles, name=f"{field}")
    await ctx.author.add_roles(role)
    await ctx.send("`Mod Role Successfully Set `")
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
  docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
  try:
    moderationRole = u'{}'.format(docs.get({u'ModRole'}).to_dict()['ModRole'])
  except:
    moderationRole = 'None'
  if str(moderationRole) == 'None':
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
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
        except:
          pass
  else:
    role = discord.utils.find(lambda r: r.name == f'{moderationRole}', ctx.guild.roles)
    if role in ctx.author.roles:
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
              embed.set_footer(text="iQ Bot by Aevus : Q Help")
              await modchannel.send(embed=embed)
          except:
            pass
    else:
      await ctx.send("`Missing Permissions`")



@bot.command(pass_context=True)
async def warn(ctx, member: discord.Member, *, content):
  docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
  try:
    moderationRole = u'{}'.format(docs.get({u'ModRole'}).to_dict()['ModRole'])
  except:
    moderationRole = 'None'
  if str(moderationRole) == 'None':
    channel = await member.create_dm()
    embed = discord.Embed(
        title="Warning", description="You are receiving a warning for the following reason: " + content + " If you keep up this behavior it may result in a kick/ban.", color=random.choice(colors))
    await asyncio.sleep(1)
    embed.set_footer(text="iQ Bot by Aevus : Q Help")
    await channel.send(embed=embed)
    doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
    try:
      if doc_ref.get().exists:
        server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
        modchannel = bot.get_channel(int(server))
        embed = discord.Embed(title=f"Warned", description= f"{member.mention} has been warned for {content} by {ctx.author.mention}",color=random.choice(colors))
        embed.set_footer(text="iQ Bot by Aevus : Q Help")
        await modchannel.send(embed=embed)
    except:
      pass
  else:
    role = discord.utils.find(lambda r: r.name == f'{moderationRole}', ctx.guild.roles)
    if role in ctx.author.roles:
      channel = await member.create_dm()
      embed = discord.Embed(
          title="Warning", description="You are receiving a warning for the following reason: " + content + " If you keep up this behavior it may result in a kick/ban.", color=random.choice(colors))
      await asyncio.sleep(1)
      embed.set_footer(text="iQ Bot by Aevus : Q Help")
      await channel.send(embed=embed)
      doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
      try:
        if doc_ref.get().exists:
          server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
          modchannel = bot.get_channel(int(server))
          embed = discord.Embed(title=f"Warned", description= f"{member.mention} has been warned for {content} by {ctx.author.mention}",color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await modchannel.send(embed=embed)
      except:
        pass
    else:
      await ctx.send("`Missing Permissions`")

      
@bot.command()
async def kick(ctx, member: discord.Member, reason=None):
  docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
  try:
    moderationRole = u'{}'.format(docs.get({u'ModRole'}).to_dict()['ModRole'])
  except:
    moderationRole = 'None'
  if str(moderationRole) == 'None':
    if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! !kick <User> <Reason>', color=random.choice(colors))
        embed.set_footer(text="iQ Bot by Aevus : Q Help")
        await ctx.send(embed=embed)
    else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Kicked", description="You are receiving a Kick for the following reason: " + reason , color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Kicked", description= f"{member.mention} has been kicked for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
          await member.kick()
          embed = discord.Embed(
              title="Removed", description=f"Successfully kicked {member} for {reason}", color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await ctx.send(embed=embed)
        except:
          pass
    
  else:
    role = discord.utils.find(lambda r: r.name == f'{moderationRole}', ctx.guild.roles)
    if role in ctx.author.roles:
      if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! !kick <User> <Reason>', color=random.choice(colors))
        embed.set_footer(text="iQ Bot by Aevus : Q Help")
        await ctx.send(embed=embed)
      else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Kicked", description="You are receiving a Kick for the following reason: " + reason , color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Kicked", description= f"{member.mention} has been kicked for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
          await member.kick()
          embed = discord.Embed(
              title="Removed", description=f"Successfully kicked {member} for {reason}", color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await ctx.send(embed=embed)
        except:
          pass
    else:
      await ctx.send("`Missing Permissions`")
      
@bot.command()
async def ban(ctx, member: discord.Member, reason=None):
  docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
  try:
    moderationRole = u'{}'.format(docs.get({u'ModRole'}).to_dict()['ModRole'])
  except:
    moderationRole = 'None'
  if str(moderationRole) == 'None':
    if reason == None:
        embed = discord.Embed(
            title="Error", description='Please specify reason! `Q ban <User> <Reason>`', color=random.choice(colors))
        embed.set_footer(text="iQ Bot by Aevus : Q Help")
        await ctx.send(embed=embed)
    else:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Banned", description="You are receiving a BAN for the following reason: " + reason , color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Banned", description= f"{member.mention} has been banned for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
          await member.ban()
          embed = discord.Embed(
              title="BANNED", description=f"Successfully banned {member} for {reason}", color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await ctx.send(embed=embed)
        except:
          pass

  else:
    role = discord.utils.find(lambda r: r.name == f'{moderationRole}', ctx.guild.roles)
    if role in ctx.author.roles:
        try:
          channel = await member.create_dm()
          embed = discord.Embed(
              title="Banned", description="You are receiving a BAN for the following reason: " + reason , color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await channel.send(embed=embed)
        except:
          pass
        doc_ref = db.collection(u'Servers').document(str(ctx.message.guild.id))
        try:
          if doc_ref.get().exists:
            server = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Banned", description= f"{member.mention} has been banned for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
          await member.ban()
          embed = discord.Embed(
              title="BANNED", description=f"Successfully banned {member} for {reason}", color=random.choice(colors))
          embed.set_footer(text="iQ Bot by Aevus : Q Help")
          await ctx.send(embed=embed)
        except:
          pass
    else:
      await ctx.send("`Missing Permissions`")
  
@bot.event
async def on_message(message):
  role = discord.utils.find(lambda r: r.name == 'Muted', message.guild.roles)
  if role in message.author.roles:
    await message.delete()
    try:
      channel = await message.author.create_dm()
      embed = discord.Embed(
        title="Muted", description=f"You are muted from {message.guild.name}! Messages you send will be deleted immediately.", color=random.choice(colors))
      embed.set_footer(text="iQ Bot by Aevus : Q Help")
      await asyncio.sleep(1)
      await channel.send(embed=embed)
    except:
      pass
  else:
    
    await bot.process_commands(message)

@bot.command()
async def Mute(ctx,member: discord.Member, *, reason):
  docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
  try:
    moderationRole = u'{}'.format(docs.get({u'ModRole'}).to_dict()['ModRole'])
  except:
    moderationRole = 'None'
  if str(moderationRole) == 'None':
    rolee = discord.utils.get(ctx.guild.roles, name="Muted")
    await member.add_roles(rolee)
    if docs.get().exists:
            server = u'{}'.format(docs.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Muted", description= f"{member.mention} has been muted for {reason} by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
  else:
    role = discord.utils.find(lambda r: r.name == f'{moderationRole}', ctx.guild.roles)
    if role in ctx.author.roles:
      rolee = discord.utils.get(ctx.guild.roles, name="Muted")
      await member.add_roles(rolee)
      if docs.get().exists:
            server = u'{}'.format(docs.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"Muted", description= f"{member.mention} has been muted for **{reason}** by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
    else:
      await ctx.send("`Missing Permissions`")
  role = discord.utils.get(ctx.guild.roles, name="Muted")

@bot.command()
async def UnMute(ctx,member: discord.Member):
  docs = db.collection(u'Servers').document(str(ctx.message.guild.id))
  try:
    moderationRole = u'{}'.format(docs.get({u'ModRole'}).to_dict()['ModRole'])
  except:
    moderationRole = 'None'
  if str(moderationRole) == 'None':
    rolee = discord.utils.get(ctx.guild.roles, name="Muted")
    await member.remove_roles(rolee)
    if docs.get().exists:
            server = u'{}'.format(docs.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"UnMuted", description= f"{member.mention} has been unmuted by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
  else:
    role = discord.utils.find(lambda r: r.name == f'{moderationRole}', ctx.guild.roles)
    if role in ctx.author.roles:
      rolee = discord.utils.get(ctx.guild.roles, name="Muted")
      await member.remove_roles(rolee)
      if docs.get().exists:
            server = u'{}'.format(docs.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
            modchannel = bot.get_channel(int(server))
            embed = discord.Embed(title=f"UnMuted", description= f"{member.mention} has been unmuted by {ctx.author.mention}",color=random.choice(colors))
            embed.set_footer(text="iQ Bot by Aevus : Q Help")
            await modchannel.send(embed=embed)
    else:
      await ctx.send("`Missing Permissions`")
  role = discord.utils.get(ctx.guild.roles, name="Muted")

@bot.command()
async def Invite(ctx, member=None):
  if member == None:
    invitelink = await ctx.channel.create_invite(max_uses=1,unique=True)
    await ctx.send(invitelink)
  else:
    channel = await member.create_dm()
    #creating invite link
    invitelink = await ctx.channel.create_invite(max_uses=1,unique=True)
    #dming it to the person
    await channel.send(invitelink)

@bot.command()
async def Feedback(ctx, *, message: str):
  today = date.today()
  datetoday = today.strftime("%m/%d/%y")
  logzero.logfile("feedback.log", maxBytes=1e6, backupCount=3)
  logger.info(f"{datetoday} {ctx.author.id} {str(message)}")
  channel = await ctx.author.create_dm()
  await channel.send('Thanks for the feedback')
  time.sleep(1)
  await channel.send(f'Received as: `{datetoday} {ctx.author.id} {str(message)}`')

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
  embed.set_footer(text="iQ Bot by Aevus : Q Help")
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
            "iQ Weather gets information with the help of openweathermap.org",
            color=random.choice(colors))
        embed.set_author(
            name='iQ', url="https://synapsebot.netlify.app")
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
    embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
    embed.set_footer(text="iQ Bot by Aevus ")
    embed.add_field(name="Delete Messages", value="`Q Clear (amount)`", inline=False)
    embed.add_field(name="Limit Commands to role", value="`Q Add ModRole (rolename)`", inline=False)
    embed.add_field(name="Warn", value="`Q Warn (mention user) (reason)`", inline=False)
    embed.add_field(name="Kick", value="`Q Kick (mention user) (reason)`", inline=False)
    embed.add_field(name="Ban", value="`Q Ban (mention user) (reason)`", inline=False)
    embed.add_field(name="Mute", value="`Q Mute (mention user)`", inline=False)
    embed.add_field(name="Weather", value="`Q Weather (City)`", inline=False)
    embed.add_field(name="Invite Member to Server", value="`Q Invite`", inline=False)
    embed.add_field(name="Feedback", value="`Q Feedback (Message)`", inline=False)
    embed.add_field(name="Jukebox Commands", value="-------------------", inline=False)
    embed.add_field(name="Play Song", value="`Q Play (Song Name)`", inline=False)
    embed.add_field(name="Skip Song", value="`Q Skip`", inline=False)
    embed.add_field(name="Jukebox Queue", value="`Q Queue`", inline=False)
    embed.add_field(name="Pause Jukebox", value="`Q Pause`  ", inline=False)
    embed.add_field(name="Resume Jukebox", value="`Q Resume`  ", inline=False)
    embed.add_field(name="Clear Jukebox", value="`Q Stop`", inline=False)
    embed.add_field(name="Current Song", value="`Q Now`  ", inline=False)
    embed.add_field(name="Resume Jukebox", value="`Q Resume`  ", inline=False)
    embed.add_field(name="Shuffle Jukebox", value="`Q Shuffle`", inline=False)
    embed.add_field(name="Force Join VC", value="`Q ForceJoin (VC Name)`", inline=False)
    embed.add_field(name="Advanced Commands", value="-------------------", inline=False)
    embed.add_field(name="Get Channel ID", value="`Q Get Channel`", inline=False)
    embed.add_field(name="Set ModLog", value="`Q Set ModLog (channel id)`", inline=False)
    embed.add_field(name="Host Information", value="`Q Host`  ", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def Logo(ctx):
  await ctx.send('https://i.imgur.com/f6XzjPE.png')

@bot.command()
async def Guild(ctx):
  embed = discord.Embed(title=f"{ctx.guild.name}", description="iQ is the ultimate moderation bot! It has everything relating to server management. ", color=random.choice(colors))
  await asyncio.sleep(1)
  embed.set_thumbnail(url="https://i.imgur.com/f6XzjPE.png")
  embed.set_footer(text="iQ Bot by Aevus : Q Help")
  doc_ref = db.collection(u'Servers').document(f'{ctx.guild.id}')
  if doc_ref.get().exists:
    embed.add_field(name="Name",
                        value=f'{ctx.guild.name}', inline=False)
    credits = u'{}'.format(doc_ref.get({u'Credits'}).to_dict()['Credits'])
    embed.add_field(name="Credits",
                        value=f'{str(credits)}', inline=False)
    modchannel = u'{}'.format(doc_ref.get({u'ModerationChannel'}).to_dict()['ModerationChannel'])
    embed.add_field(name="Mod Channel",
                        value=f'{str(modchannel)}', inline=False)
    modrole = u'{}'.format(doc_ref.get({u'ModRole'}).to_dict()['ModRole'])
    embed.add_field(name="Mod Role",
                        value=f'{str(modrole)}', inline=False)
    pg = u'{}'.format(doc_ref.get({u'PG'}).to_dict()['PG'])
    embed.add_field(name="PG",
                        value=f'{str(pg)}', inline=False)    
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
  #'music'  # Same name as it would be if you were importing it
]

if __name__ == '__main__':  # Ensures this is the file being ran
  for extension in extensions:
    bot.load_extension(extension)  # Loades every extension.

bot.add_cog(Music(bot))
keep_alive()
token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)    
