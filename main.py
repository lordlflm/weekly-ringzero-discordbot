import calendar
import os
import random
import re
import asyncio

import discord
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# TODOS
# 
# filter already done challenges
# vote for difficulty
# fallback if no challenge matches category and difficulty
# help command with usages
# add modes (weekly, biweekly, monthly)

SET_ANNOUNCEMENT_CHANNEL_USAGE = '!set_announcement_channel <channel name>'
START_USAGE = '!start <day> <hour>'

bot = None
announcement_channel = None
scheduler = AsyncIOScheduler()

# each guild has an entry
done_challenges = {}
category_votes = {}
difficulty_votes = {}
categories = {}

def run_discord_bot():
    load_dotenv(override=True)
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN_DEV')
    # DISCORD_TOKEN = os.getenv('DISCORD_TOKEN_PROD')
    if DISCORD_TOKEN is None:
        print("Discord token not found in .env file")
        return
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix='!', intents=intents)

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        categories.setdefault(guild.id, get_categories())
        category_votes.setdefault(guild.id, {'votes': {}, 'voted': []})
        done_challenges.setdefault(guild.id, [])

    @bot.event
    async def on_ready():
        for guild in bot.guilds:
            categories.setdefault(guild.id, get_categories())        
            category_votes.setdefault(guild.id, {'votes': {}, 'voted': []})
            done_challenges.setdefault(guild.id, [])
        print(categories)
        print(category_votes)
        print(done_challenges)
        try:
            # synced = await bot.tree.sync()
            synced = await bot.tree.sync(guild=discord.Object(id=768896437261041704))
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(e)
            return
        scheduler.start()


    async def announcement_channel_autocomplete(interaction: discord.Interaction, current: str):
        text_channels = interaction.guild.text_channels
        return [
            app_commands.Choice(name=text_channel.name, value=text_channel.name)
            for text_channel in text_channels if current.lower() in text_channel.name.lower()
        ]

    @bot.tree.command(name='set_announcement_channel', 
        guild=discord.Object(id=768896437261041704),
        description='Set the channel in which the bot will interact')
    @app_commands.describe(channel='The channel in which the bot will interact')
    @app_commands.autocomplete(channel=announcement_channel_autocomplete)
    async def set_announcement_channel(interaction: discord.Interaction, channel: str):
        text_channels = [channel for channel in interaction.guild.text_channels]
        channel_object = next((text_channel for text_channel in text_channels if channel == text_channel.name), None)
        if channel_object is None:           
            await interaction.response.send_message(f"'{channel}' is not a valid text channel")
            return
        global announcement_channel
        announcement_channel = channel_object
        await interaction.response.send_message(f"Successfully set '{channel}' as announcement channel", ephemeral=True)

    async def day_autocomplete(interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=day, value=day)
            for day in list(calendar.day_name) if current.lower() in day.lower()
        ]

    async def time_autocomplete(interaction: discord.Interaction, current: str):
        times = []
        for hour in range(24):
            for minute in range(60):
                time = f"{hour:02}:{minute:02}"
                if current.lower() in time.lower():
                    times.append(time)
        return [
            app_commands.Choice(name=time, value=time)
            for time in times[:25]
        ]

    @bot.tree.command(name='start', 
        guild=discord.Object(id=768896437261041704),
        description='Starts weekly challenge announcements')
    @app_commands.describe(day='The day of the week for weekly challenge announcement')
    @app_commands.describe(time='The time at which the challenge is announced')
    @app_commands.autocomplete(day=day_autocomplete)
    @app_commands.autocomplete(time=time_autocomplete)
    async def start(interaction: discord.Interaction, day: str, time: str):
        global announcement_channel
        if announcement_channel is None:
            await interaction.response.send_message(f"Please set an announcement_channel before running start. Use `{SET_ANNOUNCEMENT_CHANNEL_USAGE}`")
            return

        if day.lower() not in map(lambda x: x.lower(), list(calendar.day_name)):
            await interaction.response.send_message('Invalid day name')
            return

        match = re.fullmatch(r"([01]?[0-9]|[2][0-3]):([0-5][0-9])", time)
        if match:
            hour, minute = match.groups()
        else:
            await interaction.response.send_message('Invalid time')
            return

        try:
            scheduler.remove_job('announcement')
        except:
            pass
 
        scheduler.add_job(job, args=[interaction.guild.id], id='announcement', trigger=CronTrigger(day_of_week=day_name_to_day_abr(day), hour=hour, minute=minute))
        await interaction.response.send_message(f"Successfully started! Challenges will be announced on {day} at {time}")

    async def category_autocomplete(interaction: discord.Interaction, current: str):
        guild_categories = categories[interaction.guild.id]
        category_choices = [category['title'] for category in guild_categories if current.lower() in category['title'].lower()]
        return [
            app_commands.Choice(name=category, value=category)
            for category in category_choices[:25]
        ]

    @bot.tree.command(name='category',
        guild=discord.Object(id=768896437261041704),
        description="Vote for next week's challenge category")
    @app_commands.autocomplete(category=category_autocomplete)
    async def category(interaction: discord.Interaction, category: str):
        guild_categories = categories[interaction.guild.id]
        if category not in [category['title'] for category in guild_categories]:
            await interaction.response.send_message('Not a valid category')
            return

        guild_id = interaction.guild.id
        user_id = interaction.user.id
        guild_entry = category_votes[guild_id]
        if user_id in guild_entry['voted']:
            await interaction.response.send_message("You can only vote once a week")
            return
        guild_entry['votes'][category] = guild_entry['votes'].get(category, 0) + 1
        guild_entry['voted'].append(user_id)

        await interaction.response.send_message(f"You voted for {category}")

    bot.run(DISCORD_TOKEN)

