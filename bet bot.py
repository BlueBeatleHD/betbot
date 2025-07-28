import discord
from discord.ext import commands, tasks
import json
import random
from datetime import datetime, time, timedelta
import asyncio
import aiohttp
from dotenv import load_dotenv
import os
import pytz
from collections import defaultdict
import uuid
import signal
import sys
import platform
import logging

# Windows event loop policy fix
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Data storage
user_points = {}
active_bets = {}
last_daily = {}
last_message_time = {}
voice_time_tracking = {}
voice_start_times = {}
voice_channel_points = defaultdict(int)
next_voice_payout = {}  # New tracker for next payout time
lottery_pot = 0
lottery_history = []
lottery_winners = []

# Configuration
OWNER_ROLE_NAME = "Bot Owner"
ADMIN_ROLE_NAME = "Bot Admin"
EASTERN = pytz.timezone('US/Eastern')
DAILY_RESET_HOUR = 0  # 12 AM
DAILY_RESET_MINUTE = 0
MAX_BET_DURATION = 1440  # 24 hours in minutes
MIN_BET_DURATION = 1     # 1 minute minimum

# Lottery settings
INITIAL_POT = 15000
LOTTERY_COST = 10
POWERBALL_BONUS = 50
JACKPOT_PERCENT = 0.6
MATCH5_PERCENT = 0.3
MATCH4_PERCENT = 0.1
MAIN_NUMBER_RANGE = range(1, 26)
POWERBALL_RANGE = range(1, 11)

# Voice points settings
VOICE_INTERVAL = 1800  # 30 minutes in seconds
BASE_VOICE_POINTS = 15
MIN_VOICE_POINTS = 3
VOICE_SCALE_DOWN = 3  # Points reduced per hour

TICKET_RULES = f"""
🎟 **Lottery Rules:**
- Starting Pot: {INITIAL_POT} points
- Cost: {LOTTERY_COST} points per ticket
- Pick 5 main numbers (1-25) + 1 Powerball (1-10)
- Prize Structure:
  🏆 JACKPOT (5+PB): 60% of pot • Odds: 1 in 531,300
  💎 Match 5 (5 main): 30% of pot • Odds: 1 in 59,033
  🔥 Match 4 (4 main): 10% of pot • Odds: 1 in 425
  🎯 Powerball Only: {POWERBALL_BONUS} points • Odds: 1 in 10
- Use `$quickticket [amount]` for random tickets
"""

def get_example(command_name):
    """Returns example usage for commands"""
    examples = {
        "points": "",
        "daily": "",
        "voicepoints": "",
        "voicestatus": "",
        "leaderboard": "",
        "createbet": "WillItRain? Yes No 60",
        "placebet": "abc123 1 50",
        "activebets": "",
        "lotteryrules": "",
        "quickticket": "3",
        "buyticket": "1 2 3 4 5 6",
        "lotterystats": "",
        "resetpot": "",
        "drawlottery": "",
        "resolvebet": "abc123 1",
        "cancelbet": "abc123",
        "givepoints": "@User 100", 
        "mytickets": "",
    }
    return examples.get(command_name, "")

def load_data():
    global user_points, active_bets, last_daily, last_message_time, voice_time_tracking, voice_channel_points, next_voice_payout, lottery_pot, lottery_history, lottery_winners
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            user_points = data.get('user_points', {})
            active_bets = data.get('active_bets', {})
            last_daily = data.get('last_daily', {})
            last_message_time = data.get('last_message_time', {})
            voice_time_tracking = data.get('voice_time_tracking', {})
            voice_channel_points = defaultdict(int, data.get('voice_channel_points', {}))
            next_voice_payout = data.get('next_voice_payout', {})
            lottery_pot = data.get('lottery_pot', INITIAL_POT)
            lottery_history = data.get('lottery_history', [])
            lottery_winners = data.get('lottery_winners', [])
    except (FileNotFoundError, json.JSONDecodeError):
        user_points = {}
        active_bets = {}
        last_daily = {}
        last_message_time = {}
        voice_time_tracking = {}
        voice_channel_points = defaultdict(int)
        next_voice_payout = {}
        lottery_pot = INITIAL_POT
        lottery_history = []
        lottery_winners = []
        save_data()

def save_data():
    with open('data.json', 'w') as f:
        json.dump({
            'user_points': user_points,
            'active_bets': active_bets,
            'last_daily': last_daily,
            'last_message_time': last_message_time,
            'voice_time_tracking': voice_time_tracking,
            'voice_channel_points': dict(voice_channel_points),
            'next_voice_payout': next_voice_payout,
            'lottery_pot': lottery_pot,
            'lottery_history': lottery_history,
            'lottery_winners': lottery_winners
        }, f, indent=4)

def ensure_user(user_id):
    if str(user_id) not in user_points:
        user_points[str(user_id)] = 100
        save_data()
    return user_points[str(user_id)]

def is_admin(member):
    return any(role.name == ADMIN_ROLE_NAME for role in member.roles)

def is_owner(member):
    return any(role.name == OWNER_ROLE_NAME for role in member.roles)

def handle_shutdown():
    """Cleanup function for graceful shutdown"""
    logger.info("\n🛑 Shutting down bot gracefully...")
    save_data()

def admin_required():
    async def predicate(ctx):
        if not is_admin(ctx.author):
            raise commands.CheckFailure()
        return True
    return commands.check(predicate)

