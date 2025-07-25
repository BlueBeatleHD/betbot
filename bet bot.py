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

# Configuration
ADMIN_ROLE_NAME = "Bot Admin"
EASTERN = pytz.timezone('US/Eastern')
DAILY_RESET_HOUR = 0  # 12 AM
DAILY_RESET_MINUTE = 0
MAX_BET_DURATION = 1440  # 24 hours in minutes
MIN_BET_DURATION = 1     # 1 minute minimum

def get_example(command_name):
    """Returns example usage for commands"""
    examples = {
        "createbet": "WillItRain? Yes No 60",
        "placebet": "abc123 1 50",
        "resolvebet": "abc123 1",
        "cancelbet": "abc123",
        "givepoints": "@User 100",
        "daily": "",
        "points": "",
        "voicepoints": "",
        "leaderboard": "",
        "activebets": ""
    }
    return examples.get(command_name, "")

def load_data():
    global user_points, active_bets, last_daily, last_message_time, voice_time_tracking, voice_channel_points
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            user_points = data.get('user_points', {})
            active_bets = data.get('active_bets', {})
            last_daily = data.get('last_daily', {})
            last_message_time = data.get('last_message_time', {})
            voice_time_tracking = data.get('voice_time_tracking', {})
            voice_channel_points = defaultdict(int, data.get('voice_channel_points', {}))
    except (FileNotFoundError, json.JSONDecodeError):
        user_points = {}
        active_bets = {}
        last_daily = {}
        last_message_time = {}
        voice_time_tracking = {}
        voice_channel_points = defaultdict(int)
        save_data()

def save_data():
    with open('data.json', 'w') as f:
        json.dump({
            'user_points': user_points,
            'active_bets': active_bets,
            'last_daily': last_daily,
            'last_message_time': last_message_time,
            'voice_time_tracking': voice_time_tracking,
            'voice_channel_points': dict(voice_channel_points)
        }, f, indent=4)

def ensure_user(user_id):
    if str(user_id) not in user_points:
        user_points[str(user_id)] = 100
        save_data()
    return user_points[str(user_id)]

def is_admin(member):
    return any(role.name == ADMIN_ROLE_NAME for role in member.roles)

def handle_shutdown():
    """Cleanup function for graceful shutdown"""
    logger.info("\n🛑 Shutting down bot gracefully...")
    save_data()  # Ensure all data is saved
    sys.exit(0)

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

        @tasks.loop(minutes=5)
        async def voice_points_update():
            await self.check_voice_time()

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

    async def check_voice_time(self):
        now = datetime.now()
        users_to_remove = []
        
        for user_id, start_time in voice_start_times.items():
            time_spent = (now - start_time).total_seconds()
            
            if time_spent >= 300:  # 5 minutes in seconds
                voice_time_tracking[user_id] = voice_time_tracking.get(user_id, 0) + time_spent
                voice_start_times[user_id] = now
                
                total_hours = voice_time_tracking.get(user_id, 0) / 3600
                hours_floor = int(total_hours)
                points_to_add = max(3, 15 - (3 * min(4, hours_floor)))
                
                voice_channel_points[user_id] = voice_channel_points.get(user_id, 0) + points_to_add
                ensure_user(user_id)
                user_points[user_id] += points_to_add
                voice_time_tracking[user_id] = 0
        
        save_data()

    async def on_shutdown(self):
        """Handle graceful shutdown"""
        await self.close()
        handle_shutdown()

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logger.info('------')
        if not self.daily_reset.is_running():
            self.daily_reset.start()
        if not self.voice_points_update.is_running():
            self.voice_points_update.start()

# Initialize bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = RobustBot(
    command_prefix='$',
    intents=intents,
    reconnect=True,
    heartbeat_timeout=60.0
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

# Voice state tracking
@bot.event
async def on_voice_state_update(member, before, after):
    user_id = str(member.id)
    now = datetime.now()
    
    if before.channel != after.channel:
        if before.channel and user_id in voice_start_times:
            time_spent = (now - voice_start_times[user_id]).total_seconds()
            if not before.self_deaf:
                voice_time_tracking[user_id] = voice_time_tracking.get(user_id, 0) + time_spent
            del voice_start_times[user_id]
        
        if after.channel and not after.self_deaf:
            voice_start_times[user_id] = now
    
    elif after.channel and (before.self_deaf != after.self_deaf):
        if after.self_deaf:
            if user_id in voice_start_times:
                time_spent = (now - voice_start_times[user_id]).total_seconds()
                voice_time_tracking[user_id] = voice_time_tracking.get(user_id, 0) + time_spent
                del voice_start_times[user_id]
        else:
            voice_start_times[user_id] = now

# Points system
@bot.command(name='points', help='Check your points balance')
async def check_points(ctx):
    points = ensure_user(ctx.author.id)
    await ctx.send(f'{ctx.author.mention}, you have {points} points.')

@bot.command(name='voicepoints', help='Check your voice chat points balance')
async def check_voice_points(ctx):
    user_id = str(ctx.author.id)
    points = voice_channel_points.get(user_id, 0)
    await ctx.send(f'{ctx.author.mention}, you have earned {points} points from voice chat.')

@bot.command(
    name='daily',
    help='Claim your daily points (100-150 points)'
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
    name='leaderboard',
    help='Show top 10 users by points'
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

# Admin commands
def admin_required():
    async def predicate(ctx):
        if not is_admin(ctx.author):
            raise commands.CheckFailure()
        return True
    return commands.check(predicate)

@bot.command(
    name='givepoints',
    help='Give points to a user (Admin only)',
    usage="<user> <amount>"
)
@admin_required()
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

# Betting system
@bot.command(
    name='activebets',
    help='Show all active betting events'
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

@bot.command(
    name='createbet',
    help='Create a new betting event (1 min to 24 hours)',
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
    help='Place a bet on an event',
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
    name='resolvebet',
    help='Resolve a betting event (Admin only)',
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
    help='Cancel an active bet and refund all points (Admin only)',
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

# Start the bot
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
        # Final safeguard to ensure data is saved
        save_data()