def day_name_to_day_abr(day_name):
    for i in range(6):
        day_names = list(calendar.day_name)
        if day_name == day_names[i] or day_name == day_names[i].lower():
            return list(calendar.day_abbr)[i]

async def job(guild_id: int):
    challenge_info_json = get_random_challenge_from_ringzero(guild_id)
    message = format_challenge_info_into_discord_message(challenge_info_json)

    global announcement_channel
    asyncio.create_task(announcement_channel.send("# 🔥 New Weekly Challenge! 🔥", embed=message))

def format_challenge_info_into_discord_message(challenge_info_json):
    url = f"https://ringzer0ctf.com/challenges/{challenge_info_json['id']}"
    embed = discord.Embed(
        title=challenge_info_json['title'],
        url=url,
        color=discord.Color.gold(),
    )
    embed.add_field(name="Points", value=challenge_info_json['points'], inline=True)
    embed.add_field(name="Author", value=challenge_info_json['author'], inline=True)
    embed.set_footer(text="ringzer0ctf.com")
    embed.set_image(url='https://ringzer0ctf.com/images/logo.png')

    return embed

def get_categories():
    response = requests.get('https://ringzer0ctf.com/api/categories')
    return [category['category'] for category in response.json()['data']['categories']]

def get_random_challenge_from_ringzero(guild_id: int):
    guild_category_votes = category_votes[guild_id]['votes'] or {}
    guild_categories = categories[guild_id]
    category_votes[guild_id]['votes'] = {}
    category_votes[guild_id]['voted'] = []

    possible_categories = []
    if len(guild_category_votes) == 0:
        possible_categories = [category['title'] for category in guild_categories]
    else:
        for category, votes in guild_category_votes.items():
            for _ in range(votes):
                possible_categories.append(category)

    picked_category_title = possible_categories[random.randint(0, len(possible_categories) - 1)]
    picked_category_id = next((category['id'] for category in guild_categories if category['title'] == picked_category_title), None)

    challenges = []
    response = requests.get(f" https://ringzer0ctf.com/api/category/challenges/{picked_category_id}")
    guild_done_challenges = done_challenges[guild_id]
    challenges.extend([challenge['challenge'] for challenge in response.json()['data']['categories'][0]['category']['challenges'] if challenge['challenge']['title'] not in guild_done_challenges])
        
    categories[guild_id] = get_categories()
    challenge = challenges[random.randint(0, len(challenges) - 1)]
    done_challenges[guild_id] = done_challenges[guild_id].append(challenge['title'])
    print(done_challenges)
    return challenge

if __name__ == "__main__":
    run_discord_bot()
