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
# vote for difficulty
# start with first challenge of a track
# fallback if no challenge matches category and difficulty
# help command with usages
# add modes (weekly, biweekly, monthly)

SET_ANNOUNCEMENT_CHANNEL_USAGE = '!set_announcement_channel <channel name>'
START_USAGE = '!start <day> <hour>'

bot = None
scheduler = AsyncIOScheduler()

# each guild has an entry
done_challenges = {}
category_votes = {}
difficulty_votes = {}
categories = {}
difficulties = {}
announcement_channels = {}

def run_discord_bot():
    load_dotenv(override=True)
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN_DEV')
    # DISCORD_TOKEN = os.getenv('DISCORD_TOKEN_PROD')
    if DISCORD_TOKEN is None:
        print("DISCORD_TOEKN_PROD entry not found in .env file")
        return
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix='!', intents=intents)

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        announcement_channels.setdefault(guild.id, None)
        set_guild_entries(guild.id)
        done_challenges.setdefault(guild.id, [])

        # TODO remove prints later
        debug_entries("on_guild_join event called")

    @bot.event
    async def on_ready():
        for guild in bot.guilds:
            announcement_channels.setdefault(guild.id, None)
            set_guild_entries(guild.id)
            done_challenges.setdefault(guild.id, [])
        # TODO remove prints later
        debug_entries("on_ready event called")
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
        announcement_channels[interaction.guild.id] = channel_object
        await interaction.response.send_message(
            f"Successfully set '{channel}' as announcement channel", ephemeral=True)

        # TODO remove prints later
        debug_entries("set_announcement_channel command called")

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
        guild_announcement_channel = announcement_channels[interaction.guild.id]
        if guild_announcement_channel is None:
            await interaction.response.send_message(
                f"Please set an announcement_channel before running start. Use `{SET_ANNOUNCEMENT_CHANNEL_USAGE}`")
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
 
        scheduler.add_job(
            job, 
            args=[interaction.guild.id], 
            id='announcement', 
            trigger=CronTrigger(day_of_week=day_name_to_day_abr(day), 
            hour=hour, 
            minute=minute))
        await interaction.response.send_message(
            f"Successfully started! Challenges will be announced on {day} at {time}", 
            ephemeral=True)

        # TODO remove prints later
        debug_entries("start command called")

    async def category_autocomplete(interaction: discord.Interaction, current: str):
        guild_categories = categories[interaction.guild.id]
        category_choices = [category['title'] 
            for category in guild_categories 
            if current.lower() in category['title'].lower()]
        return [
            app_commands.Choice(name=category, value=category)
            for category in category_choices[:25]
        ]

    @bot.tree.command(name='category',
        guild=discord.Object(id=768896437261041704),
        description="Vote for next week's challenge category")
    @app_commands.describe(category='The category of the challenge')
    @app_commands.autocomplete(category=category_autocomplete)
    async def category(interaction: discord.Interaction, category: str):
        guild_id = interaction.guild.id
        guild_categories = categories[guild_id]
        if category not in [category['title'] for category in guild_categories]:
            await interaction.response.send_message('Not a valid category')
            return

        user_id = interaction.user.id
        guild_entry = category_votes[guild_id]
        if user_id in guild_entry['voted']:
            await interaction.response.send_message("You can only vote once a week")
            return
        guild_entry['votes'][category] = guild_entry['votes'].get(category, 0) + 1
        guild_entry['voted'].append(user_id)

        await interaction.response.send_message(f"You voted for the following category: {category}")
        # TODO remove prints later
        debug_entries("category command called")

    async def difficulty_autocomplete(interaction: discord.Interaction, current: str):
        guild_difficulties = difficulties[interaction.guild.id]
        difficulty_choices = [difficulty 
            for difficulty in guild_difficulties
            if current.lower() in difficulty.lower()]
        return [
            app_commands.Choice(name=f"{difficulty} points", value=difficulty)
            for difficulty in difficulty_choices[:25]
        ]

    @bot.tree.command(name='difficulty',
        guild=discord.Object(id=768896437261041704),
        description="Vote for next week's challenge difficulty")
    @app_commands.describe(difficulty='The difficulty of the challenge')
    @app_commands.autocomplete(difficulty=difficulty_autocomplete)
    async def difficulty(interaction: discord.Interaction, difficulty: str):
        guild_id = interaction.guild.id
        guild_difficulties = difficulties[guild_id]
        if difficulty not in guild_difficulties:
            await interaction.response.send_message('Not a valid difficulty')
            return

        user_id = interaction.user.id
        guild_entry = difficulty_votes[guild_id]
        if user_id in guild_entry['voted']:
            await interaction.response.send_message("You can only vote once a week")
            return
        guild_entry['votes'][difficulty] = guild_entry['votes'].get(difficulty, 0) + 1
        guild_entry['voted'].append(user_id)

        await interaction.response.send_message(f"You voted for the following difficulty: {difficulty} points")

        # TODO remove prints later
        debug_entries("difficulty command called")


    bot.run(DISCORD_TOKEN)

def day_name_to_day_abr(day_name):
    for i in range(6):
        day_names = list(calendar.day_name)
        if day_name == day_names[i] or day_name == day_names[i].lower():
            return list(calendar.day_abbr)[i]

async def job(guild_id: int):
    challenge_info_json = get_random_challenge_from_ringzero(guild_id)
    message = format_challenge_info_into_discord_message(challenge_info_json)

    guild_announcement_channel = announcement_channels[guild_id]
    asyncio.create_task(guild_announcement_channel.send("# 🔥 New Weekly Challenge! 🔥", embed=message))

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