def owner_required():
    async def predicate(ctx):
        if not is_owner(ctx.author):
            raise commands.CheckFailure()
        return True
    return commands.check(predicate)

class CustomHelpCommand(commands.HelpCommand):
    def __init__(self):
        super().__init__(
            command_attrs={
                'help': 'Shows help information for commands',
                'hidden': True
            }
        )
    
    async def send_bot_help(self, mapping):
        embed = discord.Embed(
            title="🎰 BetBot Command Categories",
            description=f"Use `{self.context.prefix}help <command>` for more info",
            color=discord.Color.blurple()
        )
        
        # Points Commands
        points_commands = [
            f"`{cmd.name}` - {cmd.help.split(']')[-1].strip() if ']' in cmd.help else cmd.help}"
            for cmd in bot.commands 
            if cmd.name in ['points', 'daily', 'voicepoints', 'voicestatus', 'leaderboard']
            and not cmd.hidden
        ]
        embed.add_field(
            name="💰 Points System",
            value="\n".join(points_commands) or "No commands",
            inline=False
        )
        
        # Betting Commands
        betting_commands = [
            f"`{cmd.name}` - {cmd.help.split(']')[-1].strip() if ']' in cmd.help else cmd.help}"
            for cmd in bot.commands 
            if cmd.name in ['createbet', 'placebet', 'activebets']
            and not cmd.hidden
        ]
        embed.add_field(
            name="🎲 Betting System",
            value="\n".join(betting_commands) or "No commands",
            inline=False
        )
        
        # Lottery Commands
        lottery_commands = [
            f"`{cmd.name}` - {cmd.help.split(']')[-1].strip() if ']' in cmd.help else cmd.help}"
            for cmd in bot.commands 
            if cmd.name in ['lotteryrules', 'quickticket', 'buyticket', 'lotterystats', 'mytickets']
            and not cmd.hidden
        ]
        embed.add_field(
            name="🎰 Lottery System",
            value="\n".join(lottery_commands) or "No commands",
            inline=False
        )
        
        # Admin Commands
        admin_commands = [
            f"`{cmd.name}` - {cmd.help.split(']')[-1].strip() if ']' in cmd.help else cmd.help}"
            for cmd in bot.commands 
            if cmd.name in ['resetpot', 'drawlottery', 'resolvebet', 'cancelbet']
            and not cmd.hidden
        ]
        if admin_commands:
            embed.add_field(
                name="⚙️ Admin Commands",
                value="\n".join(admin_commands),
                inline=False
            )
        
        # Owner Commands
        owner_commands = [
            f"`{cmd.name}` - {cmd.help.split(']')[-1].strip() if ']' in cmd.help else cmd.help}"
            for cmd in bot.commands 
            if cmd.name in ['givepoints']
            and not cmd.hidden
        ]
        if owner_commands:
            embed.add_field(
                name="🛡️ Owner Commands",
                value="\n".join(owner_commands),
                inline=False
            )
        
        embed.set_footer(text=f"Type {self.context.prefix}help <command> for more details")
        await self.get_destination().send(embed=embed)
    
    async def send_command_help(self, command):
        embed = discord.Embed(
            title=f"Command: {command.name}",
            description=command.help,
            color=discord.Color.green()
        )
        embed.add_field(
            name="Usage",
            value=f"```{self.context.prefix}{command.name} {command.signature}```",
            inline=False
        )
        if get_example(command.name):
            embed.add_field(
                name="Example",
                value=f"```{self.context.prefix}{get_example(command.name)}```",
                inline=False
            )
        await self.get_destination().send(embed=embed)

class RobustBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_tasks()

    def _init_tasks(self):
        @tasks.loop(time=time(DAILY_RESET_HOUR, DAILY_RESET_MINUTE, tzinfo=EASTERN))
        async def daily_reset():
            global last_daily
            last_daily.clear()
            save_data()
            now = datetime.now(EASTERN)
            logger.info(f"{now.strftime('%Y-%m-%d %H:%M:%S')} ET: ✅ Daily rewards reset")

        @tasks.loop(minutes=30)
        async def voice_points_update():
            await check_voice_time()
            logger.info("Voice points check completed at %s", datetime.now(EASTERN))

        @daily_reset.error
        async def daily_reset_error(error):
            logger.error(f"❌ Daily reset error: {error}")
            await asyncio.sleep(60)
            self.daily_reset.restart()

        @voice_points_update.error
        async def voice_points_error(error):
            logger.error(f"❌ Voice points error: {error}")
            await asyncio.sleep(60)
            self.voice_points_update.restart()

        self.daily_reset = daily_reset
        self.voice_points_update = voice_points_update

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logger.info('------')
        if not self.daily_reset.is_running():
            self.daily_reset.start()
        if not self.voice_points_update.is_running():
            self.voice_points_update.start()

    async def on_shutdown(self):
        """Handle graceful shutdown"""
        logger.info("Starting graceful shutdown...")
        # Stop all tasks
        if hasattr(self, 'daily_reset') and self.daily_reset.is_running():
            self.daily_reset.cancel()
        if hasattr(self, 'voice_points_update') and self.voice_points_update.is_running():
            self.voice_points_update.cancel()
    
        # Close the bot connection
        await self.close()
        handle_shutdown()

