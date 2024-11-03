import json
import asyncio
import imaplib
import email
import logging
import re
from io import BytesIO
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

def contains_html(text):
    return bool(re.search(r'<[^>]+>', text))

def prepare_html_content(content, from_addr, subject):
    # Add HTML boilerplate if needed
    if not content.strip().lower().startswith('<!doctype') and not content.strip().lower().startswith('<html'):
        content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{subject}</title>
</head>
<body>
    {content}
</body>
</html>
"""
    return content

def get_email_body(email_message):
    try:
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == "text/html":
                    try:
                        return part.get_payload(decode=True).decode(), True
                    except UnicodeDecodeError:
                        return part.get_payload(decode=True).decode('utf-8', 'ignore'), True
                elif content_type == "text/plain":
                    try:
                        return part.get_payload(decode=True).decode(), False
                    except UnicodeDecodeError:
                        return part.get_payload(decode=True).decode('utf-8', 'ignore'), False
        else:
            content = email_message.get_payload(decode=True).decode('utf-8', 'ignore')
            return content, contains_html(content)
    except Exception as e:
        logger.error(f"Error getting email body: {str(e)}")
        return "Error extracting email content", False
    return "No content found", False

def extract_email_address(email_str):
    match = re.search(r'<(.+?)>', email_str)
    if match:
        return match.group(1)
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', email_str)
    if match:
        return match.group(0)
    return email_str

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
                        
                        content, is_html = get_email_body(email_message)
                        
                        if is_html:
                            html_content = prepare_html_content(content, from_, subject)
                            
                            from_email = extract_email_address(from_)
                            to_email = EMAIL
                            filename = f"From_{from_email}_To_{to_email}.html"
                            
                            message = (
                                f"📧 New email (HTML)\n\n"
                                f"From: {from_}\n"
                                f"Subject: {subject}\n"
                                f"\nHTML content attached below."
                            )
                            
                            await context.bot.send_message(chat_id=user_id, text=message)
                            
                            html_bytes = BytesIO(html_content.encode('utf-8'))
                            html_bytes.name = filename
                            
                            await context.bot.send_document(
                                chat_id=user_id,
                                document=html_bytes,
                                filename=filename
                            )
                            
                        else:
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
        return
        
    if not get_user_status(user_id):
        await update.message.reply_text('Monitoring is not running')
        return
        
    update_user_status(user_id, False)
    
    if user_id in mail_tasks:
        mail_tasks[user_id].cancel()
        del mail_tasks[user_id]
        
    await update.message.reply_text('🛑 Stopped email monitoring')

async def startup(application: Application):
    for user_id, status in config['allowed_users'].items():
        if status:
            try:
                user_id = int(user_id)
                task = asyncio.create_task(check_mail(application, user_id))
                mail_tasks[user_id] = task
                logger.info(f"Autostarted monitoring for user {user_id}")
                await application.bot.send_message(
                    chat_id=user_id,
                    text="✅ Bot restarted, email monitoring resumed automatically"
                )
            except Exception as e:
                logger.error(f"Error auto-starting monitoring for user {user_id}: {str(e)}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    
    application.job_queue.run_once(startup, 0)
    
    logger.info("Bot started")
    application.run_polling()

if __name__ == '__main__':
    main()
