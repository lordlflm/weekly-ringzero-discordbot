import os
import random
import asyncio
import calendar

import discord
from discord.ext import commands
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# TODOS
# 
# filter already done challenges
# vote for category
# vote for difficulty
# help command with usages
# use app command instead of !command
# add modes (weekly, biweekly, monthly)

SET_ANNOUNCEMENT_CHANNEL_USAGE = '!set_announcement_channel <channel name>'
START_USAGE = '!start <day> <hour>'

bot = None
announcement_channel = None
scheduler = AsyncIOScheduler()

def run_discord_bot():
    load_dotenv(override=True)
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix='!', intents=intents)

    @bot.event
    async def on_ready():
        scheduler.start()

    @bot.command()
    async def set_announcement_channel(ctx, *args):
        if len(args) < 1:
            await ctx.send(f"Wrong number of arguments. Usage: `{SET_ANNOUNCEMENT_CHANNEL_USAGE}`")
            return

        channel_name = args[0]
        guild = ctx.guild
        text_channels = [channel for channel in guild.text_channels]

        channel = next((channel for channel in text_channels if channel_name == channel.name), None)

        if channel is None:
            await ctx.send(f"'{channel_name}' is not a valid text channel")
            return

        global announcement_channel
        announcement_channel = channel

        await ctx.send(f"Successfully set '{channel_name}' as announcement channel")

    @bot.command()
    async def start(ctx, *args):
        global announcement_channel
        if announcement_channel is None:
            await ctx.send(f"Please set an announcement_channel before running start. Use `{SET_ANNOUNCEMENT_CHANNEL_USAGE}`")
            return

        if len(args) < 2:
            await ctx.send(f"Wrong number of arguments. Usage: `{START_USAGE}`")
            return

        try:
            scheduler.remove_job('announcement')
        except:
            pass

        day = day_name_to_day_abr(args[0])
        if day is None:
            await ctx.send("Invalid day")
            return

        try:
            hour = int(args[1])
        except:
            ctx.send("Invalid hour")
            return

        minute = 0
        if len(args) > 2:
            try:
                minute = int(args[2])
            except:
                ctx.send("Invalid minutes")
                return

        scheduler.add_job(job, CronTrigger(day_of_week=day, hour=hour, minute=minute), id='announcement')
        await ctx.send(f"Successfully started! Challenges will be announced on {day} at {hour}:{minute:02}")
    
    bot.run(DISCORD_TOKEN)

def day_name_to_day_abr(day_name):
    for i in range(6):
        day_names = list(calendar.day_name)
        if day_name == day_names[i] or day_name == day_names[i].lower():
            return list(calendar.day_abbr)[i]

async def job():
    challenge_info_html = get_random_challenge_from_ringzero()
    message = format_challenge_info_into_discord_message(challenge_info_html)

    global announcement_channel
    asyncio.create_task(announcement_channel.send("# 🔥 New Weekly Challenge! 🔥", embed=message))

def format_challenge_info_into_discord_message(challenge_info_html):
    anchor_tag = challenge_info_html.find('a')
    name = anchor_tag.get_text()
    url = f"https://ringzer0ctf.com{anchor_tag['href']}"
    points = challenge_info_html.find('span', class_='points').get_text()
    author = challenge_info_html.find_all('td')[-1].get_text()
    embed = discord.Embed(
        title=name,
        url=url,
        color=discord.Color.gold(),
    )
    embed.add_field(name="Points", value=points, inline=True)
    embed.add_field(name="Author", value=author, inline=True)
    embed.set_footer(text="ringzer0ctf.com")
    embed.set_image(url='https://ringzer0ctf.com/images/logo.png')

    return embed

def get_random_challenge_from_ringzero():
    response = requests.get('https://ringzer0ctf.com/challenges')
    soup = BeautifulSoup(response.content, 'html.parser')

    challenges_tables = [table for table in soup.find_all('table') if 'Challenges descriptions' in table.find('thead').get_text()]
    
    challenges = []
    for table in challenges_tables:
        category_challenges = [challenge for challenge in table.find_all('tr')]
        challenges += category_challenges

    return challenges[random.randint(0, len(challenges))]
    

if __name__ == "__main__":
    run_discord_bot()