async def check_voice_time():
    now = datetime.now(EASTERN)
    
    for user_id, start_time in list(voice_start_times.items()):
        try:
            if user_id not in next_voice_payout:
                next_voice_payout[user_id] = (now + timedelta(seconds=VOICE_INTERVAL)).isoformat()
                continue
                
            payout_time = datetime.fromisoformat(next_voice_payout[user_id]).astimezone(EASTERN)
            
            if now >= payout_time:
                # Calculate points
                total_hours = (voice_time_tracking.get(user_id, 0) + (now - start_time).total_seconds()) / 3600
                hours_floor = int(total_hours)
                points = max(MIN_VOICE_POINTS, 
                            BASE_VOICE_POINTS - (VOICE_SCALE_DOWN * hours_floor))
                
                # Update tracking
                voice_time_tracking[user_id] = 0
                voice_channel_points[user_id] = voice_channel_points.get(user_id, 0) + points
                ensure_user(user_id)
                user_points[user_id] += points
                
                # Reset timer
                voice_start_times[user_id] = now
                next_voice_payout[user_id] = (now + timedelta(seconds=VOICE_INTERVAL)).isoformat()
                
                logger.info(f"Awarded {points} points to {user_id} for voice time")
                
        except Exception as e:
            logger.error(f"Error processing voice time for {user_id}: {e}")
    
    save_data()

# Initialize bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = RobustBot(
    command_prefix='$',
    intents=intents,
    reconnect=True,
    heartbeat_timeout=60.0,
    help_command=CustomHelpCommand()
)

