import json
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import User
import imaplib
import email
from email.header import decode_header

with open('config.json', 'r') as f:
    config = json.load(f)

api_id = config['telegram_api_id']
api_hash = config['telegram_api_hash']
bot_token = config['bot_token']

EMAIL = config['email']
PASSWORD = config['email_password']
IMAP_SERVER = config['imap_server']
CHECK_INTERVAL = config['check_interval']

client = TelegramClient('mail_monitor_bot', api_id, api_hash).start(bot_token=bot_token)

def is_authorized(user_id):
    return str(user_id) in config['allowed_users']

def get_user_status(user_id):
    return config['allowed_users'].get(str(user_id), False)

def update_user_status(user_id, status):
    config['allowed_users'][str(user_id)] = status
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

def get_email_body(email_message):
    if email_message.is_multipart():
        for part in email_message.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode()
    else:
        return email_message.get_payload(decode=True).decode()
    return "No text content found"

async def check_mail(user_id):
    while get_user_status(user_id):
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
            mail.login(EMAIL, PASSWORD)
            mail.select('inbox')
            
            _, messages = mail.search(None, 'UNSEEN')
            
            for num in messages[0].split():
                _, msg = mail.fetch(num, '(RFC822)')
                email_body = msg[0][1]
                email_message = email.message_from_bytes(email_body)
                
                subject = decode_header(email_message["Subject"])[0][0]
                if isinstance(subject, bytes):
                    subject = subject.decode()
                    
                from_ = decode_header(email_message.get("From", ""))[0][0]
                if isinstance(from_, bytes):
                    from_ = from_.decode()
                
                content = get_email_body(email_message)
                
                if len(content) > 4000:
                    content = content[:4000] + "...\n[Message truncated due to length]"
                
                message = (
                    f"📧 New email\n\n"
                    f"From: {from_}\n"
                    f"Subject: {subject}\n"
                    f"\n--- Content ---\n\n"
                    f"{content}"
                )
                
                await client.send_message(user_id, message)
                
            mail.close()
            mail.logout()
        except Exception as e:
            await client.send_message(user_id, f"Error checking mail: {str(e)}")
            
        await asyncio.sleep(CHECK_INTERVAL)

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        return
        
    if get_user_status(user_id):
        await event.respond('Monitoring is already running')
        return
        
    update_user_status(user_id, True)
    await event.respond('Started email monitoring')
    asyncio.create_task(check_mail(user_id))

@client.on(events.NewMessage(pattern='/stop'))
async def stop_handler(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        return
        
    if not get_user_status(user_id):
        await event.respond('Monitoring is not running')
        return
        
    update_user_status(user_id, False)
    await event.respond('Stopped email monitoring')

client.run_until_disconnected()
