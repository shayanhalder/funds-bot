import actions
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import discord
from discord.ext import commands
import ssl
import certifi
from dotenv import load_dotenv
import os

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE')
TOKEN = os.getenv('TOKEN')

credentials = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# google sheets api
service = build('sheets', 'v4', credentials=credentials)
sheet = service.spreadsheets()
# Before creating the bot, add this SSL context configuration
ssl_context = ssl.create_default_context(cafile=certifi.where())
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')

@bot.command()
async def run(ctx, *, script: str):
    try:
        ctx.send(f'Testing...{script}')
    except Exception as e:
        await ctx.send(f'**Exception:** {e}')

@bot.command()
async def hello(ctx):
    await ctx.send("Hi! I'm your friendly bot!")
    
@bot.command()
async def balance(ctx):
    output: str = actions.list_balance(sheet, service)
    formatted_output: str = f"```\n{output}\n```"
    await ctx.send(formatted_output)
    
@bot.command()
async def transactions(ctx, num: str):
    if not num.isnumeric():
        await ctx.send("ERROR: Please enter an integer value")
        return
    
    success = await actions.list_transactions(sheet, service, head=int(num))
    if success:
        await ctx.send(file=discord.File('./transactions.png'))
    else:
        await ctx.send("ERROR :((")
    
if __name__ == "__main__":
    bot.run(TOKEN)