@bot.event
async def on_command_error(ctx, error):
    """Handles command errors with user-friendly messages"""
    if isinstance(error, commands.MissingRequiredArgument):
        command = ctx.command
        usage = f"`{ctx.prefix}{command.name} {command.usage or command.signature}`"
        example = f"\n\nExample: `{ctx.prefix}{command.name} {get_example(command.name)}`" if get_example(command.name) else ""
        
        embed = discord.Embed(
            title=f"❌ Missing Argument for {command.name}",
            description=f"**Correct Usage:**\n{usage}{example}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Command not found. Use `{ctx.prefix}help` for available commands.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.CheckFailure):
        if is_admin(ctx.author):
            await ctx.send(f"❌ You need the '{OWNER_ROLE_NAME}' role to use this command.")
        else:
            await ctx.send(f"❌ You need the '{ADMIN_ROLE_NAME}' role to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument: {error}")
    else:
        logger.error(f"⚠️ Unhandled error in command {ctx.command}: {error}")
        await ctx.send("❌ An unexpected error occurred. Please try again later.")

# Activity tracking
@bot.event
async def on_message(message):
    if message.author.bot:
        return await bot.process_commands(message)
    
    user_id = str(message.author.id)
    ensure_user(user_id)
    
    now = datetime.now()
    last_time = last_message_time.get(user_id)
    
    if last_time is None or (now - datetime.fromisoformat(last_time)).seconds >= 60:
        user_points[user_id] += 1
        last_message_time[user_id] = now.isoformat()
        save_data()
    
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    user_id = str(member.id)
    now = datetime.now(EASTERN)
    
    # User left voice channel or was disconnected
    if before.channel and not after.channel:
        if user_id in voice_start_times:
            time_spent = (now - voice_start_times[user_id]).total_seconds()
            voice_time_tracking[user_id] = voice_time_tracking.get(user_id, 0) + time_spent
            del voice_start_times[user_id]
            if user_id in next_voice_payout:
                del next_voice_payout[user_id]
    
    # User joined voice channel
    elif after.channel and not before.channel:
        voice_start_times[user_id] = now
        next_voice_payout[user_id] = (now + timedelta(seconds=VOICE_INTERVAL)).isoformat()
    
    # User moved between channels
    elif before.channel and after.channel and before.channel != after.channel:
        if user_id in voice_start_times:
            time_spent = (now - voice_start_times[user_id]).total_seconds()
            voice_time_tracking[user_id] = voice_time_tracking.get(user_id, 0) + time_spent
        voice_start_times[user_id] = now
        next_voice_payout[user_id] = (now + timedelta(seconds=VOICE_INTERVAL)).isoformat()
    
    # User deafened/undeafened
    elif before.channel and after.channel and before.channel == after.channel:
        if before.self_deaf != after.self_deaf:
            if after.self_deaf:  # User deafened
                if user_id in voice_start_times:
                    time_spent = (now - voice_start_times[user_id]).total_seconds()
                    voice_time_tracking[user_id] = voice_time_tracking.get(user_id, 0) + time_spent
                    del voice_start_times[user_id]
                    if user_id in next_voice_payout:
                        del next_voice_payout[user_id]
            else:  # User undeafened
                voice_start_times[user_id] = now
                next_voice_payout[user_id] = (now + timedelta(seconds=VOICE_INTERVAL)).isoformat()
    
    save_data()

@bot.command(name='voicestatus', help='💰 Check your voice points status and next payout time')
async def voice_status(ctx):
    user_id = str(ctx.author.id)
    points = voice_channel_points.get(user_id, 0)
    now = datetime.now(EASTERN)
    
    status_msg = "🔴 Not currently in a voice channel"
    current_rate = BASE_VOICE_POINTS
    
    if user_id in next_voice_payout:
        payout_time = datetime.fromisoformat(next_voice_payout[user_id]).astimezone(EASTERN)
        time_left = payout_time - now
        minutes_left = max(0, int(time_left.total_seconds() / 60))
        status_msg = f"⏳ Next payout in ~{minutes_left} minutes"
        
        if user_id in voice_time_tracking:
            total_hours = voice_time_tracking.get(user_id, 0) / 3600
            if user_id in voice_start_times:
                total_hours += (now - voice_start_times[user_id]).total_seconds() / 3600
            hours_floor = int(total_hours)
            current_rate = max(MIN_VOICE_POINTS, BASE_VOICE_POINTS - (VOICE_SCALE_DOWN * hours_floor))
    
    embed = discord.Embed(
        title="🎧 Voice Points Status",
        description=f"{ctx.author.mention}'s voice activity",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Earned", value=f"{points} points", inline=True)
    embed.add_field(name="Status", value=status_msg, inline=True)
    embed.add_field(
        name="Current Rate",
        value=f"Earning {current_rate} points per {VOICE_INTERVAL//60} minutes",
        inline=False
    )
    
    await ctx.send(embed=embed)
            
# Points System Commands
@bot.command(
    name='points',
    help='💰 Check your points balance'
)
async def check_points(ctx):
    points = ensure_user(ctx.author.id)
    await ctx.send(f'{ctx.author.mention}, you have {points} points.')

@bot.command(
    name='daily',
    help='💰 Claim your daily points (100-150 points)'
)
async def daily_points(ctx):
    user_id = str(ctx.author.id)
    now = datetime.now(EASTERN)
    
    if user_id in last_daily:
        last_claim_date = datetime.fromisoformat(last_daily[user_id]).astimezone(EASTERN).date()
        if now.date() == last_claim_date:
            await ctx.send(f"{ctx.author.mention}, you've already claimed your daily today!")
            return
    
    reward = random.randint(100, 150)
    ensure_user(ctx.author.id)
    user_points[user_id] += reward
    last_daily[user_id] = now.isoformat()
    save_data()
    
    embed = discord.Embed(
        title="🎉 Daily Reward Claimed",
        description=f"{ctx.author.mention} received {reward} points!",
        color=discord.Color.gold()
    )
    embed.add_field(name="New Balance", value=f"{user_points[user_id]} points")
    await ctx.send(embed=embed)

@bot.command(
    name='voicepoints',
    help='💰 Check your voice chat points balance'
)
async def check_voice_points(ctx):
    user_id = str(ctx.author.id)
    points = voice_channel_points.get(user_id, 0)
    await ctx.send(f'{ctx.author.mention}, you have earned {points} points from voice chat.')

@bot.command(
    name='leaderboard',
    help='💰 Show top 10 users by points'
)
async def show_leaderboard(ctx):
    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:10]
    
    embed = discord.Embed(
        title="🏆 Top 10 Users",
        color=discord.Color.blurple()
    )
    
    for i, (user_id, points) in enumerate(sorted_users, 1):
        user = await bot.fetch_user(int(user_id))
        embed.add_field(
            name=f"{i}. {user.name}",
            value=f"{points} points",
            inline=False
        )
    
    await ctx.send(embed=embed)

# Betting System Commands
@bot.command(
    name='createbet',
    help='🎲 Create a new betting event',
    usage="<name> <option1> <option2> [duration_minutes=5]"
)
async def create_bet(ctx, name: str, option1: str, option2: str, duration_minutes: int = 5):
    if duration_minutes < MIN_BET_DURATION:
        return await ctx.send(f"❌ Minimum bet duration is {MIN_BET_DURATION} minute.")
    if duration_minutes > MAX_BET_DURATION:
        return await ctx.send(f"❌ Maximum bet duration is {MAX_BET_DURATION} minutes (24 hours).")
    
    bet_id = str(uuid.uuid4())[:8]
    end_time = datetime.now() + timedelta(minutes=duration_minutes)
    
    active_bets[bet_id] = {
        'name': name,
        'options': [option1, option2],
        'bets': {option1: {}, option2: {}},
        'end_time': end_time.isoformat(),
        'creator': ctx.author.id,
        'resolved': False
    }
    save_data()
    
    embed = discord.Embed(
        title=f"🎲 New Bet Created by {ctx.author.display_name}",
        description=f"**{name}**\nBet ID: `{bet_id}`",
        color=discord.Color.blue(),
        timestamp=end_time
    )
    embed.add_field(name="Option 1️⃣", value=option1, inline=True)
    embed.add_field(name="Option 2️⃣", value=option2, inline=True)
    embed.add_field(
        name="How to Bet",
        value=f"Use `{ctx.prefix}placebet {bet_id} <1 or 2> <amount>`",
        inline=False
    )
    embed.set_footer(text=f"Betting closes at")
    
    await ctx.send(embed=embed)

@bot.command(
    name='placebet',
    help='🎲 Place a bet on an event',
    usage="<bet_id> <option_number> <amount>"
)
async def place_bet(ctx, bet_id: str, option_number: int, amount: int):
    user_id = str(ctx.author.id)
    ensure_user(user_id)
    
    if bet_id not in active_bets:
        return await ctx.send("❌ Invalid bet ID. Use `$createbet` to make a new one.")
    
    bet = active_bets[bet_id]
    
    if datetime.fromisoformat(bet['end_time']) < datetime.now():
        return await ctx.send("❌ Betting is closed for this event.")
    
    if user_points[user_id] < amount:
        return await ctx.send(f"❌ You only have {user_points[user_id]} points.")
    
    if option_number not in [1, 2]:
        return await ctx.send("❌ Please choose option 1 or 2.")
    
    selected_option = bet['options'][option_number - 1]
    
    previous_bet = bet['bets'][selected_option].get(user_id, 0)
    bet['bets'][selected_option][user_id] = previous_bet + amount
    user_points[user_id] -= amount
    save_data()
    
    embed = discord.Embed(
        title="✅ Bet Placed",
        description=f"{ctx.author.mention} bet {amount} points on {selected_option}",
        color=discord.Color.green()
    )
    embed.add_field(name="Total Bet", value=f"{previous_bet + amount} points on this option")
    embed.add_field(name="Remaining Points", value=f"{user_points[user_id]} points")
    await ctx.send(embed=embed)

@bot.command(
    name='activebets',
    help='🎲 Show all active betting events'
)
async def show_active_bets(ctx):
    if not active_bets:
        return await ctx.send("No active bets currently running.")
    
    embed = discord.Embed(
        title="🎲 Active Bets",
        color=discord.Color.blue()
    )
    
    for bet_id, bet in active_bets.items():
        if not bet['resolved'] and datetime.fromisoformat(bet['end_time']) > datetime.now():
            creator = await bot.fetch_user(bet['creator'])
            time_left = datetime.fromisoformat(bet['end_time']) - datetime.now()
            
            embed.add_field(
                name=f"ID: {bet_id} - {bet['name']}",
                value=(
                    f"Creator: {creator.mention}\n"
                    f"Options: 1) {bet['options'][0]} | 2) {bet['options'][1]}\n"
                    f"Time left: {str(time_left).split('.')[0]}\n"
                    f"Cancel with: `{ctx.prefix}cancelbet {bet_id}`"
                ),
                inline=False
            )
    
    await ctx.send(embed=embed)

# Lottery System Commands
@bot.command(
    name='lotteryrules',
    help='🎰 Show lottery rules and current pot'
)
async def show_lottery_rules(ctx):
    embed = discord.Embed(
        title="🎰 Lottery Information",
        description=TICKET_RULES,
        color=0x00FF00
    )
    embed.add_field(
        name="Current Pot", 
        value=f"{lottery_pot} points ({len(lottery_history)} tickets sold)",
        inline=False
    )
    embed.add_field(
        name="Last Draw",
        value=lottery_winners[-1]['main'] + [lottery_winners[-1]['powerball']] if lottery_winners else "No draws yet",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(
    name='quickticket',
    help='🎰 Generate AND buy random lottery tickets',
    usage="[amount=1]"
)
async def quick_pick(ctx, amount: int = 1):
    user_id = str(ctx.author.id)
    ensure_user(user_id)
    
    if amount <= 0:
        return await ctx.send("❌ Amount must be at least 1")
    if amount > 5:
        return await ctx.send("❌ Max 5 tickets at once (for clean formatting)")
    
    total_cost = LOTTERY_COST * amount
    if user_points[user_id] < total_cost:
        return await ctx.send(
            f"❌ You need {total_cost} points for {amount} tickets "
            f"(You have: {user_points[user_id]})"
        )
    
    # Process purchase
    user_points[user_id] -= total_cost
    global lottery_pot
    lottery_pot += total_cost
    
    # Generate tickets
    tickets = []
    for _ in range(amount):
        main_numbers = sorted(random.sample(MAIN_NUMBER_RANGE, 5))
        powerball = random.choice(list(POWERBALL_RANGE))
        tickets.append((main_numbers, powerball))
        lottery_history.append({
            'user': user_id,
            'numbers': main_numbers,
            'powerball': powerball,
            'time': datetime.now().isoformat()
        })
    
    save_data()
    
    # Bingo-style display
    def create_bingo_card(numbers, pb):
        card = "```diff\n"
        card += "+-----+-----+-----+-----+-----+-----+\n"
        card += "| Main Numbers           | Powerball |\n"
        card += "+-----+-----+-----+-----+-----+-----+\n"
        num_cells = "|"
        for num in numbers:
            num_cells += f" {str(num).center(3)} |"
        num_cells += f" {f'PB{pb}'.center(3)} |"
        card += num_cells + "\n"
        card += "+-----+-----+-----+-----+-----+-----+\n"
        card += "```"
        return card
    
    visual_tickets = []
    for i, (nums, pb) in enumerate(tickets):
        visual_tickets.append(
            f"**Ticket #{i+1}**\n"
            f"{create_bingo_card(nums, pb)}"
        )
    
    embed = discord.Embed(
        title=f"🎰 {'Tickets' if amount > 1 else 'Ticket'} Purchased",
        color=0x00FF00 if amount > 1 else 0x7289DA
    )
    
    embed.add_field(
        name=f"Your {'Tickets' if amount > 1 else 'Ticket'}",
        value="\n".join(visual_tickets),
        inline=False
    )
    
    embed.add_field(
        name="Transaction Summary",
        value=(
            f"```diff\n"
            f"- Spent: {total_cost} points\n"
            f"+ Tickets: {amount}\n"
            f"= Balance: {user_points[user_id]} points\n"
            f"```"
            f"🏦 Pot: {lottery_pot} points"
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(
    name='buyticket',
    help='🎰 Buy lottery ticket with specific numbers',
    usage="<num1> <num2> <num3> <num4> <num5> <powerball>"
)
async def buy_lottery_ticket(ctx, n1: int, n2: int, n3: int, n4: int, n5: int, pb: int):
    user_id = str(ctx.author.id)
    ensure_user(user_id)
    
    # Validate numbers
    main_numbers = {n1, n2, n3, n4, n5}
    if len(main_numbers) != 5 or any(n not in MAIN_NUMBER_RANGE for n in main_numbers):
        return await ctx.send("❌ Pick 5 unique numbers between 1-25")
    if pb not in POWERBALL_RANGE:
        return await ctx.send("❌ Powerball must be 1-10")
    
    # Charge points
    if user_points[user_id] < LOTTERY_COST:
        return await ctx.send(f"❌ You need {LOTTERY_COST} points (You have: {user_points[user_id]})")
    
    user_points[user_id] -= LOTTERY_COST
    global lottery_pot
    lottery_pot += LOTTERY_COST
    
    # Store ticket
    ticket = {
        'user': user_id,
        'numbers': sorted(main_numbers),
        'powerball': pb,
        'time': datetime.now().isoformat()
    }
    lottery_history.append(ticket)
    save_data()
    
    # Create bingo display
    def create_bingo_card(numbers, pb):
        card = "```diff\n"
        card += "+-----+-----+-----+-----+-----+-----+\n"
        card += "| Main Numbers           | Powerball |\n"
        card += "+-----+-----+-----+-----+-----+-----+\n"
        num_cells = "|"
        for num in numbers:
            num_cells += f" {str(num).center(3)} |"
        num_cells += f" {f'PB{pb}'.center(3)} |"
        card += num_cells + "\n"
        card += "+-----+-----+-----+-----+-----+-----+\n"
        card += "```"
        return card
    
    embed = discord.Embed(
        title="🎟️ Custom Ticket Purchased",
        color=0x7289DA
    )
    embed.add_field(
        name="Your Ticket",
        value=create_bingo_card(sorted(main_numbers), pb),
        inline=False
    )
    embed.add_field(
        name="Transaction",
        value=(
            f"```diff\n"
            f"- {LOTTERY_COST} points\n"
            f"= Balance: {user_points[user_id]} points\n"
            f"```"
            f"🏦 Pot: {lottery_pot} points"
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)
    
@bot.command(
    name='mytickets',
    help='🎰 View your lottery tickets with perfect alignment',
    usage=""
)
async def view_my_tickets(ctx):
    user_id = str(ctx.author.id)
    user_tickets = sorted(
        [t for t in lottery_history if t['user'] == user_id],
        key=lambda x: x['time'],
        reverse=True
    )
    
    if not user_tickets:
        return await ctx.send("You haven't purchased any tickets yet!")

    def create_bingo_card(numbers, pb, index=None, purchase_time=None):
        card = [
            "```diff",
            "+-------+-------+-------+-------+-------+---------+",
        ]
        
        if index is not None and purchase_time is not None:
            header = f" Ticket #{index+1} - {purchase_time} "
            card.append(f"|{header.center(47)} |")
            card.append("+-------+-------+-------+-------+-------+---------+")
        
        card.extend([
            "| Main Numbers                        | Powerball |",
            "+-------+-------+-------+-------+-------+---------+",
            f"|  {str(numbers[0]).center(3)}  |  {str(numbers[1]).center(3)}  |  {str(numbers[2]).center(3)}  |  {str(numbers[3]).center(3)}  |  {str(numbers[4]).center(3)}  |    {str(pb).center(3)}  |",
            "+-------+-------+-------+-------+-------+---------+",
            "```"
        ])
        
        return "\n".join(card)

    # Pagination and display logic would go here
    # [Same as previous examples]

    # Create pages with 3 tickets each
    tickets_per_page = 3
    pages = []
    
    for i in range(0, len(user_tickets), tickets_per_page):
        embed = discord.Embed(
            title=f"🎟 Your Lottery Tickets ({len(user_tickets)} total)",
            color=discord.Color.gold()
        )
        
        page_tickets = user_tickets[i:i+tickets_per_page]
        visual_display = []
        
        for j, ticket in enumerate(page_tickets, 1):
            purchase_time = datetime.fromisoformat(ticket['time']).strftime('%m/%d %I:%M %p')
            visual_display.append(
                create_bingo_card(
                    ticket['numbers'],
                    ticket['powerball'],
                    index=i+j-1,
                    purchase_time=purchase_time
                )
            )
        
        embed.description = "\n".join(visual_display)
        embed.set_footer(text=f"Page {i//tickets_per_page + 1}/{(len(user_tickets)-1)//tickets_per_page + 1}")
        pages.append(embed)
    
    # Send first page with pagination controls
    if len(pages) == 1:
        return await ctx.send(embed=pages[0])
    
    message = await ctx.send(embed=pages[0])
    
    # Add reactions for navigation
    for emoji in ["⬅️", "➡️", "❌"]:
        await message.add_reaction(emoji)
    
    # Pagination logic
    def check(reaction, user):
        return user == ctx.author and reaction.message.id == message.id and str(reaction.emoji) in ["⬅️", "➡️", "❌"]
    
    current_page = 0
    
    while True:
        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=60.0, check=check)
            
            if str(reaction.emoji) == "➡️" and current_page < len(pages) - 1:
                current_page += 1
                await message.edit(embed=pages[current_page])
            elif str(reaction.emoji) == "⬅️" and current_page > 0:
                current_page -= 1
                await message.edit(embed=pages[current_page])
            elif str(reaction.emoji) == "❌":
                await message.delete()
                return
            
            try:
                await message.remove_reaction(reaction, user)
            except:
                pass
                
        except asyncio.TimeoutError:
            try:
                await message.clear_reactions()
            except:
                pass
            break

@bot.command(
    name='lotterystats',
    help='🎰 Show historical lottery stats'
)
async def lottery_stats(ctx):
    if not lottery_winners:
        return await ctx.send("No draws yet!")
    
    # Calculate frequency
    main_counts = defaultdict(int)
    pb_counts = defaultdict(int)
    
    for draw in lottery_winners:
        for num in draw['main']:
            main_counts[num] += 1
        pb_counts[draw['powerball']] += 1
    
    # Top hot numbers
    hot_main = sorted(main_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    hot_pb = sorted(pb_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Cold numbers (never or rarely drawn)
    all_main = set(MAIN_NUMBER_RANGE)
    drawn_main = set(main_counts.keys())
    cold_main = sorted(all_main - drawn_main) or ["None"]
    
    embed = discord.Embed(
        title="📊 Lottery Statistics",
        description=f"Analyzing {len(lottery_winners)} past draws",
        color=0x00FFFF
    )
    embed.add_field(
        name="🔥 Hot Main Numbers",
        value="\n".join(f"{num}: {count}x" for num, count in hot_main),
        inline=True
    )
    embed.add_field(
        name="❄️ Cold Main Numbers",
        value=", ".join(map(str, cold_main[:5])),
        inline=True
    )
    embed.add_field(
        name="🔥 Hot Powerballs",
        value="\n".join(f"{num}: {count}x" for num, count in hot_pb),
        inline=False
    )
    await ctx.send(embed=embed)

## Owner Commands
@bot.command(
    name='givepoints',
    help='🛡️ [OWNER] Give points to a user',
    usage="<user> <amount>"
)
@owner_required()
async def give_points(ctx, user: discord.Member, amount: int):
    try:
        if user.bot:
            raise commands.BadArgument("Cannot give points to bots!")
        if amount <= 0:
            raise commands.BadArgument("Amount must be positive!")
        if amount > 10000:
            raise commands.BadArgument("Cannot give more than 10,000 points at once!")
        
        ensure_user(user.id)
        user_points[str(user.id)] += amount
        save_data()
        
        embed = discord.Embed(
            title="✅ Points Added",
            description=f"{ctx.author.mention} gave {amount} points to {user.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="New Balance", value=f"{user_points[str(user.id)]} points")
        await ctx.send(embed=embed)

    except commands.BadArgument as e:
        await ctx.send(f"❌ {e}", delete_after=15)

@bot.command(
    name='shutdown',
    help='🛑 [OWNER] Shutdown the bot gracefully',
    hidden=True
)
@owner_required()
async def shutdown_bot(ctx):
    """Gracefully shuts down the bot"""
    embed = discord.Embed(
        title="🛑 Bot Shutdown",
        description="Shutting down the bot gracefully...",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)
    logger.info(f"Shutdown command received from {ctx.author}")
    
    # Create a new task to avoid blocking
    asyncio.create_task(bot.on_shutdown())

# Admin Commands
@bot.command(
    name='resetpot',
    help='⚙️ [ADMIN] Reset lottery pot to initial amount',
    usage=""
)
@admin_required()
async def reset_pot(ctx):
    global lottery_pot
    lottery_pot = INITIAL_POT
    save_data()
    await ctx.send(f"✅ Pot reset to initial amount of {INITIAL_POT} points")

@bot.command(
    name='drawlottery',
    help='⚙️ [ADMIN] Run lottery draw',
    usage=""
)
@admin_required()
async def draw_lottery(ctx):
    global lottery_pot, lottery_history, lottery_winners
    
    if len(lottery_history) < 3:
        return await ctx.send("❌ Need at least 3 tickets to draw")
    
    # Generate winning numbers
    winning_main = sorted(random.sample(MAIN_NUMBER_RANGE, 5))
    winning_pb = random.choice(list(POWERBALL_RANGE))
    
    # Record draw
    lottery_winners.append({
        'main': winning_main,
        'powerball': winning_pb,
        'time': datetime.now().isoformat()
    })
    
    # Check winners
    jackpot_winners = [
        t for t in lottery_history 
        if set(t['numbers']) == set(winning_main) and t['powerball'] == winning_pb
    ]
    match5_winners = [
        t for t in lottery_history 
        if set(t['numbers']) == set(winning_main) and t['powerball'] != winning_pb
    ]
    match4_winners = [
        t for t in lottery_history 
        if len(set(t['numbers']) & set(winning_main)) == 4
    ]
    powerball_winners = [t for t in lottery_history if t['powerball'] == winning_pb]
    
    # Calculate payouts
    powerball_cost = len(powerball_winners) * POWERBALL_BONUS
    remaining_pot = max(0, lottery_pot - powerball_cost)
    
    # Build result message
    result_msg = []
    
    # Pay Powerball winners first
    for ticket in powerball_winners:
        user_points[ticket['user']] += POWERBALL_BONUS
        result_msg.append(f"🎯 Powerball: <@{ticket['user']}> +{POWERBALL_BONUS} points")
    
    # Pay jackpot winners (60%)
    if jackpot_winners:
        jackpot_prize = int(remaining_pot * JACKPOT_PERCENT / len(jackpot_winners))
        for ticket in jackpot_winners:
            user_points[ticket['user']] += jackpot_prize
            result_msg.append(f"🏆 **JACKPOT**: <@{ticket['user']}> won {jackpot_prize} points!")
        remaining_pot -= jackpot_prize * len(jackpot_winners)
    
    # Pay match5 winners (30%)
    if match5_winners:
        match5_prize = int(remaining_pot * MATCH5_PERCENT / len(match5_winners))
        for ticket in match5_winners:
            user_points[ticket['user']] += match5_prize
            result_msg.append(f"💰 Match 5: <@{ticket['user']}> +{match5_prize} points")
        remaining_pot -= match5_prize * len(match5_winners)
    
    # Pay match4 winners (10%)
    if match4_winners:
        match4_prize = int(remaining_pot * MATCH4_PERCENT / len(match4_winners))
        for ticket in match4_winners:
            user_points[ticket['user']] += match4_prize
            result_msg.append(f"🎫 Match 4: <@{ticket['user']}> +{match4_prize} points")
        remaining_pot -= match4_prize * len(match4_winners)
    
    # Determine new pot
    new_pot = remaining_pot if not jackpot_winners else 0
    
    # Update and save
    lottery_pot = new_pot
    lottery_history.clear()
    save_data()
    
    # Send results
    embed = discord.Embed(
        title=f"🎰 Lottery Draw (Pot: {lottery_pot} points)",
        description=(
            f"Winning Numbers: **{', '.join(map(str, winning_main))}** + **{winning_pb}**\n"
            f"```{len(jackpot_winners)} Jackpot Winner(s)\n"
            f"{len(match5_winners)} Match-5 Winner(s)\n"
            f"{len(match4_winners)} Match-4 Winner(s)\n"
            f"{len(powerball_winners)} Powerball Winner(s)```"
        ),
        color=0xFFD700
    )
    if result_msg:
        embed.add_field(name="Payouts", value="\n".join(result_msg), inline=False)
    if new_pot > 0:
        embed.add_field(name="💎 Jackpot Rolls Over", value=f"New pot: {new_pot} points", inline=False)
    await ctx.send(embed=embed)

@bot.command(
    name='resolvebet',
    help='⚙️ [ADMIN] Resolve a betting event',
    usage="<bet_id> <winning_option_number>"
)
@admin_required()
async def resolve_bet(ctx, bet_id: str, winning_option_number: int):
    if bet_id not in active_bets:
        return await ctx.send("❌ Invalid bet ID.")
    
    bet = active_bets[bet_id]
    
    if bet['resolved']:
        return await ctx.send("❌ This bet has already been resolved.")
    
    if winning_option_number not in [1, 2]:
        return await ctx.send("❌ Please choose winning option 1 or 2.")
    
    winning_option = bet['options'][winning_option_number - 1]
    losing_option = bet['options'][0] if winning_option_number == 2 else bet['options'][1]
    
    total_winning = sum(bet['bets'][winning_option].values())
    total_losing = sum(bet['bets'][losing_option].values())
    
    embed = discord.Embed(
        title=f"🏆 Bet Resolved: {bet['name']}",
        description=f"Winning option: {winning_option}",
        color=discord.Color.gold()
    )
    
    if total_winning == 0:
        for option in bet['options']:
            for user_id, amount in bet['bets'][option].items():
                user_points[user_id] += amount
        
        embed.description = "No winners - all bets returned"
        await ctx.send(embed=embed)
    else:
        winners = []
        for user_id, amount in bet['bets'][winning_option].items():
            winnings = amount + (amount / total_winning) * total_losing
            user_points[user_id] += int(winnings)
            winners.append((user_id, amount, int(winnings)))
        
        bet['resolved'] = True
        save_data()
        
        winner_text = []
        for user_id, bet_amount, winnings in sorted(winners, key=lambda x: x[1], reverse=True)[:5]:
            user = await bot.fetch_user(int(user_id))
            winner_text.append(f"{user.name}: +{winnings - bet_amount} (total {winnings})")
        
        embed.add_field(
            name="Top Winners",
            value="\n".join(winner_text) if winner_text else "No winners",
            inline=False
        )
        embed.add_field(
            name="Payout Details",
            value=f"Total pot: {total_winning + total_losing}\nWinners share: {total_losing}",
            inline=False
        )
        await ctx.send(embed=embed)

@bot.command(
    name='cancelbet',
    help='⚙️ [ADMIN] Cancel an active bet',
    usage="<bet_id>"
)
@admin_required()
async def cancel_bet(ctx, bet_id: str):
    if bet_id not in active_bets:
        return await ctx.send("❌ Invalid bet ID. Use `$activebets` to see current bets.")
    
    bet = active_bets[bet_id]
    
    if bet['resolved']:
        return await ctx.send("❌ This bet was already resolved.")
    
    if datetime.fromisoformat(bet['end_time']) < datetime.now():
        return await ctx.send("❌ This bet has already ended (use `$resolvebet` instead).")

    # Refund all bets
    refunds = 0
    for option in bet['options']:
        for user_id, amount in bet['bets'][option].items():
            user_points[user_id] += amount
            refunds += amount
    
    # Mark as resolved and save
    bet['resolved'] = True
    save_data()
    
    embed = discord.Embed(
        title="❌ Bet Cancelled",
        description=f"All {refunds} points have been refunded.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Bet Name", value=bet['name'])
    embed.add_field(name="Options", value=f"1) {bet['options'][0]}\n2) {bet['options'][1]}")
    await ctx.send(embed=embed)

if __name__ == "__main__":
    try:
        load_data()
        bot.run(os.getenv('DISCORD_TOKEN'))
    except discord.LoginFailure:
        logger.error("❌ Failed to login. Check your bot token.")
    except KeyboardInterrupt:
        logger.info("\n🛑 Received shutdown signal, saving data...")
        save_data()
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        save_data()
    finally:
        save_data()