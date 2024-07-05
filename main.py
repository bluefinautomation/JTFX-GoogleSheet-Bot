import json
import stripe
import gspread
import discord
from discord.ext import commands
from flask import Flask, request, jsonify, redirect
from oauth2client.service_account import ServiceAccountCredentials
import os
from decouple import config
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import asyncio
from threading import Thread
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Stripe API keys
stripe.api_key = config('STRIPE_API_KEY')
webhook_secret = config('STRIPE_WEBHOOK_KEY')

# Paths to credentials and token file
TOKEN_PATH = 'token.pickle'
CREDENTIALS_PATH = './client_secret_1050871309466-orgrcac7400fr802e43bieo5952jlut7.apps.googleusercontent.com.json'

# Google Sheets setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

def authenticate_gspread():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_console()
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(creds, token)
    return creds

creds = authenticate_gspread()
client = gspread.authorize(creds)
sheet = client.open("ReformFXSubSheet").sheet1  # Adjust to your sheet

# Function to add data to Google Sheets
def add_data_to_sheet(data):
    print(f"Adding data to sheet: {data}")
    sheet.append_row(data)

def update_data_in_sheet(discord_username, status):
    print(f"Updating data in sheet for Discord Username {discord_username} to status {status}")
    cell = sheet.find(discord_username)
    if cell:
        sheet.update_cell(cell.row, 7, status)  # Update the Active Status column
    else:
        print(f"Discord Username {discord_username} not found in sheet.")

# Function to get Discord username
async def get_discord_username(discord_id):
    user = await bot.fetch_user(discord_id)
    return f"{user.name}#{user.discriminator}"

# Discord bot setup
intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix='$', intents=intents)

@bot.event
async def on_message(message):
    if isinstance(message.channel, discord.DMChannel):
        if message.content.lower() == '$subscribe':
            try:
                print("Creating stripe checkout session")
                # Create a new Stripe Checkout Session
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price': 'price_1PXWvCDt39UfBCOTwpKNimKZ',  # Replace with your actual price ID
                        'quantity': 1,
                    }],
                    mode='subscription',
                    success_url='https://discord.com/',  # Replace with your actual success URL
                    cancel_url='https://your-cancel-url.com/cancel',  # Replace with your actual cancel URL
                    client_reference_id=str(message.author.id),  # Include the Discord user ID
                    subscription_data={
                        'metadata': {
                            'discord_id': str(message.author.id)
                        }
                    }
                )
                # Print session data for debugging
                # print("Checkout Session Data:", json.dumps(checkout_session, indent=2))
                # Send the checkout link to the user
                await message.author.send(f'Click here to subscribe: {checkout_session.url}')
                print(f"Sent subscription link to {message.author.name}")
            except Exception as e:
                print(f"Error sending subscription link: {e}")
        elif message.content.lower() == '$cancel':
            discord_id = str(message.author.id)
            print(f"Received cancel command from {message.author.name}")
            try:
                # Find the customer's subscription
                subscriptions = stripe.Subscription.list(limit=100)
                for subscription in subscriptions.auto_paging_iter():
                    if subscription.metadata.get('discord_id') == discord_id:
                        stripe.Subscription.delete(subscription.id)
                        await message.author.send('Your subscription has been canceled.')
                        print(f"Canceled subscription for {message.author.name}")
                        # Update the Google Sheet
                        discord_username = await get_discord_username(discord_id)
                        update_data_in_sheet(discord_username, 'Cancelled')
                        break
                else:
                    await message.author.send('No active subscription found.')
                    print(f"No active subscription found for {message.author.name}")
            except Exception as e:
                await message.author.send(f'Error canceling subscription: {e}')
                print(f"Error canceling subscription for {message.author.name}: {e}")

# Define role management functions
async def add_role_to_member(guild_id, user_id, role_id):
    print(f"Attempting to add role {role_id} to user {user_id} in guild {guild_id}")
    guild = bot.get_guild(guild_id)
    role = guild.get_role(role_id)
    member = guild.get_member(user_id)
    if guild is None:
        print(f"Guild not found for ID: {guild_id}")
    if role is None:
        print(f"Role not found for ID: {role_id}")
    if member is None:
        print(f"Member not found for ID: {user_id}")
    if member and role:
        await member.add_roles(role)
        print(f"Added role {role.name} to {member.display_name}")
    else:
        print(f"Failed to add role {role_id} to {user_id}")

async def remove_role_from_member(guild_id, user_id, role_id):
    print(f"Attempting to remove role {role_id} from user {user_id} in guild {guild_id}")
    guild = bot.get_guild(guild_id)
    role = guild.get_role(role_id)
    member = guild.get_member(user_id)
    if guild is None:
        print(f"Guild not found for ID: {guild_id}")
    if role is None:
        print(f"Role not found for ID: {role_id}")
    if member is None:
        print(f"Member not found for ID: {user_id}")
    if member and role:
        await member.remove_roles(role)
        print(f"Removed role {role.name} from {member.display_name}")
    else:
        print(f"Failed to remove role {role_id} from {user_id}")

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')
    await bot.change_presence(activity=discord.Game(name="Managing Subscriptions"))

