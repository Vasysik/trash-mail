import json
import asyncio
import imaplib
import email
import logging
from email.header import decode_header
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

with open('config.json', 'r') as f:
    config = json.load(f)

EMAIL = config['email']
PASSWORD = config['email_password']
IMAP_SERVER = config['imap_server']
CHECK_INTERVAL = config['check_interval']
BOT_TOKEN = config['bot_token']

mail_tasks = {}

def is_authorized(user_id):
    return str(user_id) in config['allowed_users']

def get_user_status(user_id):
    return config['allowed_users'].get(str(user_id), False)

def update_user_status(user_id, status):
    config['allowed_users'][str(user_id)] = status
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

def get_email_body(email_message):
    try:
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_payload(decode=True).decode()
                    except UnicodeDecodeError:
                        return part.get_payload(decode=True).decode('utf-8', 'ignore')
        else:
            try:
                return email_message.get_payload(decode=True).decode()
            except UnicodeDecodeError:
                return email_message.get_payload(decode=True).decode('utf-8', 'ignore')
    except Exception as e:
        logger.error(f"Error getting email body: {str(e)}")
        return "Error extracting email content"
    return "No text content found"

async def check_mail(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    while get_user_status(user_id):
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
            mail.login(EMAIL, PASSWORD)
            mail.select('inbox')
            
            _, messages = mail.search(None, 'UNSEEN')
            
            if messages[0]:
                for num in messages[0].split():
                    try:
                        _, msg = mail.fetch(num, '(RFC822)')
                        email_body = msg[0][1]
                        email_message = email.message_from_bytes(email_body)
                        
                        subject = decode_header(email_message["Subject"])[0][0]
                        if isinstance(subject, bytes):
                            subject = subject.decode('utf-8', 'ignore')
                            
                        from_ = decode_header(email_message.get("From", ""))[0][0]
                        if isinstance(from_, bytes):
                            from_ = from_.decode('utf-8', 'ignore')
                        
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
                        
                        await context.bot.send_message(chat_id=user_id, text=message)
                        logger.info(f"Sent email notification to user {user_id}")
                        
                    except Exception as e:
                        logger.error(f"Error processing email: {str(e)}")
                        continue
            
            mail.close()
            mail.logout()
            
        except Exception as e:
            logger.error(f"Error checking mail: {str(e)}")
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Error checking mail: {str(e)}"
                )
            except:
                pass
                
        await asyncio.sleep(CHECK_INTERVAL)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text('Unauthorized access')
        return
        
    if get_user_status(user_id):
        await update.message.reply_text('Monitoring is already running')
        return
        
    update_user_status(user_id, True)
    await update.message.reply_text('✅ Started email monitoring')
    
    task = asyncio.create_task(check_mail(context, user_id))
    mail_tasks[user_id] = task

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text('Unauthorized access')
        return
        
    if not get_user_status(user_id):
        await update.message.reply_text('Monitoring is not running')
        return
        
    update_user_status(user_id, False)
    
    if user_id in mail_tasks:
        mail_tasks[user_id].cancel()
        del mail_tasks[user_id]
        
    await update.message.reply_text('🛑 Stopped email monitoring')

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    
    logger.info("Bot started")
    application.run_polling()

if __name__ == '__main__':
    main()