def set_guild_entries(guild_id: int):
    categories.setdefault(guild_id, get_categories())
    category_votes[guild_id] = {'votes': {}, 'voted': []}
    difficulties.setdefault(guild_id, get_difficulties(guild_id))
    difficulty_votes[guild_id] = {'votes': {}, 'voted': []}

def get_categories():
    response = requests.get('https://ringzer0ctf.com/api/categories')
    return [category['category'] for category in response.json()['data']['categories']]

def get_difficulties(guild_id: int):
    difficulties = []
    for category in categories[guild_id]:
        response = requests.get(f"https://ringzer0ctf.com/api/category/challenges/{category['id']}")
        challenges = response.json()['data']['categories'][0]['category']['challenges']
        difficulties.extend(
            challenge['challenge']['points']
                for challenge in challenges 
                if challenge['challenge']['points'] not in difficulties)
    difficulties.sort(key=lambda x: int(x))
    return difficulties

def debug_entries(event: str):
    print(f"==================  {event}  ===================")
    print(f"DEBUG categories\n{categories}")
    print(f"DEBUG difficulties\n{difficulties}")
    print(f"DEBUG category_votes\n{category_votes}")
    print(f"DEBUG difficulty_votes\n{difficulty_votes}")
    print(f"DEBUG done_challenges\n{done_challenges}")
    print(f"DEBUG announcement_channels\n{announcement_channels}")
    print("=====================================")

def get_random_challenge_from_ringzero(guild_id: int):
    guild_category_votes = category_votes.get(guild_id, {}).get('votes', {})
    guild_categories = categories[guild_id]
    guild_difficulty_votes = difficulty_votes.get(guild_id, {}).get('votes', {})
    guild_done_challenges = done_challenges[guild_id]

    def get_category_id(title):
        return next((c['id'] for c in guild_categories if c['title'] == title), None)

    def fetch_challenges(cid):
        response = requests.get(f"https://ringzer0ctf.com/api/category/challenges/{cid}")
        return response.json()['data']['categories'][0]['category']['challenges']

    def get_weighted_list(vote_dict, fallback_list):
        weighted = [key for key, votes in vote_dict.items() for _ in range(votes)]
        return weighted if weighted else fallback_list[:]

    possible_categories = get_weighted_list(guild_category_votes, [category['title'] 
        for category in guild_categories])
    possible_difficulties = get_weighted_list(guild_difficulty_votes, difficulties[guild_id])

    random.shuffle(possible_categories)
    random.shuffle(possible_difficulties)

    challenges = []

    if guild_category_votes:
        while possible_categories:
            category_title = possible_categories.pop(0)
            category_id = get_category_id(category_title)
            if not category_id:
                continue
            all_challenges = fetch_challenges(category_id)

            for difficulty in possible_difficulties:
                filtered = [
                    challenge['challenge'] for challenge in all_challenges
                    if challenge['challenge']['points'] == difficulty and
                       challenge['challenge']['title'] not in guild_done_challenges
                ]
                if filtered:
                    challenges = filtered
                    print(f"Selected voted category '{category_title}' and voted difficulty {difficulty}")
                    break

            if challenges:
                break

            fallback = [
                challenge['challenge'] for challenge in all_challenges
                if challenge['challenge']['title'] not in guild_done_challenges
            ]
            if fallback:
                challenges = fallback
                print(f"No voted difficulty match for '{category_title}', using any difficulty")
                break
            else:
                print(f"Voted category '{category_title}' exhausted, using next...")

        if not challenges:
            print("All voted categories exhausted, falling back to random category with voted difficulties.")
            all_category_titles = [category['title'] for category in guild_categories]
            random.shuffle(all_category_titles)
            for category_title in all_category_titles:
                category_id = get_category_id(category_title)
                all_challenges = fetch_challenges(category_id)

                for difficulty in possible_difficulties:
                    filtered = [
                        challenge['challenge'] for challenge in all_challenges
                        if challenge['challenge']['points'] == difficulty and
                           challenge['challenge']['title'] not in guild_done_challenges
                    ]
                    if filtered:
                        challenges = filtered
                        print(f"Found with fallback category '{category_title}' and voted difficulty {difficulty}")
                        break
                if challenges:
                    break

    else:
        for difficulty in possible_difficulties:
            for category in guild_categories:
                all_challenges = fetch_challenges(category['id'])
                filtered = [
                    challenge['challenge'] for challenge in all_challenges
                    if challenge['challenge']['points'] == difficulty and
                       challenge['challenge']['title'] not in guild_done_challenges
                ]
                if filtered:
                    challenges = filtered
                    print(f"Found with voted difficulty {difficulty} in category '{category['title']}'")
                    break
            if challenges:
                break

    # Final fallback: any challenge not done
    if not challenges:
        print("Final fallback: searching globally for any challenge not done...")
        for category in guild_categories:
            all_challenges = fetch_challenges(category['id'])
            for challenge in all_challenges:
                if challenge['challenge']['title'] not in guild_done_challenges:
                    challenges.append(challenge['challenge'])
        if not challenges:
            raise RuntimeError("All challenges appear to be done. Nothing left to assign.")

    challenge = random.choice(challenges)
    done_challenges[guild_id].append(challenge['title'])
    set_guild_entries(guild_id)
    debug_entries("challenge selected")
    return challenge

if __name__ == "__main__":
    run_discord_bot()