# Stripe webhook endpoint
@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    print(f"Received webhook event. Payload: {payload}")
    print(f"Signature Header: {sig_header}")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        # print(f"Webhook event constructed successfully: {json.dumps(event, indent=2)}")
    except ValueError as e:
        print(f"Webhook construct event ValueError: {e}")
        return jsonify({'error': str(e)}), 400
    except stripe.error.SignatureVerificationError as e:
        print(f"Webhook construct event SignatureVerificationError: {e}")
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        # print("Checkout Session Completed Event:", json.dumps(session, indent=2))  # Debug print

        # Retrieve the subscription to check metadata
        subscription_id = session.get('subscription')
        print(f"Subscription ID: {subscription_id}")
        if subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            # print(f"Subscription Data: {json.dumps(subscription, indent=2)}")
            discord_id = subscription['metadata'].get('discord_id', None)
            print(f"Discord ID from Subscription Metadata: {discord_id}")

            if discord_id:
                # Add role to Discord user
                guild_id = int(config('DISCORD_GUILD_ID'))
                role_id = int(config('DISCORD_PREMIUM_ROLE_ID'))
                asyncio.run_coroutine_threadsafe(add_role_to_member(guild_id, int(discord_id), role_id), bot.loop)
            else:
                print("No Discord ID found in subscription metadata.")

    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        # print("Invoice Payment Succeeded Event:", json.dumps(invoice, indent=2))  # Debug print

        customer_id = invoice['customer']
        customer = stripe.Customer.retrieve(customer_id)
        # print(f"Customer Data for Payment Succeeded: {json.dumps(customer, indent=2)}")
        customer_email = customer['email']
        amount_paid = invoice['amount_paid']

        # Retrieve the subscription to check metadata
        subscription_id = invoice.get('subscription')
        print(f"Subscription ID: {subscription_id}")
        if subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            # print(f"Subscription Data: {json.dumps(subscription, indent=2)}")
            discord_id = subscription['metadata'].get('discord_id', None)
            print(f"Discord ID from Subscription Metadata: {discord_id}")
        else:
            discord_id = None
            print("No subscription ID found in invoice.")

        print(f"Customer Email: {customer_email}, Amount Paid: {amount_paid}, Discord ID: {discord_id}")

        if discord_id:
            guild_id = int(config('DISCORD_GUILD_ID'))
            role_id = int(config('DISCORD_PREMIUM_ROLE_ID'))
            asyncio.run_coroutine_threadsafe(add_role_to_member(guild_id, int(discord_id), role_id), bot.loop)
        else:
            print("No Discord ID found in subscription metadata.")

    elif event['type'] == 'customer.subscription.created':
        subscription = event['data']['object']
        # print("Customer Subscription Created Event:", json.dumps(subscription, indent=2))  # Debug print

        customer_id = subscription['customer']
        customer = stripe.Customer.retrieve(customer_id)
        # print(f"Customer Data for Subscription Created: {json.dumps(customer, indent=2)}")
        discord_id = subscription['metadata'].get('discord_id', None)

        print(f"Customer Email: {customer['email']}, Discord ID: {discord_id}")

        if discord_id:
            guild_id = int(config('DISCORD_GUILD_ID'))
            role_id = int(config('DISCORD_PREMIUM_ROLE_ID'))
            asyncio.run_coroutine_threadsafe(add_role_to_member(guild_id, int(discord_id), role_id), bot.loop)

            customer_name = customer['name'] if 'name' in customer else 'N/A'
            next_billing_date = datetime.fromtimestamp(subscription['current_period_end']).strftime('%Y-%m-%d')

            discord_username = asyncio.run_coroutine_threadsafe(get_discord_username(int(discord_id)), bot.loop).result()

            cell = sheet.find(discord_username)
            if cell:
                sheet.update_cell(cell.row, 7, 'Active')

            else:
                add_data_to_sheet([customer_name, customer['email'], discord_username, datetime.now().strftime('%Y-%m-%d'), next_billing_date, 'Subscription', 'Active'])
        else:
            print("No Discord ID found in subscription metadata.")

    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        # print("Subscription Deleted Event:", json.dumps(subscription, indent=2))  # Debug print

        customer_id = subscription['customer']
        customer = stripe.Customer.retrieve(customer_id)
        # print(f"Customer Data for Subscription Deleted: {json.dumps(customer, indent=2)}")
        discord_id = subscription['metadata'].get('discord_id', None)

        print(f"Customer Email: {customer['email']}, Discord ID: {discord_id}")

        if discord_id:
            guild_id = int(config('DISCORD_GUILD_ID'))
            role_id = int(config('DISCORD_PREMIUM_ROLE_ID'))
            asyncio.run_coroutine_threadsafe(remove_role_from_member(guild_id, int(discord_id), role_id), bot.loop)

            discord_username = asyncio.run_coroutine_threadsafe(get_discord_username(int(discord_id)), bot.loop).result()
            update_data_in_sheet(discord_username, 'Cancelled')
        else:
            print("No Discord ID found in subscription metadata.")

    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        # print("Invoice Payment Failed Event:", json.dumps(invoice, indent=2))  # Debug print

        customer_id = invoice['customer']
        customer = stripe.Customer.retrieve(customer_id)
        # print(f"Customer Data for Payment Failed: {json.dumps(customer, indent=2)}")
        discord_id = customer['metadata'].get('discord_id', None)

        print(f"Customer Email: {customer['email']}, Discord ID: {discord_id}")

        if discord_id:
            guild_id = int(config('DISCORD_GUILD_ID'))
            role_id = int(config('DISCORD_PREMIUM_ROLE_ID'))
            asyncio.run_coroutine_threadsafe(remove_role_from_member(guild_id, int(discord_id), role_id), bot.loop)

            discord_username = asyncio.run_coroutine_threadsafe(get_discord_username(int(discord_id)), bot.loop).result()
            update_data_in_sheet(discord_username, 'Payment Failed')
        else:
            print("No Discord ID found in customer metadata.")

    return '', 200

def run_discord_bot():
    bot.run(config('DISCORD_TOKEN'))

if __name__ == '__main__':
    # Run the Discord bot in the main thread
    run_discord_bot()
