from dotenv import load_dotenv
import os
load_dotenv('PRIVATE_KEY.env')
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Додавання відладки
if PRIVATE_KEY is None:
    raise ValueError("Приватний ключ не знайдено! Перевірте файл PRIVATE_KEY.env і змінну PRIVATE_KEY.")
print(f"Завантажено приватний ключ: {PRIVATE_KEY}")

import asyncio
import sqlite3
from aiogram import Bot, Router, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
from collections import defaultdict
import logging
from web3 import Web3
from aiogram.exceptions import TelegramBadRequest  # Додаємо імпорт для TelegramBadRequest
import json
import time
import random
import uuid  # Для генерації унікального ID
import requests  # Додаємо імпорт requests
from web3.exceptions import TimeExhausted
import aiogram

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Логуємо версію aiogram
logger.info(f"Using aiogram version: {aiogram.__version__}")


# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен твого бота від BotFather
TOKEN = "7629732469:AAHHPd__YZeyXe2O0SYWI65uQraozFgbOEc"
bot = Bot(token=TOKEN)
router = Router()

# Налаштування Web3 для Arbitrum
w3 = Web3(Web3.HTTPProvider('https://arb-mainnet.g.alchemy.com/v2/EZdUtVEmFrn1Si6KlXobOutpyOp7dXGq'))
BOT_ADDRESS = w3.eth.account.from_key(PRIVATE_KEY).address
MAIN_WALLET_ADDRESS = "0x17905724acBC29e9D2BC95D0c0793A3381b96792"

# Контракт USDC на Arbitrum
USDC_ADDRESS = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
with open("usdc_abi.json", "r") as f:
    USDC_ABI = json.load(f)
usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=USDC_ABI)

ALLOWED_DEPOSIT_AMOUNTS = [10, 20, 50, 75, 100, 200, 500, 1000]

# Додамо після імпортів і перед обробниками
class WithdrawStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_address = State()

# Визначення станів для FSM
class DepositStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_address = State()

class WithdrawalStates(StatesGroup):
    waiting_for_address = State()
    waiting_for_amount = State()

class BigGameStates(StatesGroup):
    waiting_for_budget = State()
    waiting_for_ticket_purchase = State()
    waiting_for_confirmation = State()

class TournamentStates(StatesGroup):
    waiting_for_risk_level = State()
    waiting_for_participants = State()
    waiting_for_room_selection = State()
    waiting_for_ticket_purchase = State()
    waiting_for_confirmation = State()

class CompanyLotteryStates(StatesGroup):
    waiting_for_participants = State()
    waiting_for_winners = State()
    waiting_for_risk = State()
    waiting_for_budget = State()
    waiting_for_confirmation = State()
    viewing_history = State()
    waiting_for_username = State()  # Додаємо новий стан

class CompanyLotteryCreation(StatesGroup):
    waiting_for_participants = State()
    waiting_for_budget = State()
    waiting_for_winners = State()
    waiting_for_risk = State()
    waiting_for_confirmation = State()

def init_db():
    try:
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        print("Attempting to connect to database...")
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, deposit_address TEXT, first_visit INTEGER DEFAULT 1, last_withdrawal TEXT)''')
        print("Created/checked users table")
        c.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in c.fetchall()]
        if "preferred_crypto" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN preferred_crypto TEXT DEFAULT 'TRX'")
            print("Added preferred_crypto column to users")
        if "last_withdrawal" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN last_withdrawal TEXT")
            print("Added last_withdrawal column to users")

        # Решта ініціалізації таблиць...
        c.execute("PRAGMA table_info(deposits)")
        deposit_columns = [col[1] for col in c.fetchall()]
        if "chat_id" not in deposit_columns:
            c.execute("ALTER TABLE deposits ADD COLUMN chat_id INTEGER")
            print("Added chat_id column to deposits")
        if "received_amount" not in deposit_columns:
            c.execute("ALTER TABLE deposits ADD COLUMN received_amount REAL")
            print("Added received_amount column to deposits")
        if "is_checked" not in deposit_columns:
            c.execute("ALTER TABLE deposits ADD COLUMN is_checked INTEGER DEFAULT 0")
            print("Added is_checked column to deposits")
        c.execute('''CREATE TABLE IF NOT EXISTS deposits 
                     (deposit_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, from_address TEXT, status TEXT, timestamp TEXT, tx_hash TEXT, unique_id TEXT, chat_id INTEGER, received_amount REAL, is_checked INTEGER DEFAULT 0)''')
        print("Created/checked deposits table")

        c.execute('''CREATE TABLE IF NOT EXISTS processed_transactions 
                     (tx_hash TEXT PRIMARY KEY, user_id INTEGER, amount REAL, from_address TEXT, status TEXT, timestamp TEXT)''')
        print("Created/checked processed_transactions table")

        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals 
                     (withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, to_address TEXT, status TEXT, timestamp TEXT, tx_hash TEXT)''')
        print("Created/checked withdrawals table")

        c.execute('''CREATE TABLE IF NOT EXISTS tournaments 
                     (tournament_id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, participant_count INTEGER, risk_level TEXT, ticket_price_options TEXT, status TEXT, timestamp TEXT)''')
        print("Created/checked tournaments table")

        c.execute('''CREATE TABLE IF NOT EXISTS big_game_participants 
                     (participation_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, budget_level TEXT, ticket_price REAL, status TEXT, timestamp TEXT, tx_hash TEXT)''')
        print("Created/checked big_game_participants table")

        # Додаємо таблицю big_game_history
        c.execute('''CREATE TABLE IF NOT EXISTS big_game_history 
                     (history_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, budget_level TEXT, ticket_price REAL, status TEXT, winnings REAL, timestamp TEXT)''')
        print("Created/checked big_game_history table")

        # Перевіряємо, чи існує таблиця tournament_participants і чи має вона стару структуру
        c.execute("PRAGMA table_info(tournament_participants)")
        columns = [col[1] for col in c.fetchall()]
        if "tournament_id" not in columns:
            # Стара структура: перейменовуємо таблицю
            c.execute("ALTER TABLE tournament_participants RENAME TO tournament_participants_old")
            print("Renamed tournament_participants to tournament_participants_old")

            # Створюємо нову таблицю з правильною структурою
            c.execute('''CREATE TABLE tournament_participants 
                         (participation_id INTEGER PRIMARY KEY AUTOINCREMENT, tournament_id INTEGER, user_id INTEGER, ticket_price REAL, status TEXT, timestamp TEXT, tx_hash TEXT, FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id))''')
            print("Created new tournament_participants table with tournament_id")

            # Переносимо дані зі старої таблиці в нову
            c.execute("SELECT user_id, ticket_price, status, timestamp, tx_hash, risk_level, participant_count FROM tournament_participants_old")
            old_data = c.fetchall()
            for row in old_data:
                user_id, ticket_price, status, timestamp, tx_hash, risk_level, participant_count = row
                # Знаходимо відповідний tournament_id
                c.execute("SELECT tournament_id FROM tournaments WHERE risk_level = ? AND participant_count = ? LIMIT 1",
                          (risk_level, participant_count))
                tournament = c.fetchone()
                if tournament:
                    tournament_id = tournament[0]
                else:
                    # Якщо турнір не знайдено, створюємо новий
                    c.execute("INSERT INTO tournaments (creator_id, participant_count, risk_level, ticket_price_options, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                              (user_id, participant_count, risk_level, "3_7_15", "pending", timestamp))
                    tournament_id = c.lastrowid

                # Вставляємо дані в нову таблицю
                c.execute("INSERT INTO tournament_participants (tournament_id, user_id, ticket_price, status, timestamp, tx_hash) VALUES (?, ?, ?, ?, ?, ?)",
                          (tournament_id, user_id, ticket_price, status, timestamp, tx_hash))

            # Видаляємо стару таблицу
            c.execute("DROP TABLE tournament_participants_old")
            print("Dropped old tournament_participants table")
            conn.commit()
        else:
            print("tournament_participants table already has tournament_id column")

        c.execute('''CREATE TABLE IF NOT EXISTS tournament_history 
                     (history_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tournament_id INTEGER, ticket_price REAL, status TEXT, winnings REAL, timestamp TEXT, FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id))''')
        print("Created/checked tournament_history table")

        c.execute('''CREATE TABLE IF NOT EXISTS company_lottery 
                     (lottery_id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, participant_count INTEGER, risk_level TEXT, budget_level TEXT, status TEXT, link TEXT, timestamp TEXT, winner_count INTEGER)''')
        print("Created/checked company_lottery table")
        c.execute("PRAGMA table_info(company_lottery)")
        columns = [col[1] for col in c.fetchall()]
        if "winner_count" not in columns:
            c.execute("ALTER TABLE company_lottery ADD COLUMN winner_count INTEGER")
            print("Added winner_count column to company_lottery")
        c.execute("PRAGMA table_info(company_lottery_participants)")
        columns = [col[1] for col in c.fetchall()]
        if "budget_level" not in columns:
            c.execute("ALTER TABLE company_lottery_participants ADD COLUMN budget_level TEXT")
            print("Added budget_level column to company_lottery_participants")
        if "username" not in columns:
            c.execute("ALTER TABLE company_lottery_participants ADD COLUMN username TEXT")
            print("Added username column to company_lottery_participants")
        c.execute('''CREATE TABLE IF NOT EXISTS company_lottery_participants 
                     (participation_id INTEGER PRIMARY KEY AUTOINCREMENT, lottery_id INTEGER, user_id INTEGER, ticket_price REAL, status TEXT, timestamp TEXT, tx_hash TEXT, budget_level TEXT, username TEXT, FOREIGN KEY (lottery_id) REFERENCES company_lottery(lottery_id))''')
        print("Created/checked company_lottery_participants table")

        conn.commit()
        print("Database committed successfully.")
        print("Database initialized successfully.")
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()
        print("Database connection closed.")

# Словник для зберігання повідомлень
user_messages = defaultdict(list)
processing_messages = defaultdict(list)

# Словники для зберігання часу останніх операцій
last_deposit_time = defaultdict(lambda: 0)  # Час останнього депозиту (timestamp)
last_withdrawal_time = defaultdict(lambda: 0)  # Час останнього виведення (timestamp)

# Функції для відстеження повідомлень
async def manage_deposit_messages(user_id, chat_id, message_id):
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append({'chat_id': chat_id, 'message_id': message_id})
    logger.info(f"Added message to user_messages for user {user_id}: {{'chat_id': {chat_id}, 'message_id': {message_id}}}")

async def manage_processing_message(user_id, chat_id, message_id):
    processing_messages[user_id].append({
        'chat_id': chat_id,
        'message_id': message_id,
        'type': 'processing_message'
    })

# Словник для зберігання сповіщень про повернення коштів
refund_notifications = defaultdict(list)

# Функція для видалення сповіщень про повернення коштів
async def delete_refund_notification(user_id, chat_id, delay=5):
    await asyncio.sleep(delay)
    for message in refund_notifications[user_id]:
        try:
            await bot.delete_message(chat_id=message['chat_id'], message_id=message['message_id'])
            logger.info(f"Deleted refund notification {message['message_id']} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete refund notification {message['message_id']}: {str(e)}")
    refund_notifications[user_id].clear()

async def delete_deposit_messages(user_id, chat_id, delay=None):
    if user_id in user_messages:
        if delay is not None:
            await asyncio.sleep(delay)  # Затримка перед видаленням
        for msg in user_messages[user_id]:
            try:
                if isinstance(msg, dict) and 'chat_id' in msg and 'message_id' in msg:
                    await bot.delete_message(chat_id=msg['chat_id'], message_id=msg['message_id'])
                    logger.info(f"Deleted deposit message {msg['message_id']} for user {user_id}")
                elif isinstance(msg, int):
                    # Якщо msg є цілим числом, припускаємо, що це message_id
                    await bot.delete_message(chat_id=chat_id, message_id=msg)
                    logger.info(f"Deleted deposit message {msg} for user {user_id}")
                else:
                    logger.warning(f"Invalid message format in user_messages for user {user_id}: {msg}")
            except Exception as e:
                logger.warning(f"Failed to delete message {msg} for user {user_id}: {str(e)}")
        user_messages[user_id].clear()
        logger.info(f"Cleared user_messages for user {user_id}")

async def delete_processing_message(user_id, chat_id, delay=0):
    await asyncio.sleep(delay)
    tasks = []
    for message in processing_messages[user_id]:
        tasks.append(bot.delete_message(chat_id=message['chat_id'], message_id=message['message_id']))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            if isinstance(task, Exception):
                logger.error(f"Error deleting processing message: {task}")
    processing_messages[user_id].clear()

def get_big_game_status():
    now = datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    start_time = current_hour + timedelta(hours=now.hour - current_hour.hour)
    end_time = start_time + timedelta(minutes=45)
    if start_time <= now <= end_time:
        time_left = end_time - now
        minutes_left = time_left.seconds // 60
        seconds_left = time_left.seconds % 60
        return True, f"Час до кінця набору: {minutes_left} хв {seconds_left} сек"
    else:
        next_start = (start_time + timedelta(hours=1)).strftime("%H:%M")
        return False, f"Набір учасників завершено. Наступна гра почнеться о {next_start}."

def count_big_game_participants(budget_level):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM big_game_participants WHERE budget_level = ? AND status = 'active'", (budget_level,))
    count = c.fetchone()[0]
    conn.close()
    return count

def count_tournament_participants(tournament_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tournament_participants WHERE tournament_id = ? AND status = 'active'", (tournament_id,))
    count = c.fetchone()[0]
    logger.info(f"Counting participants: tournament_id={tournament_id}, result={count}")
    conn.close()
    return count

def count_active_tickets(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM (SELECT user_id FROM big_game_participants WHERE status = 'active' AND user_id = ? UNION "
              "SELECT user_id FROM tournament_participants WHERE status = 'active' AND user_id = ? UNION "
              "SELECT user_id FROM company_lottery_participants WHERE status = 'active' AND user_id = ?) AS active_tickets", (user_id, user_id, user_id))
    count = c.fetchone()[0]
    conn.close()
    return count

def count_active_tournament_tickets(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tournament_participants WHERE status = 'active' AND user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def count_tournament_tickets_by_params(user_id, tournament_id, ticket_price):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tournament_participants WHERE status = 'active' AND user_id = ? AND tournament_id = ? AND ticket_price = ?",
              (user_id, tournament_id, ticket_price))
    count = c.fetchone()[0]
    conn.close()
    return count

def count_active_big_game_tickets(user_id, budget_level):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM big_game_participants WHERE status = 'active' AND user_id = ? AND budget_level = ?", (user_id, budget_level))
    count = c.fetchone()[0]
    conn.close()
    return count

def has_active_withdrawal(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id = ? AND status = 'pending'", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def get_activity_dates(user_id, table, date_field="timestamp"):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    # Отримуємо всі записи з таблиці
    c.execute(f"SELECT {date_field} FROM {table} WHERE user_id = ? AND status != 'pending'", (user_id,))
    timestamps = [row[0] for row in c.fetchall()]
    logger.info(f"All timestamps from {table} for user {user_id}: {timestamps}")

    # Логуємо всі записи для перевірки
    c.execute(f"SELECT {date_field}, status FROM {table} WHERE user_id = ?", (user_id,))
    all_records = c.fetchall()
    logger.info(f"All records in {table} for user {user_id}: {all_records}")

    # Витягуємо дати вручну з timestamp
    dates = []
    for timestamp in timestamps:
        try:
            # Очікуємо формат YYYY-MM-DD HH:MM:SS
            date_part = timestamp.split(" ")[0]  # Беремо лише дату (YYYY-MM-DD)
            dates.append(date_part)
        except Exception as e:
            logger.error(f"Failed to parse timestamp {timestamp}: {str(e)}")
            continue

    # Видаляємо дублікати і сортуємо
    dates = sorted(list(set(dates)), reverse=True)
    logger.info(f"Raw dates from {table} for user {user_id}: {dates}")
    # Конвертуємо формат дати для відображення в DD.MM.YYYY
    formatted_dates = []
    for date in dates:
        try:
            formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            formatted_dates.append(formatted_date)
        except ValueError as e:
            logger.error(f"Failed to format date {date}: {str(e)}")
            continue
    conn.close()
    logger.info(f"Formatted dates for user {user_id}: {formatted_dates}")
    return formatted_dates

# Функція для отримання унікальних дат участі в лотереях компанії
def get_company_lottery_dates(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT timestamp FROM company_lottery_participants WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    dates = c.fetchall()
    conn.close()
    # Форматуємо дати у формат DD.MM.YYYY
    formatted_dates = [datetime.strptime(date[0], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y") for date in dates]
    return formatted_dates

# Функція для отримання унікальних дат покупок для "Великої гри"
def get_big_game_purchase_dates(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT SUBSTR(timestamp, 1, 10) FROM big_game_tickets WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    dates = [datetime.strptime(date[0], "%Y-%m-%d").strftime("%d.%m.%Y") for date in c.fetchall()]
    conn.close()
    return dates

# Функція для отримання унікальних дат покупок для "Турнірів"
def get_tournament_purchase_dates(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT SUBSTR(timestamp, 1, 10) FROM tournament_tickets WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    dates = [datetime.strptime(date[0], "%Y-%m-%d").strftime("%d.%m.%Y") for date in c.fetchall()]
    conn.close()
    return dates

def get_active_transactions(user_id):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    transactions = []

    def parse_timestamp(timestamp):
        try:
            # Спробуємо спочатку стандартний формат YYYY-MM-DD HH:MM:SS
            return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                # Якщо не вийшло, пробуємо формат DD.MM.YYYY HH:MM:SS
                return datetime.strptime(timestamp, "%d.%m.%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError as e:
                logger.error(f"Failed to parse timestamp: {timestamp}, error: {str(e)}")
                return timestamp  # Повертаємо як є, якщо не вдалося обробити

    # Велика гра
    c.execute("SELECT participation_id, budget_level, ticket_price, timestamp FROM big_game_participants WHERE user_id = ? AND status = 'active'", (user_id,))
    for row in c.fetchall():
        participation_id, budget_level, ticket_price, timestamp = row
        formatted_timestamp = parse_timestamp(timestamp)
        transactions.append(("big_game", participation_id, budget_level, ticket_price, formatted_timestamp))

    # Турніри
    c.execute("""
        SELECT tp.participation_id, t.risk_level, t.participant_count, tp.ticket_price, tp.timestamp 
        FROM tournament_participants tp 
        JOIN tournaments t ON tp.tournament_id = t.tournament_id 
        WHERE tp.user_id = ? AND tp.status = 'active'
    """, (user_id,))
    for row in c.fetchall():
        participation_id, risk_level, participant_count, ticket_price, timestamp = row
        formatted_timestamp = parse_timestamp(timestamp)
        level = f"{risk_level}% ({participant_count} учасників)"
        transactions.append(("tournament", participation_id, level, ticket_price, formatted_timestamp))

    # Лотереї компанії
    c.execute("SELECT clp.participation_id, cl.budget_level, clp.ticket_price, clp.timestamp FROM company_lottery_participants clp JOIN company_lottery cl ON clp.lottery_id = cl.lottery_id WHERE clp.user_id = ? AND clp.status = 'active'", (user_id,))
    for row in c.fetchall():
        participation_id, budget_level, ticket_price, timestamp = row
        formatted_timestamp = parse_timestamp(timestamp)
        transactions.append(("company_lottery", participation_id, budget_level, ticket_price, formatted_timestamp))

    conn.close()
    return transactions

def generate_lottery_link(lottery_id):
    return f"https://t.me/RapidRiches_company_bot?start={lottery_id}"

def is_valid_arbitrum_address(address: str) -> bool:
    try:
        # Перевіряємо, чи адреса є валідною (починається з 0x, 42 символи, шістнадцятковий формат)
        if not address.startswith("0x") or len(address) != 42:
            return False
        # Перевіряємо, чи це валідна адреса через web3.py
        return w3.is_address(address) and w3.is_checksum_address(address)
    except Exception as e:
        logger.error(f"Error validating address {address}: {str(e)}")
        return False
    
# Реальна обробка транзакцій
# Реальна обробка транзакцій
# Реальна обробка транзакцій
def send_transaction(from_address, to_address, amount, private_key):
    try:
        nonce = w3.eth.get_transaction_count(from_address)
        logger.info(f"Sending transaction with nonce: {nonce}, amount: {amount}, from: {from_address}, to: {to_address}")

        # Перевіряємо баланс бота для оплати газу
        bot_balance_wei = w3.eth.get_balance(from_address)
        bot_balance_eth = w3.from_wei(bot_balance_wei, 'ether')
        logger.info(f"Bot balance: {bot_balance_eth} ETH")
        if bot_balance_eth < 0.01:
            raise ValueError("Недостатньо ETH на гаманці бота для оплати газу!")

        # Схвалення контракту для витрачання USDC (approve)
        approve_tx = usdc_contract.functions.approve(
            BOT_ADDRESS,
            w3.to_wei(amount, 'mwei')
        ).build_transaction({
            'chainId': 42161,
            'gas': 200000,
            'gasPrice': w3.to_wei('0.1', 'gwei'),
            'nonce': nonce,
            'from': from_address,
        })
        signed_approve_tx = w3.eth.account.sign_transaction(approve_tx, private_key)
        tx_hash_approve = w3.eth.send_raw_transaction(signed_approve_tx.raw_transaction)
        receipt_approve = w3.eth.wait_for_transaction_receipt(tx_hash_approve, timeout=120)
        logger.info(f"Approve transaction hash: {tx_hash_approve.hex()}")

        # Переказ USDC через transfer
        transfer_tx = usdc_contract.functions.transfer(
            to_address,
            w3.to_wei(amount, 'mwei')
        ).build_transaction({
            'chainId': 42161,
            'gas': 200000,
            'gasPrice': w3.to_wei('0.1', 'gwei'),
            'nonce': nonce + 1,
            'from': from_address,
        })
        signed_transfer_tx = w3.eth.account.sign_transaction(transfer_tx, private_key)
        tx_hash_transfer = w3.eth.send_raw_transaction(signed_transfer_tx.raw_transaction)
        receipt_transfer = w3.eth.wait_for_transaction_receipt(tx_hash_transfer, timeout=120)
        tx_hash = receipt_transfer['transactionHash'].hex()
        logger.info(f"Transfer transaction hash: {tx_hash}")

        # Перевіряємо, що хеш у правильному форматі
        if len(tx_hash) != 66 or not tx_hash.startswith('0x'):
            raise ValueError(f"Invalid transaction hash format: {tx_hash}")

        # Перевіряємо, що транзакція існує в мережі Arbitrum
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is None or receipt['status'] != 1:
                logger.error(f"Transaction {tx_hash} not found or failed in Arbitrum network")
                return None
            logger.info(f"Transaction {tx_hash} confirmed in Arbitrum network")
        except Exception as e:
            logger.error(f"Failed to verify transaction {tx_hash} in Arbitrum network: {str(e)}")
            return None

        return tx_hash
    except Exception as e:
        logger.error(f"Error in send_transaction: {e}")
        return None

# Обробка депозиту з реальними коштами
# Обробка депозиту з реальними коштами
async def check_deposit_transaction(from_address, amount, deposit_timestamp, unique_id):
    logger.info(f"Checking deposit with unique_id {unique_id} from {from_address} for amount {amount}")
    deposit_time = datetime.strptime(deposit_timestamp, "%Y-%m-%d %H:%M:%S")
    time_window = 300  # 5 хвилин
    max_attempts = 3  # Максимальна кількість спроб
    attempt_delay = 30  # Затримка між спробами (секунди)

    for attempt in range(max_attempts):
        try:
            latest_block = await asyncio.get_event_loop().run_in_executor(None, lambda: w3.eth.get_block('latest')['number'])
            blocks_per_hour = 14400  # Оцінка: ~0.25 сек/блок
            search_start_time = deposit_time - timedelta(minutes=10)  # Розширюємо вікно до 10 хвилин назад
            blocks_to_subtract = int((datetime.now().timestamp() - search_start_time.timestamp()) / 0.25) * 2  # Подвоюємо для надійності
            start_block = max(0, latest_block - blocks_to_subtract)

            transfer_event = usdc_contract.events.Transfer()
            try:
                events = await asyncio.get_event_loop().run_in_executor(None, lambda: transfer_event.get_logs(
                    from_block=start_block,
                    to_block='latest',
                    argument_filters={
                        'from': w3.to_checksum_address(from_address),
                        'to': w3.to_checksum_address(MAIN_WALLET_ADDRESS)
                    }
                ))
                logger.info(f"Attempt {attempt + 1}: Found {len(events)} Transfer events for address {from_address}, start_block={start_block}, latest_block={latest_block}")
            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Failed to fetch events from Web3: {e}")
                return False, None, None

            if not events and attempt < max_attempts - 1:
                logger.warning(f"Attempt {attempt + 1}: No events found for unique_id {unique_id}, waiting {attempt_delay} seconds before retry...")
                await asyncio.sleep(attempt_delay)
                continue

            events = events[:100]  # Обмежуємо до 100 подій

            latest_event = None
            latest_time_diff = float('inf')
            for event in events:
                value = float(event['args']['value']) / 10**6
                tx_hash = event['transactionHash'].hex()
                try:
                    block = await asyncio.get_event_loop().run_in_executor(None, lambda: w3.eth.get_block(event['blockNumber']))
                    logger.debug(f"Block number: {block['number']}, Timestamp: {block['timestamp']}")
                except Exception as e:
                    logger.error(f"Failed to fetch block {event['blockNumber']} from Web3: {e}")
                    continue
                block_timestamp = float(block['timestamp'])
                tx_time = datetime.fromtimestamp(block_timestamp)
                time_diff = abs((tx_time - deposit_time).total_seconds())

                # Перевіряємо, чи транзакція від потрібного відправника і сталася після deposit_time
                if event['args']['from'] != w3.to_checksum_address(from_address) or tx_time <= deposit_time:
                    continue

                logger.debug(f"Event: value={value}, amount={amount}, tx_hash={tx_hash}, time={tx_time}, time_diff={time_diff}")

                if time_diff <= time_window and time_diff < latest_time_diff:
                    latest_time_diff = time_diff
                    latest_event = (value, tx_hash, tx_time)

            if latest_event:
                value, tx_hash, tx_time = latest_event
                if value in ALLOWED_DEPOSIT_AMOUNTS:
                    # Сума входить у список, зараховуємо її
                    logger.info(f"Found matching transaction: {tx_hash} for unique_id {unique_id} with value={value} at {tx_time}")
                    return True, tx_hash, value
                else:
                    # Сума не входить у список, повертаємо кошти
                    logger.info(f"Amount {value} not in allowed list, refunding {value} to {from_address} at {tx_time}")
                    try:
                        refund_tx_hash = send_transaction(BOT_ADDRESS, from_address, value, PRIVATE_KEY)
                        if refund_tx_hash:
                            logger.info(f"Refunded {value} USDC to {from_address}, tx_hash: {refund_tx_hash}")
                            # Оновлюємо статус депозиту одразу
                            conn = sqlite3.connect("lottery.db")
                            c = conn.cursor()
                            c.execute("UPDATE deposits SET status = 'refunded', tx_hash = ?, received_amount = ? WHERE unique_id = ?", (refund_tx_hash, value, unique_id))
                            c.execute("DELETE FROM deposits WHERE unique_id = ? AND status = 'refunded'", (unique_id,))
                            conn.commit()
                            conn.close()
                            logger.info(f"Refunded and deleted deposit with unique_id {unique_id} for amount {value}")
                            # Надсилаємо повідомлення користувачу з клікабельним посиланням на Arbiscan
                            c.execute("SELECT chat_id FROM deposits WHERE unique_id = ? LIMIT 1", (unique_id,))
                            chat_id = c.fetchone()[0]
                            if chat_id:
                                await bot.send_message(
                                    chat_id,
                                    f"❌ Сума депозиту {value} USDC не входить у дозволений список. Кошти повернуто.\n"
                                    f"Деталі транзакції: [Переглянути на Arbiscan](https://arbiscan.io/tx/{refund_tx_hash})"
                                )
                            return False, refund_tx_hash, value
                        else:
                            logger.error(f"Failed to refund {value} USDC to {from_address}: Transaction not confirmed")
                            # Надсилаємо повідомлення без хешу
                            c.execute("SELECT chat_id FROM deposits WHERE unique_id = ? LIMIT 1", (unique_id,))
                            chat_id = c.fetchone()[0]
                            if chat_id:
                                await bot.send_message(
                                    chat_id,
                                    f"❌ Сума депозиту {value} USDC не входить у дозволений список. Кошти повернуто."
                                )
                            return False, None, value
                    except Exception as e:
                        logger.error(f"Failed to refund {value} USDC to {from_address}: {e}")
                        return False, None, value
            logger.warning(f"Attempt {attempt + 1}: No matching transaction found in {len(events)} events for unique_id {unique_id}")
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}: Error checking transaction via Web3: {e}")
            return False, None, None

    logger.error(f"Deposit transaction not found for unique_id {unique_id} after {max_attempts} attempts")
    return False, None, None

def send_transaction(from_address, to_address, amount, private_key):
    nonce = w3.eth.get_transaction_count(from_address)
    approve_tx = usdc_contract.functions.approve(
        BOT_ADDRESS,
        w3.to_wei(amount, 'mwei')
    ).build_transaction({
        'chainId': 42161,
        'gas': 200000,
        'gasPrice': w3.to_wei('0.1', 'gwei'),
        'nonce': nonce,
    })
    signed_approve_tx = w3.eth.account.sign_transaction(approve_tx, private_key)
    tx_hash_approve = w3.eth.send_raw_transaction(signed_approve_tx.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash_approve, timeout=60)  # Додаємо таймаут

    transfer_tx = usdc_contract.functions.transferFrom(
        from_address,
        to_address,
        w3.to_wei(amount, 'mwei')
    ).build_transaction({
        'chainId': 42161,
        'gas': 200000,
        'gasPrice': w3.to_wei('0.1', 'gwei'),
        'nonce': nonce + 1,
    })
    signed_transfer_tx = w3.eth.account.sign_transaction(transfer_tx, private_key)
    tx_hash_transfer = w3.eth.send_raw_transaction(signed_transfer_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash_transfer, timeout=60)  # Додаємо таймаут
    return receipt['transactionHash'].hex()

def process_real_deposit(user_id, amount, from_address):
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    success, tx_hash = check_deposit_transaction(from_address, amount)
    if success:
        c.execute("INSERT INTO deposits (user_id, amount, from_address, status, timestamp, tx_hash) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, amount, from_address, "completed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tx_hash))
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    conn.close()
    return success, tx_hash

# Обробка команд і callback
@router.message(Command(commands=["start"]))
async def start_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split()
    logger.info(f"Entering start_command for user {user_id}, chat_id {chat_id}, message: {message.text}")

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    
    # Переконуємося, що таблиця users існує
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not c.fetchone():
        logger.error("Table 'users' not found, initializing database...")
        init_db()
    
    # Додаємо користувача, якщо його немає
    c.execute("INSERT OR IGNORE INTO users (user_id, first_visit) VALUES (?, ?)", (user_id, 1))
    conn.commit()

    # Перевіряємо, чи користувач існує
    c.execute("SELECT first_visit FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result is None:
        logger.error(f"User {user_id} not found after insert, re-adding...")
        c.execute("INSERT INTO users (user_id, first_visit) VALUES (?, ?)", (user_id, 1))
        conn.commit()
        first_visit = 1
    else:
        first_visit = result[0]
        logger.info(f"User {user_id} found, first_visit: {first_visit}")

    if first_visit:
        welcome_message = (
            "👋 Привіт! Ласкаво просимо до нашого лотерейного бота!\n\n"
            "Ми — платформа, де ти можеш брати участь у захоплюючих лотереях та вигравати призи в USDC (Arbitrum).\n"
            "Тут ти можеш поповнити баланс, грати в лотереї та виводити свої виграші.\n\n"
            "Для початку ознайомся з інформацією нижче та погодься з умовами!"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📜 Умови та правила", callback_data="rules")],
            [InlineKeyboardButton(text="ℹ️ Хто ми", callback_data="about")],
            [InlineKeyboardButton(text="❓ Як почати?", callback_data="how_to_start")],
            [InlineKeyboardButton(text="✅ Погодитись та продовжити", callback_data="agree_and_continue")]
        ])
        await message.answer(welcome_message, reply_markup=markup)
        c.execute("UPDATE users SET first_visit = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
    else:
        # Обробка параметра start=deposit або start=<lottery_id>
        if len(args) > 1:
            if args[1] == "deposit":
                # Логіка для депозиту
                current_time = time.time()
                last_time = last_deposit_time[user_id]
                if current_time - last_time < 120:
                    time_left = int(120 - (current_time - last_time))
                    await message.answer(
                        f"❌ Ви можете робити депозит лише раз на 2 хвилини. Зачекайте ще {time_left} секунд.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                        ])
                    )
                    conn.close()
                    return

                # Очищаємо попередні дані депозиту
                if user_id in user_messages:
                    user_messages[user_id].clear()
                if user_id in processing_messages:
                    processing_messages[user_id].clear()
                c.execute("DELETE FROM deposits WHERE user_id = ? AND status IN ('pending', 'failed', 'refunded')", (user_id,))
                conn.commit()

                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="10 USDC", callback_data="deposit_amount_10"),
                     InlineKeyboardButton(text="20 USDC", callback_data="deposit_amount_20")],
                    [InlineKeyboardButton(text="50 USDC", callback_data="deposit_amount_50"),
                     InlineKeyboardButton(text="75 USDC", callback_data="deposit_amount_75")],
                    [InlineKeyboardButton(text="100 USDC", callback_data="deposit_amount_100"),
                     InlineKeyboardButton(text="200 USDC", callback_data="deposit_amount_200")],
                    [InlineKeyboardButton(text="500 USDC", callback_data="deposit_amount_500"),
                     InlineKeyboardButton(text="1000 USDC", callback_data="deposit_amount_1000")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
                ])
                await message.answer("Оберіть суму для поповнення:", reply_markup=markup)
            else:
                # Логіка для приєднання до лотереї компанії
                try:
                    lottery_id = int(args[1])
                    c.execute("SELECT participant_count, budget_level, status FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
                    lottery = c.fetchone()
                    if lottery:
                        participant_count, budget_level, status = lottery
                        if status == "pending":
                            # Перевіряємо, чи користувач уже бере участь у цій лотереї
                            c.execute("SELECT ticket_price, username FROM company_lottery_participants WHERE lottery_id = ? AND user_id = ? AND status = 'active'",
                                      (lottery_id, user_id))
                            ticket = c.fetchone()
                            c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
                            current_participants = c.fetchone()[0]

                            if ticket:
                                # Користувач уже бере участь
                                ticket_price, username = ticket
                                message_text = (
                                    f"🏆 Лотерея для компанії\n\n"
                                    f"Ви вже берете участь у цій лотереї!\n"
                                    f"Ваш юзернейм: {username if username else 'Невідомий'}\n"
                                    f"Ваш квиток: {ticket_price} USDC\n"
                                    f"Зібрано учасників: {current_participants}/{participant_count}\n"
                                    f"Ще потрібно: {participant_count - current_participants}\n"
                                )
                                markup = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🔄 Оновити статус", callback_data=f"update_lottery_status_{lottery_id}")],
                                    [InlineKeyboardButton(text="📜 Історія", callback_data=f"company_lottery_history_{lottery_id}")],
                                    [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
                                ])
                                await message.answer(message_text, reply_markup=markup)
                            else:
                                # Користувач ще не бере участь, запитуємо юзернейм
                                if current_participants < participant_count:
                                    await state.set_state(CompanyLotteryStates.waiting_for_username)
                                    await state.update_data(lottery_id=lottery_id)
                                    await message.answer("Будь ласка, вкажіть ваш юзернейм для цієї лотереї:")
                                else:
                                    await message.answer("❌ Лотерея вже розпочата або завершена.")
                        else:
                            await message.answer("❌ Лотерея вже завершена.")
                    else:
                        await message.answer("❌ Лотерея не знайдена.")
                except ValueError:
                    await message.answer("❌ Неправильний формат посилання.")
        else:
            # Видаляємо попередні повідомлення
            if user_id in processing_messages:
                for msg in processing_messages[user_id]:
                    try:
                        await bot.delete_message(chat_id=msg['chat_id'], message_id=msg['message_id'])
                    except Exception as e:
                        logger.warning(f"Failed to delete message {msg['message_id']}: {e}")
                processing_messages[user_id].clear()

            # Показуємо головну сторінку
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
                [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
                [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
                [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
                [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
                [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
                [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
                [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
            ])
            await message.answer("Вітаємо на головній сторінці бота!", reply_markup=markup)
    conn.close()

@router.message(CompanyLotteryCreation.waiting_for_participants)
async def process_participant_count(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Entering process_participant_count for user {user_id}, chat_id {chat_id}, message: {message.text}")

    # Перевіряємо поточний стан
    current_state = await state.get_state()
    logger.info(f"Current state for user {user_id} in process_participant_count: {current_state}")

    user_data = await state.get_data()
    participants_message_id = user_data.get("participants_message_id")

    try:
        participant_count = int(message.text.strip())
        logger.info(f"User {user_id} entered participant count: {participant_count}")
        if participant_count < 5 or participant_count > 20:
            logger.info(f"Invalid participant count for user {user_id}: {participant_count}")
            # Видаляємо повідомлення користувача
            await message.delete()
            # Видаляємо попереднє повідомлення бота
            if participants_message_id:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=participants_message_id)
                    logger.info(f"Deleted previous participants message {participants_message_id} for user {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete previous participants message {participants_message_id}: {str(e)}")
            # Надсилаємо повідомлення про помилку
            error_message = await message.answer(
                "❌ Неправильно введена кількість. Спробуйте ще раз:"
            )
            # Повторно надсилаємо запит
            participants_message = await message.answer(
                "🎯 Створення гри для компанії\n\nВкажіть кількість учасників (від 5 до 20):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
                ])
            )
            await state.update_data(participants_message_id=participants_message.message_id)
            # Видаляємо повідомлення про помилку через 2 секунди
            await asyncio.sleep(2)
            await error_message.delete()
            return
    except ValueError as e:
        logger.error(f"ValueError in process_participant_count for user {user_id}: {str(e)}")
        # Видаляємо повідомлення користувача
        await message.delete()
        # Видаляємо попереднє повідомлення бота
        if participants_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=participants_message_id)
                logger.info(f"Deleted previous participants message {participants_message_id} for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to delete previous participants message {participants_message_id}: {str(e)}")
        # Надсилаємо повідомлення про помилку
        error_message = await message.answer(
            "❌ Неправильно введена кількість. Спробуйте ще раз:"
        )
        # Повторно надсилаємо запит
        participants_message = await message.answer(
            "🎯 Створення гри для компанії\n\nВкажіть кількість учасників (від 5 до 20):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await state.update_data(participants_message_id=participants_message.message_id)
        # Видаляємо повідомлення про помилку через 2 секунди
        await asyncio.sleep(2)
        await error_message.delete()
        return
    except Exception as e:
        logger.error(f"Unexpected error in process_participant_count for user {user_id}: {str(e)}")
        # Видаляємо повідомлення користувача
        await message.delete()
        # Видаляємо попереднє повідомлення бота
        if participants_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=participants_message_id)
                logger.info(f"Deleted previous participants message {participants_message_id} for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to delete previous participants message {participants_message_id}: {str(e)}")
        # Надсилаємо повідомлення про помилку
        error_message = await message.answer(
            "❌ Помилка при обробці кількості учасників. Спробуйте ще раз пізніше."
        )
        # Повторно надсилаємо запит
        participants_message = await message.answer(
            "🎯 Створення гри для компанії\n\nВкажіть кількість учасників (від 5 до 20):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await state.update_data(participants_message_id=participants_message.message_id)
        # Видаляємо повідомлення про помилку через 2 секунди
        await asyncio.sleep(2)
        await error_message.delete()
        return

    logger.info(f"Updating state with participant_count for user {user_id}")
    await state.update_data(participant_count=participant_count, participant_message_id=message.message_id)
    logger.info(f"Updated state with participant_count for user {user_id}")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5/10/20 USDC", callback_data="budget_5_10_20"),
         InlineKeyboardButton(text="10/20/40 USDC", callback_data="budget_10_20_40")],
        [InlineKeyboardButton(text="20/40/80 USDC", callback_data="budget_20_40_80"),
         InlineKeyboardButton(text="50/100/200 USDC", callback_data="budget_50_100_200")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
    ])
    logger.info(f"Sending budget selection message to user {user_id}")
    budget_message = await message.answer(
        "🎯 Оберіть бюджет для лотереї (Мін./Середній/Макс.):",
        reply_markup=markup
    )
    logger.info(f"Sent budget selection message to user {user_id}")

    logger.info(f"Setting state to CompanyLotteryCreation.waiting_for_budget for user {user_id}")
    await state.set_state(CompanyLotteryCreation.waiting_for_budget)
    current_state = await state.get_state()
    logger.info(f"State set to CompanyLotteryCreation.waiting_for_budget for user {user_id}, current state: {current_state}")

    # Видаляємо всі попередні повідомлення
    logger.info(f"Deleting previous messages for user {user_id}")
    await delete_deposit_messages(user_id, chat_id)
    if participants_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=participants_message_id)
            logger.info(f"Deleted previous participants message {participants_message_id} for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to delete previous participants message {participants_message_id}: {str(e)}")
    await message.delete()  # Видаляємо введене користувачем число
    await manage_deposit_messages(user_id, chat_id, budget_message.message_id)
    logger.info(f"Deleted previous messages for user {user_id}")

@router.callback_query(lambda c: c.data.startswith("budget_"))
async def process_budget_selection(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Entering process_budget_selection for user {user_id}, chat_id {chat_id}, callback.data: {callback.data}")

    budget = callback.data.split("_")[1:]
    budget_str = "_".join(budget)
    valid_budgets = ["5_10_20", "10_20_40", "20_40_80", "50_100_200"]
    if budget_str not in valid_budgets:
        logger.info(f"Invalid budget selection for user {user_id}: {budget_str}")
        await callback.message.edit_text(
            "❌ Будь ласка, оберіть бюджет зі списку (Мін./Середній/Макс.):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="5/10/20 USDC", callback_data="budget_5_10_20"),
                 InlineKeyboardButton(text="10/20/40 USDC", callback_data="budget_10_20_40")],
                [InlineKeyboardButton(text="20/40/80 USDC", callback_data="budget_20_40_80"),
                 InlineKeyboardButton(text="50/100/200 USDC", callback_data="budget_50_100_200")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await callback.answer()
        return

    budget_level = budget_str
    logger.info(f"User {user_id} selected budget: {budget_level}")

    logger.info(f"Updating state with budget_level for user {user_id}")
    await state.update_data(budget_level=budget_level)
    logger.info(f"Updated state with budget_level for user {user_id}")

    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    if not participant_count:
        logger.error(f"Participant count not found in state for user {user_id}")
        await callback.message.edit_text(
            "❌ Помилка: кількість учасників не вказана. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await state.clear()
        await callback.answer()
        return

    # Визначаємо діапазон переможців залежно від кількості учасників
    winner_ranges = {
        5: (2, 3),
        6: (2, 4),
        7: (2, 5),
        8: (2, 5),
        9: (2, 6),
        10: (2, 7),
        11: (3, 7),
        12: (3, 8),
        13: (3, 8),
        14: (3, 9),
        15: (3, 10),
        16: (3, 10),
        17: (3, 11),
        18: (4, 12),
        19: (4, 12),
        20: (4, 13)
    }
    min_winners, max_winners = winner_ranges[participant_count]

    # Генеруємо кнопки для вибору кількості переможців
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    buttons = []
    for i in range(min_winners, max_winners + 1):
        buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"winners_{i}"))
        if len(buttons) == 3:  # По 3 кнопки в ряд
            markup.inline_keyboard.append(buttons)
            buttons = []
    if buttons:
        markup.inline_keyboard.append(buttons)
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="play")])

    await callback.message.edit_text(
        f"🎯 Оберіть кількість переможців (від {min_winners} до {max_winners}):",
        reply_markup=markup
    )
    logger.info(f"Sent winners count prompt to user {user_id}")

    logger.info(f"Setting state to CompanyLotteryCreation.waiting_for_winners for user {user_id}")
    await state.set_state(CompanyLotteryCreation.waiting_for_winners)
    current_state = await state.get_state()
    logger.info(f"State set to CompanyLotteryCreation.waiting_for_winners for user {user_id}, current state: {current_state}")

    await callback.answer()

@router.message(CompanyLotteryCreation.waiting_for_winners)
async def process_winners_count(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Entering process_winners_count for user {user_id}, chat_id {chat_id}, message: {message.text}")

    # Перевіряємо поточний стан
    current_state = await state.get_state()
    logger.info(f"Current state for user {user_id} in process_winners_count: {current_state}")

    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    if not participant_count:
        logger.error(f"Participant count not found in state for user {user_id}")
        await message.answer(
            "❌ Помилка: кількість учасників не вказана. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await state.clear()
        return

    # Визначаємо діапазон переможців залежно від кількості учасників
    winner_ranges = {
        5: (2, 3),
        6: (2, 4),
        7: (2, 5),
        8: (2, 5),
        9: (2, 6),
        10: (2, 7),
        11: (3, 7),
        12: (3, 8),
        13: (3, 8),
        14: (3, 9),
        15: (3, 10),
        16: (3, 10),
        17: (3, 11),
        18: (4, 12),
        19: (4, 12),
        20: (4, 13)
    }
    min_winners, max_winners = winner_ranges[participant_count]

    # Генеруємо кнопки для вибору кількості переможців
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    buttons = []
    for i in range(min_winners, max_winners + 1):
        buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"winners_{i}"))
        if len(buttons) == 3:  # По 3 кнопки в ряд
            markup.inline_keyboard.append(buttons)
            buttons = []
    if buttons:
        markup.inline_keyboard.append(buttons)
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="play")])

    # Видаляємо попереднє повідомлення про вибір переможців, якщо воно є
    previous_winners_message_id = user_data.get("winners_message_id")
    if previous_winners_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=previous_winners_message_id)
            logger.info(f"Deleted previous winners message {previous_winners_message_id} for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to delete previous winners message {previous_winners_message_id}: {str(e)}")

    winners_message = await message.answer(
        f"🎯 Оберіть кількість переможців (від {min_winners} до {max_winners}):",
        reply_markup=markup
    )
    await state.update_data(winners_message_id=winners_message.message_id)

    logger.info(f"Deleting previous messages for user {user_id}")
    await delete_deposit_messages(user_id, chat_id)
    await manage_deposit_messages(user_id, chat_id, winners_message.message_id)
    logger.info(f"Deleted previous messages for user {user_id}")

@router.callback_query(lambda c: c.data.startswith("winners_"))
async def process_winners_selection(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    winners_count = int(callback.data.split("_")[1])
    logger.info(f"User {user_id} selected winners count: {winners_count}")

    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    if not participant_count:
        logger.error(f"Participant count not found in state for user {user_id}")
        await callback.message.edit_text(
            "❌ Помилка: кількість учасників не вказана. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await state.clear()
        await callback.answer()
        return

    # Перевіряємо, чи кількість переможців у допустимому діапазоні
    winner_ranges = {
        5: (2, 3),
        6: (2, 4),
        7: (2, 5),
        8: (2, 5),
        9: (2, 6),
        10: (2, 7),
        11: (3, 7),
        12: (3, 8),
        13: (3, 8),
        14: (3, 9),
        15: (3, 10),
        16: (3, 10),
        17: (3, 11),
        18: (4, 12),
        19: (4, 12),
        20: (4, 13)
    }
    min_winners, max_winners = winner_ranges[participant_count]
    if winners_count < min_winners or winners_count > max_winners:
        logger.info(f"Invalid winners count for user {user_id}: {winners_count}, allowed range: {min_winners}-{max_winners}")
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        buttons = []
        for i in range(min_winners, max_winners + 1):
            buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"winners_{i}"))
            if len(buttons) == 3:
                markup.inline_keyboard.append(buttons)
                buttons = []
        if buttons:
            markup.inline_keyboard.append(buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="play")])
        await callback.message.edit_text(
            f"❌ Кількість переможців має бути від {min_winners} до {max_winners}. Спробуйте ще раз:",
            reply_markup=markup
        )
        await callback.answer()
        return

    logger.info(f"Updating state with winners_count for user {user_id}")
    await state.update_data(winners_count=winners_count)
    logger.info(f"Updated state with winners_count for user {user_id}")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10%", callback_data="risk_10"),
         InlineKeyboardButton(text="20%", callback_data="risk_20"),
         InlineKeyboardButton(text="33%", callback_data="risk_33")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
    ])
    await callback.message.edit_text(
        "🎯 Оберіть рівень ризику (ймовірність виграшу):",
        reply_markup=markup
    )
    logger.info(f"Sent risk level selection message to user {user_id}")

    logger.info(f"Setting state to CompanyLotteryCreation.waiting_for_risk for user {user_id}")
    await state.set_state(CompanyLotteryCreation.waiting_for_risk)
    current_state = await state.get_state()
    logger.info(f"State set to CompanyLotteryCreation.waiting_for_risk for user {user_id}, current state: {current_state}")

    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("risk_"))
async def process_risk_selection(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Entering process_risk_selection for user {user_id}, chat_id {chat_id}, callback.data: {callback.data}")

    risk_level = callback.data.split("_")[1]
    valid_risk_levels = ["10", "20", "33"]
    if risk_level not in valid_risk_levels:
        logger.info(f"Invalid risk level for user {user_id}: {risk_level}")
        await callback.message.edit_text(
            "❌ Будь ласка, оберіть рівень ризику зі списку (10%, 20%, 33%):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="10%", callback_data="risk_10"),
                 InlineKeyboardButton(text="20%", callback_data="risk_20"),
                 InlineKeyboardButton(text="33%", callback_data="risk_33")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await callback.answer()
        return

    logger.info(f"Updating state with risk_level for user {user_id}")
    await state.update_data(risk_level=risk_level)
    logger.info(f"Updated state with risk_level for user {user_id}")

    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    winners_count = user_data.get("winners_count")
    budget_level = user_data.get("budget_level")

    message = (
        f"🎯 Підтвердіть створення гри для компанії:\n\n"
        f"Кількість учасників: {participant_count}\n"
        f"Кількість переможців: {winners_count}\n"
        f"Рівень ризику: {risk_level}%\n"
        f"Бюджет: {budget_level.replace('_', '/')} USDC"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data="confirm_company_lottery")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    logger.info(f"Sent confirmation prompt to user {user_id}")

    logger.info(f"Setting state to CompanyLotteryCreation.waiting_for_confirmation for user {user_id}")
    await state.set_state(CompanyLotteryCreation.waiting_for_confirmation)
    current_state = await state.get_state()
    logger.info(f"State set to CompanyLotteryCreation.waiting_for_confirmation for user {user_id}, current state: {current_state}")

    await callback.answer()

@router.callback_query(lambda c: c.data == "confirm_company_lottery")
async def confirm_company_lottery(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Entering confirm_company_lottery for user {user_id}, chat_id {chat_id}")

    # Видаляємо попередні повідомлення перед редагуванням
    await delete_deposit_messages(user_id, chat_id)
    logger.info(f"Deleted previous deposit messages for user {user_id}")

    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    winners_count = user_data.get("winners_count")
    risk_level = user_data.get("risk_level")
    budget_level = user_data.get("budget_level")

    if not all([participant_count, winners_count, risk_level, budget_level]):
        logger.error(f"Missing data in state for user {user_id}: {user_data}")
        await callback.message.edit_text(
            "❌ Помилка: не всі дані вказані. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await state.clear()
        await callback.answer()
        return

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO company_lottery (creator_id, participant_count, risk_level, budget_level, status, timestamp, winner_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, participant_count, risk_level, budget_level, "pending", timestamp, winners_count)
        )
        lottery_id = c.lastrowid
        link = generate_lottery_link(lottery_id)
        c.execute("UPDATE company_lottery SET link = ? WHERE lottery_id = ?", (link, lottery_id))
        conn.commit()
        logger.info(f"Successfully created lottery with ID {lottery_id} for user {user_id}")

        message = (
            f"🎯 Гра для компанії успішно створена!\n\n"
            f"ID: {lottery_id}\n"
            f"Кількість учасників: {participant_count}\n"
            f"Кількість переможців: {winners_count}\n"
            f"Рівень ризику: {risk_level}%\n"
            f"Бюджет: {budget_level.replace('_', '/')} USDC\n"
            f"Посилання для запрошення: {link}\n\n"
            f"Чекайте на учасників або запустіть гру завчасно командою /start_game."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ На головне меню", callback_data="back_to_main_with_lottery_message")]
        ])
        # Відображаємо повідомлення з посиланням
        try:
            await callback.message.edit_text(message, reply_markup=markup)
            logger.info(f"Successfully displayed lottery link message for user {user_id}, message_id: {callback.message.message_id}")
        except Exception as e:
            logger.error(f"Failed to edit message with lottery link for user {user_id}: {str(e)}")
            # Якщо редагування не вдалося, надсилаємо нове повідомлення
            link_message = await bot.send_message(chat_id, message, reply_markup=markup)
            logger.info(f"Sent new lottery link message for user {user_id}, message_id: {link_message.message_id}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating company lottery for user {user_id}: {str(e)}")
        try:
            await callback.message.edit_text(
                f"❌ Помилка при створенні гри: {str(e)}. Спробуйте ще раз пізніше.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
                ])
            )
        except Exception as edit_error:
            logger.error(f"Failed to edit error message for user {user_id}: {str(edit_error)}")
            await bot.send_message(
                chat_id,
                f"❌ Помилка при створенні гри: {str(e)}. Спробуйте ще раз пізніше.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
                ])
            )
    finally:
        conn.close()

    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == "rules")
async def process_rules(callback: CallbackQuery):
    rules_message = (
        "📜 **Умови та правила**\n\n"
        "1. Використовуй лише мережу Arbitrum для транзакцій.\n"
        "2. Усі операції проводяться в USDC.\n"
        "3. Ми не несемо відповідальності за помилки при введення адреси.\n"
        "4. У разі порушення правил твій акаунт може бути заблоковано.\n"
        "5. Усі виграші автоматично зараховуються на твій баланс."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")]
    ])
    await callback.message.edit_text(rules_message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "about")
async def process_about(callback: CallbackQuery):
    about_message = (
        "ℹ️ **Хто ми**\n\n"
        "Ми — команда ентузіастів, які створили цю платформу для любителів лотерей та криптовалют.\n"
        "Наша мета — зробити процес гри максимально простим, прозорим та безпечним.\n"
        "Приєднуйся до нас і вигравай круті призи!"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")]
    ])
    await callback.message.edit_text(about_message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "how_to_start")
async def process_how_to_start(callback: CallbackQuery):
    how_to_start_message = (
        "❓ **Як почати?**\n\n"
        "1. Погодься з умовами та правилами.\n"
        "2. Поповни баланс у USDC через мережу Arbitrum.\n"
        "3. Обирай лотерею, купуй квитки та чекай на результати.\n"
        "4. Виграші автоматично зараховуються на твій баланс.\n"
        "5. Використовуй кнопку 'Баланс', щоб перевірити свої кошти!"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")]
    ])
    await callback.message.edit_text(how_to_start_message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "back_to_start")
async def back_to_start(callback: CallbackQuery):
    welcome_message = (
        "👋 Привіт! Ласкаво просимо до нашого лотерейного бота!\n\n"
        "Ми — платформа, де ти можеш брати участь у захоплюючих лотереях та вигравати призи в USDC (Arbitrum).\n"
        "Тут ти можеш поповнити баланс, грати в лотереї та виводити свої виграші.\n\n"
        "Для початку ознайомся з інформацією нижче та погодься з умовами!"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Умови та правила", callback_data="rules")],
        [InlineKeyboardButton(text="ℹ️ Хто ми", callback_data="about")],
        [InlineKeyboardButton(text="❓ Як почати?", callback_data="how_to_start")],
        [InlineKeyboardButton(text="✅ Погодитись та продовжити", callback_data="agree_and_continue")]
    ])
    await callback.message.edit_text(welcome_message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "agree_and_continue")
async def agree_and_continue(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("UPDATE users SET first_visit = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
        [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
        [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
        [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
        [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
    ])
    await callback.message.edit_text("Вітаємо на головній сторінці бота!", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("back_to_main"))
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Starting back_to_main for user {user_id}, chat_id {chat_id}")

    # 1. Отримуємо message_id із callback_data, якщо є (для видалення результату)
    data_parts = callback.data.split("_")
    if len(data_parts) > 2 and data_parts[2].isdigit():
        result_message_id = int(data_parts[2])
        try:
            await bot.delete_message(chat_id=chat_id, message_id=result_message_id)
            logger.info(f"Deleted result message {result_message_id} for user {user_id}")
        except TelegramBadRequest as e:
            logger.warning(f"Failed to delete result message {result_message_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while deleting result message {result_message_id}: {str(e)}")

    # 2. Видаляємо повідомлення про помилку, якщо воно є
    user_data = await state.get_data()
    error_message_id = user_data.get("error_message_id")
    if error_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
            logger.info(f"Deleted error message {error_message_id} for user {user_id}")
        except TelegramBadRequest as e:
            logger.warning(f"Failed to delete error message {error_message_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while deleting error message {error_message_id}: {str(e)}")

    # 3. Видаляємо сповіщення про повернення коштів
    if user_id in refund_notifications:
        for message in refund_notifications[user_id]:
            try:
                await bot.delete_message(chat_id=message['chat_id'], message_id=message['message_id'])
                logger.info(f"Deleted refund notification {message['message_id']} for user {user_id}")
            except TelegramBadRequest as e:
                logger.warning(f"Failed to delete refund notification {message['message_id']}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error while deleting refund notification {message['message_id']}: {str(e)}")
        refund_notifications[user_id].clear()

    # 4. Видаляємо всі попередні повідомлення
    try:
        # Спроба видалити поточне повідомлення з таймаутом
        try:
            await asyncio.wait_for(callback.message.delete(), timeout=2.0)
            logger.info(f"Deleted current callback message for user {user_id}")
        except (TelegramBadRequest, asyncio.TimeoutError) as e:
            logger.warning(f"Failed to delete current callback message for user {user_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while deleting current callback message for user {user_id}: {str(e)}")

        # Паралельне видалення всіх попередніх повідомлень (крім результату)
        if user_id in user_messages and user_messages[user_id]:
            await delete_deposit_messages(user_id, chat_id)
            logger.info(f"Deleted all previous deposit messages for user {user_id}")
        else:
            logger.info(f"No previous deposit messages to delete for user {user_id}")
    except Exception as e:
        logger.error(f"Error during message cleanup for user {user_id}: {str(e)}")

    # 5. Відправляємо нове повідомлення з головним меню
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
        [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
        [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
        [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
        [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
    ])

    try:
        sent_message = await bot.send_message(chat_id, "Вітаємо на головній сторінці бота!", reply_markup=markup)
        logger.info(f"Sent main menu message to user {user_id}, message_id: {sent_message.message_id}")
        # Зберігаємо нове повідомлення в user_messages, якщо потрібно
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except TelegramBadRequest as e:
        logger.error(f"Failed to send main menu message to user {user_id}: {str(e)}")
        # Можна додати резервне повідомлення, якщо потрібно
    except Exception as e:
        logger.error(f"Unexpected error while sending main menu message to user {user_id}: {str(e)}")

    # 6. Очищаємо стан і завершуємо обробку
    await state.clear()
    await callback.answer()
    logger.info(f"Finished back_to_main for user {user_id}")

@router.callback_query(lambda c: c.data == "balance")
async def process_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    conn.close()
    balance_message = f"💰 **Ваш баланс:** {balance} USDC (Arbitrum)"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(balance_message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "chat")
async def process_chat(callback: CallbackQuery):
    chat_url = "https://t.me/+mUrYMi7U1twyMzQy"  # Посилання на групу
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Приєднатися до чату", url=chat_url)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(
        "💬 Приєднуйтесь до нашого чату RapidRiches Chat, щоб спілкуватися з іншими гравцями та отримувати оновлення!",
        reply_markup=markup
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "deposit")
async def process_deposit(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    # Перевірка часу останнього депозиту
    current_time = time.time()
    last_time = last_deposit_time[user_id]
    if current_time - last_time < 120:  # 2 хвилини = 120 секунд
        time_left = int(120 - (current_time - last_time))
        await callback.message.edit_text(
            f"❌ Ви можете робити депозит лише раз на 2 хвилини. Зачекайте ще {time_left} секунд.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        return

    # Очищаємо попередні дані депозиту
    if user_id in user_messages:
        user_messages[user_id].clear()
    if user_id in processing_messages:
        processing_messages[user_id].clear()
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("DELETE FROM deposits WHERE user_id = ? AND status IN ('pending', 'failed', 'refunded')", (user_id,))
    conn.commit()
    conn.close()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 USDC", callback_data="deposit_amount_10"),
         InlineKeyboardButton(text="20 USDC", callback_data="deposit_amount_20")],
        [InlineKeyboardButton(text="50 USDC", callback_data="deposit_amount_50"),
         InlineKeyboardButton(text="75 USDC", callback_data="deposit_amount_75")],
        [InlineKeyboardButton(text="100 USDC", callback_data="deposit_amount_100"),
         InlineKeyboardButton(text="200 USDC", callback_data="deposit_amount_200")],
        [InlineKeyboardButton(text="500 USDC", callback_data="deposit_amount_500"),
         InlineKeyboardButton(text="1000 USDC", callback_data="deposit_amount_1000")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("Оберіть суму для поповнення:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("deposit_amount_"))
async def deposit_amount(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    amount = float(callback.data.split("_")[-1])
    logger.info(f"User {user_id} selected deposit amount: {amount}")
    unique_id = str(uuid.uuid4())
    logger.info(f"Generated unique_id for deposit: {unique_id}")
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO deposits (user_id, amount, status, timestamp, unique_id) VALUES (?, ?, ?, ?, ?)",
                  (user_id, amount, "pending", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), unique_id))
        conn.commit()
        logger.info(f"Deposit inserted for user {user_id} with amount {amount} and unique_id {unique_id}")
    except sqlite3.Error as e:
        logger.error(f"Database error during deposit insertion: {e}")
        conn.rollback()
    finally:
        conn.close()
    request_message = await callback.message.edit_text(
        "Будь ласка, введіть адресу вашого гаманця (Arbitrum), з якого ви надсилатимете USDC:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
        ])
    )
    await manage_deposit_messages(user_id, callback.message.chat.id, request_message.message_id)
    await state.update_data(unique_id=unique_id, request_message_id=request_message.message_id)
    await state.set_state(DepositStates.waiting_for_address)
    await callback.answer()

@router.message(DepositStates.waiting_for_address)
async def process_deposit_address(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    from_address = message.text.strip()
    await manage_deposit_messages(user_id, chat_id, message.message_id)

    # Видаляємо повідомлення користувача миттєво
    try:
        await message.delete()
        logger.info(f"Deleted user message from user {user_id}: {message.text}")
    except Exception as e:
        logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

    # Отримуємо дані зі стану
    user_data = await state.get_data()
    request_message_id = user_data.get("request_message_id")
    error_message_id = user_data.get("error_message_id")

    # Видаляємо попереднє повідомлення про помилку, якщо воно є
    if error_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
            logger.info(f"Deleted previous error message {error_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete previous error message {error_message_id}: {str(e)}")

    if from_address.lower() == "назад":  # Повернення до вибору суми
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="10 USDC", callback_data="deposit_amount_10"),
             InlineKeyboardButton(text="20 USDC", callback_data="deposit_amount_20")],
            [InlineKeyboardButton(text="50 USDC", callback_data="deposit_amount_50"),
             InlineKeyboardButton(text="75 USDC", callback_data="deposit_amount_75")],
            [InlineKeyboardButton(text="100 USDC", callback_data="deposit_amount_100"),
             InlineKeyboardButton(text="200 USDC", callback_data="deposit_amount_200")],
            [InlineKeyboardButton(text="500 USDC", callback_data="deposit_amount_500"),
             InlineKeyboardButton(text="1000 USDC", callback_data="deposit_amount_1000")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
        await message.answer("Оберіть суму для поповнення:", reply_markup=markup)
        await state.clear()
        return

    if len(from_address) != 42:
        # Видаляємо попереднє повідомлення "Будь ласка, введіть адресу..."
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку (без кнопки)
        error_message = await message.answer(
            "Невірна довжина адреси! Адреса має містити рівно 42 символи (наприклад, 0x123...). Спробуйте ще раз:"
        )

        # Надсилаємо нове повідомлення "Будь ласка, введіть адресу..."
        request_message = await message.answer(
            "Будь ласка, введіть адресу вашого гаманця (Arbitrum), з якого ви надсилатимете USDC:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )

        # Оновлюємо message_id у стані
        await state.update_data(
            error_message_id=error_message.message_id,
            request_message_id=request_message.message_id
        )
        return

    if from_address.lower() == MAIN_WALLET_ADDRESS.lower():
        # Видаляємо попереднє повідомлення "Будь ласка, введіть адресу..."
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку (без кнопки)
        error_message = await message.answer(
            "❌ Не використовуйте таку ж адресу, яку використовує бот. Введіть свою дійсну адресу. Спробуйте ще раз:"
        )

        # Надсилаємо нове повідомлення "Будь ласка, введіть адресу..."
        request_message = await message.answer(
            "Будь ласка, введіть адресу вашого гаманця (Arbitrum), з якого ви надсилатимете USDC:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )

        # Оновлюємо message_id у стані
        await state.update_data(
            error_message_id=error_message.message_id,
            request_message_id=request_message.message_id
        )
        return

    # Якщо адреса коректна, видаляємо всі попередні повідомлення
    if request_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
            logger.info(f"Deleted request message {request_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
    if error_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
            logger.info(f"Deleted error message {error_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete error message {error_message_id}: {str(e)}")

    # Видаляємо всі попередні повідомлення користувача
    if user_messages[user_id]:
        for msg_id in user_messages[user_id]:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                logger.info(f"Deleted user message {msg_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete user message {msg_id}: {str(e)}")
        user_messages[user_id].clear()

    user_data = await state.get_data()
    unique_id = user_data.get("unique_id")
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deposits'")
        if not c.fetchone():
            print("Table 'deposits' not found, initializing database...")
            init_db()
        c.execute("UPDATE deposits SET from_address = ?, chat_id = ? WHERE user_id = ? AND status = 'pending' AND unique_id = ?",
                  (from_address, chat_id, user_id, unique_id))
        c.execute("SELECT amount FROM deposits WHERE user_id = ? AND status = 'pending' AND unique_id = ?", (user_id, unique_id))
        amount = c.fetchone()[0]
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error during deposit update: {e}")
        conn.rollback()
    finally:
        conn.close()

    deposit_message = await message.answer(
        f"💸 Інструкція для поповнення:\n\nМінімальна сума: 5 USDC\nСума: {amount} USDC\n\nНадішліть кошти з вашої адреси:\n{from_address}"
    )
    await manage_deposit_messages(user_id, chat_id, deposit_message.message_id)
    await asyncio.sleep(0.5)
    address_message = await message.answer(MAIN_WALLET_ADDRESS)
    await manage_deposit_messages(user_id, chat_id, address_message.message_id)
    await asyncio.sleep(0.5)
    check_message = (
        "Після відправлення натисніть 'Перевірити', щоб оновити баланс"
    )
    check_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Перевірити", callback_data="check_deposit")],
        [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
    ])
    check_sent_message = await message.answer(check_message, reply_markup=check_markup)
    await manage_deposit_messages(user_id, chat_id, check_sent_message.message_id)

    # Додаємо chat_id до processing_messages для надійності
    processing_messages[user_id].append({
        'chat_id': chat_id,
        'message_id': check_sent_message.message_id,
        'type': 'check_message'
    })
    await state.clear()

@router.callback_query(lambda c: c.data.startswith("back_to_address_"))
async def back_to_address(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    unique_id = callback.data.replace("back_to_address_", "")

    # Видаляємо всі пов’язані повідомлення
    await delete_deposit_messages(user_id, chat_id)
    await delete_processing_message(user_id, chat_id)

    # Очищаємо записи в базі даних для цього unique_id
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("DELETE FROM deposits WHERE unique_id = ? AND user_id = ?", (unique_id, user_id))
    conn.commit()
    conn.close()

    # Повертаємо до головної сторінки
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
        [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
        [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
        [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
        [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
    ])
    await callback.message.edit_text("Вітаємо на головній сторінці бота!", reply_markup=markup)
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == "check_deposit")
async def check_deposit(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"User {user_id} clicked check_deposit, chat_id: {chat_id}")

    # Видаляємо всі попередні повідомлення, пов’язані з депозитом
    await delete_deposit_messages(user_id, chat_id)
    await delete_processing_message(user_id, chat_id)

    # Перевіряємо статус депозиту
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT amount, from_address, timestamp, unique_id, status FROM deposits WHERE user_id = ? AND unique_id IN (SELECT unique_id FROM deposits WHERE status = 'pending' OR status = 'completed' OR status = 'failed') ORDER BY timestamp DESC LIMIT 1", (user_id,))
    result = c.fetchone()
    logger.info(f"Checking deposit for user {user_id}, result: {result}")
    if not result:
        await bot.send_message(chat_id, "Немає активних запитів на депозит.")
        await callback.answer()
        conn.close()
        return
    amount, from_address, deposit_timestamp, unique_id, status = result

    # Перевірка актуальності callback
    message_timestamp = callback.message.date.timestamp()
    time_threshold = (datetime.now() - timedelta(hours=1)).timestamp()
    if message_timestamp < time_threshold:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
            [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
            [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
            [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
            [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
            [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
        ])
        await bot.send_message(
            chat_id,
            "❌ Запит застарілий. Будь ласка, повторіть спробу.",
            reply_markup=markup
        )
        await callback.answer()
        conn.close()
        return

    # Якщо депозит уже оброблений
    if status == 'completed':
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = c.fetchone()[0]
        conn.close()
        success_message = await bot.send_message(
            chat_id,
            f"Депозит успішний! Перевірте ваш баланс: {new_balance} USDC",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await asyncio.sleep(10)
        await bot.delete_message(chat_id=chat_id, message_id=success_message.message_id)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
            [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
            [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
            [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
            [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
            [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
        ])
        await bot.send_message(chat_id, "Вітаємо на головній сторінці бота!", reply_markup=markup)
    elif status == 'failed':
        conn.close()
        failed_message = await bot.send_message(
            chat_id,
            "❌ Транзакція не знайдена. Переконайтеся, що ви надіслали кошти на правильну адресу, і повторіть спробу пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Повторити спробу", callback_data="deposit")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await asyncio.sleep(10)
        await bot.delete_message(chat_id=chat_id, message_id=failed_message.message_id)
    else:
        # Якщо депозит ще не оброблений
        processing_message = await bot.send_message(
            chat_id,
            "Поповнення прийнято в обробку, перевіряємо транзакцію..."
        )
        await manage_processing_message(user_id, chat_id, processing_message.message_id)

        # Перевіряємо транзакцію
        success, tx_hash, received_amount = await check_deposit_transaction(from_address, amount, deposit_timestamp, unique_id)

        if success:
            # Транзакція знайдена і сума коректна, зараховуємо кошти
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (received_amount, user_id))
            c.execute("UPDATE deposits SET status = 'completed', tx_hash = ?, received_amount = ? WHERE unique_id = ?",
                      (tx_hash, received_amount, unique_id))
            conn.commit()
            c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            new_balance = c.fetchone()[0]
            logger.info(f"Deposit completed for user {user_id}, unique_id: {unique_id}, amount: {received_amount}")

            # Видаляємо повідомлення про обробку
            await delete_processing_message(user_id, chat_id)

            success_message = await bot.send_message(
                chat_id,
                f"Депозит успішний! Перевірте ваш баланс: {new_balance} USDC\n"
                f"Деталі транзакції: [Переглянути на Arbiscan](https://arbiscan.io/tx/{tx_hash})",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                ])
            )
            await asyncio.sleep(10)
            await bot.delete_message(chat_id=chat_id, message_id=success_message.message_id)
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
                [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
                [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
                [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
                [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
                [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
                [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
                [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
            ])
            await bot.send_message(chat_id, "Вітаємо на головній сторінці бота!", reply_markup=markup)
        else:
            # Транзакція не знайдена або сума некоректна
            if received_amount and received_amount not in ALLOWED_DEPOSIT_AMOUNTS:
                # Сума некоректна, кошти вже повернуті
                c.execute("UPDATE deposits SET status = 'failed' WHERE unique_id = ?", (unique_id,))
                conn.commit()
                # Видаляємо повідомлення про обробку
                await delete_processing_message(user_id, chat_id)
                await bot.send_message(
                    chat_id,
                    f"❌ Сума депозиту {received_amount} USDC не входить у дозволений список. Кошти повернуто.\n"
                    f"Деталі транзакції: [Переглянути на Arbiscan](https://arbiscan.io/tx/{tx_hash})" if tx_hash else
                    f"❌ Сума депозиту {received_amount} USDC не входить у дозволений список. Кошти повернуто.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Повторити спробу", callback_data="deposit")],
                        [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                    ])
                )
            else:
                # Транзакція не знайдена
                c.execute("UPDATE deposits SET status = 'failed' WHERE unique_id = ?", (unique_id,))
                conn.commit()
                # Видаляємо повідомлення про обробку
                await delete_processing_message(user_id, chat_id)
                failed_message = await bot.send_message(
                    chat_id,
                    "❌ Транзакція не знайдена. Переконайтеся, що ви надіслали кошти на правильну адресу, і повторіть спробу пізніше.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Повторити спробу", callback_data="deposit")],
                        [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                    ])
                )
                await asyncio.sleep(10)
                await bot.delete_message(chat_id=chat_id, message_id=failed_message.message_id)

    await state.clear()
    await callback.answer()
    conn.close()

# Нова функція для видалення повідомлення з затримкою
async def delete_message_after_delay(chat_id, message_id, delay):
    await asyncio.sleep(delay)  # Затримка 10 секунд
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Automatically deleted processing message {message_id} after {delay} seconds")
    except Exception as e:
        logger.error(f"Failed to delete message {message_id} after delay: {e}")

@router.callback_query(lambda c: c.data == "withdraw")
async def withdraw(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Entering withdraw for user {user_id}, chat_id {chat_id}")

    # Очищаємо стан перед початком
    await state.clear()
    logger.info(f"Cleared state for user {user_id} before starting withdrawal")

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    conn.close()

    if balance < 5:
        await callback.message.edit_text(
            f"❌ Ваш баланс ({balance} USDC) замалий для виведення. Мінімальна сума — 5 USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        return

    # Надсилаємо повідомлення і зберігаємо його ID
    address_prompt = await callback.message.edit_text(
        "💸 Вкажіть адресу для виведення (мережа Arbitrum):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
        ])
    )
    await state.update_data(address_prompt_id=address_prompt.message_id)
    logger.info(f"Saved address_prompt_id {address_prompt.message_id} for user {user_id}")

    await state.set_state(WithdrawalStates.waiting_for_address)
    await callback.answer()

@router.message(WithdrawalStates.waiting_for_amount)
async def process_withdrawal_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        amount = float(message.text.strip())
    except ValueError:
        # Видаляємо повідомлення користувача миттєво
        try:
            await message.delete()
            logger.info(f"Deleted user message from user {user_id}: {message.text}")
        except Exception as e:
            logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

        # Отримуємо дані зі стану
        user_data = await state.get_data()
        request_message_id = user_data.get("request_message_id")
        amount_prompt_id = user_data.get("amount_prompt_id")
        error_message_id = user_data.get("error_message_id")

        # Видаляємо попереднє повідомлення про помилку, якщо воно є
        if error_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
                logger.info(f"Deleted previous error message {error_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete previous error message {error_message_id}: {str(e)}")

        # Видаляємо попередні повідомлення "Вкажіть суму..." і "Введіть суму:"
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
        if amount_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=amount_prompt_id)
                logger.info(f"Deleted amount prompt message {amount_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete amount prompt message {amount_prompt_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку (без кнопки)
        error_message = await message.answer(
            "❌ Введено некоректну суму. Будь ласка, введіть числове значення. Спробуйте ще раз:"
        )

        # Надсилаємо новий запит "Вкажіть суму..."
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = c.fetchone()[0]
        commission = 1.0
        conn.close()
        message_text = (
            f"💸 Вкажіть суму для виведення (USDC):\n\n"
            f"Доступний баланс: {balance} USDC\n"
            f"Комісія за виведення: {commission} USDC\n"
            f"Мінімальна сума виведення: 5 USDC"
        )
        request_message = await message.answer(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        amount_prompt = await message.answer("Введіть суму:")

        # Оновлюємо message_id у стані
        await state.update_data(
            error_message_id=error_message.message_id,
            request_message_id=request_message.message_id,
            amount_prompt_id=amount_prompt.message_id
        )
        return

    # Видаляємо повідомлення користувача миттєво
    try:
        await message.delete()
        logger.info(f"Deleted user message from user {user_id}: {message.text}")
    except Exception as e:
        logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

    # Отримуємо дані зі стану
    user_data = await state.get_data()
    to_address = user_data.get("to_address")
    request_message_id = user_data.get("request_message_id")
    amount_prompt_id = user_data.get("amount_prompt_id")
    error_message_id = user_data.get("error_message_id")

    # Перевіряємо, чи є адреса в стані
    if not to_address:
        logger.error(f"Withdrawal address not found in state for user {user_id}, current state: {user_data}")
        # Видаляємо попередні повідомлення "Вкажіть суму..." і "Введіть суму:"
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
        if amount_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=amount_prompt_id)
                logger.info(f"Deleted amount prompt message {amount_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete amount prompt message {amount_prompt_id}: {str(e)}")

        result_message = await bot.send_message(
            chat_id,
            "❌ Виникла помилка: адреса для виведення не була збережена. Спробуйте ще раз з початку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="withdraw")]
            ])
        )
        await asyncio.sleep(2)  # Чекаємо 2 секунди перед показом головного меню
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
            [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
            [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
            [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
            [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
            [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
        ])
        await bot.send_message(chat_id, "Вітаємо на головній сторінці бота!", reply_markup=markup)
        await asyncio.sleep(5)  # Чекаємо ще 5 секунд (загалом 7 секунд), щоб видалити повідомлення
        await bot.delete_message(chat_id=chat_id, message_id=result_message.message_id)
        await state.clear()
        return

    # Видаляємо попереднє повідомлення про помилку, якщо воно є
    if error_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
            logger.info(f"Deleted previous error message {error_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete previous error message {error_message_id}: {str(e)}")

    commission = 1.0
    total_amount = amount + commission

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]

    if amount < 5:
        # Видаляємо попередні повідомлення "Вкажіть суму..." і "Введіть суму:"
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
        if amount_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=amount_prompt_id)
                logger.info(f"Deleted amount prompt message {amount_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete amount prompt message {amount_prompt_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку (без кнопки)
        error_message = await message.answer(
            f"❌ Мінімальна сума виведення - 5 USDC. Ви ввели {amount} USDC. Спробуйте ще раз:"
        )

        # Надсилаємо новий запит "Вкажіть суму..."
        message_text = (
            f"💸 Вкажіть суму для виведення (USDC):\n\n"
            f"Доступний баланс: {balance} USDC\n"
            f"Комісія за виведення: {commission} USDC\n"
            f"Мінімальна сума виведення: 5 USDC"
        )
        request_message = await message.answer(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        amount_prompt = await message.answer("Введіть суму:")

        # Оновлюємо message_id у стані
        await state.update_data(
            error_message_id=error_message.message_id,
            request_message_id=request_message.message_id,
            amount_prompt_id=amount_prompt.message_id
        )
        conn.close()
        return

    if total_amount > balance:
        # Видаляємо попередні повідомлення "Вкажіть суму..." і "Введіть суму:"
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
        if amount_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=amount_prompt_id)
                logger.info(f"Deleted amount prompt message {amount_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete amount prompt message {amount_prompt_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку (без кнопки)
        result_message = await message.answer(
            f"❌ Недостатньо коштів на балансі. Доступно: {balance} USDC, потрібно: {total_amount} USDC (включаючи комісію {commission} USDC). Спробуйте ще раз:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await asyncio.sleep(2)  # Чекаємо 2 секунди перед показом головного меню
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
            [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
            [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
            [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
            [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
            [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
        ])
        await bot.send_message(chat_id, "Вітаємо на головній сторінці бота!", reply_markup=markup)
        await asyncio.sleep(5)  # Чекаємо ще 5 секунд (загалом 7 секунд), щоб видалити повідомлення
        await bot.delete_message(chat_id=chat_id, message_id=result_message.message_id)
        await state.clear()
        conn.close()
        return

    if has_active_withdrawal(user_id):
        # Видаляємо попередні повідомлення "Вкажіть суму..." і "Введіть суму:"
        if request_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
                logger.info(f"Deleted request message {request_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
        if amount_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=amount_prompt_id)
                logger.info(f"Deleted amount prompt message {amount_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete amount prompt message {amount_prompt_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку (без кнопки)
        result_message = await message.answer(
            "❌ Наразі у вас є активний запит на виведення. Зачекайте, поки транзакція завершиться. Спробуйте ще раз:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await asyncio.sleep(2)  # Чекаємо 2 секунди перед показом головного меню
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
            [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
            [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
            [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
            [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
            [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
        ])
        await bot.send_message(chat_id, "Вітаємо на головній сторінці бота!", reply_markup=markup)
        await asyncio.sleep(5)  # Чекаємо ще 5 секунд (загалом 7 секунд), щоб видалити повідомлення
        await bot.delete_message(chat_id=chat_id, message_id=result_message.message_id)
        await state.clear()
        conn.close()
        return

    # Якщо сума коректна, видаляємо всі попередні повідомлення
    if request_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=request_message_id)
            logger.info(f"Deleted request message {request_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete request message {request_message_id}: {str(e)}")
    if amount_prompt_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=amount_prompt_id)
            logger.info(f"Deleted amount prompt message {amount_prompt_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete amount prompt message {amount_prompt_id}: {str(e)}")
    if error_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
            logger.info(f"Deleted error message {error_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete error message {error_message_id}: {str(e)}")

    # Видаляємо всі попередні повідомлення користувача
    if user_messages[user_id]:
        for msg_id in user_messages[user_id]:
            try:
                await bot.delete_message(chat_id=msg_id['chat_id'], message_id=msg_id['message_id'])
                logger.info(f"Deleted user message {msg_id['message_id']} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete user message {msg_id['message_id']}: {str(e)}")
        user_messages[user_id].clear()

    # Зберігаємо суму в стані
    await state.update_data(withdrawal_amount=amount)
    logger.info(f"Saved withdrawal_amount {amount} for user {user_id} in state")

    # Показуємо підтвердження
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data="confirm_withdrawal")],
        [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
    ])
    confirmation_message = await message.answer(
        f"Ви обрали суму {amount} USDC.\nКомісія: {commission} USDC\nАдреса: {to_address}\n\nПідтвердити транзакцію?",
        reply_markup=markup
    )
    await state.update_data(confirmation_message_id=confirmation_message.message_id)
    conn.close()

# ... (кінець process_withdrawal_amount)

@router.message(WithdrawalStates.waiting_for_address)
async def process_withdrawal(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    to_address = message.text.strip()
    logger.info(f"User {user_id} entered withdrawal address: {to_address}")

    # Отримуємо дані зі стану
    user_data = await state.get_data()
    address_prompt_id = user_data.get("address_prompt_id")
    error_message_id = user_data.get("error_message_id")

    # Перевіряємо, чи адреса валідна
    if not is_valid_arbitrum_address(to_address):
        # Видаляємо повідомлення користувача
        try:
            await message.delete()
            logger.info(f"Deleted user message from user {user_id}: {message.text}")
        except Exception as e:
            logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

        # Видаляємо попереднє повідомлення про помилку, якщо воно є
        if error_message_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
                logger.info(f"Deleted previous error message {error_message_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete previous error message {error_message_id}: {str(e)}")

        # Видаляємо попереднє повідомлення "Вкажіть адресу..."
        if address_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=address_prompt_id)
                logger.info(f"Deleted address prompt message {address_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete address prompt message {address_prompt_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку
        error_message = await message.answer(
            "❌ Вказана адреса не є валідною адресою в мережі Arbitrum. Спробуйте ще раз:"
        )

        # Надсилаємо новий запит "Вкажіть адресу..."
        address_prompt = await message.answer(
            "💸 Вкажіть адресу для виведення (мережа Arbitrum):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )

        # Оновлюємо message_id у стані
        await state.update_data(
            error_message_id=error_message.message_id,
            address_prompt_id=address_prompt.message_id
        )
        return

    # Перевіряємо, чи є сума в стані
    amount = user_data.get("withdrawal_amount")
    if not amount:
        logger.error(f"Withdrawal amount not found in state for user {user_id}, current state: {user_data}")
        # Зберігаємо введену адресу, щоб не втрачати її
        await state.update_data(to_address=to_address)
        logger.info(f"Saved to_address {to_address} for user {user_id} in state despite missing amount")

        # Видаляємо повідомлення користувача
        try:
            await message.delete()
            logger.info(f"Deleted user message from user {user_id}: {message.text}")
        except Exception as e:
            logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

        # Видаляємо попереднє повідомлення "Вкажіть адресу..."
        if address_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=address_prompt_id)
                logger.info(f"Deleted address prompt message {address_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete address prompt message {address_prompt_id}: {str(e)}")

        # Надсилаємо повідомлення про помилку
        error_message = await message.answer(
            "Адреса перевірена"
        )

        # Надсилаємо новий запит "Вкажіть суму..."
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = c.fetchone()[0]
        commission = 1.0
        conn.close()
        message_text = (
            f"💸 Вкажіть суму для виведення (USDC):\n\n"
            f"Доступний баланс: {balance} USDC\n"
            f"Комісія за виведення: {commission} USDC\n"
            f"Мінімальна сума виведення: 5 USDC"
        )
        request_message = await message.answer(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        amount_prompt = await message.answer("Введіть суму:")

        # Оновлюємо message_id у стані
        await state.update_data(
            error_message_id=error_message.message_id,
            request_message_id=request_message.message_id,
            amount_prompt_id=amount_prompt.message_id
        )
        await state.set_state(WithdrawalStates.waiting_for_amount)
        return

    # Перевіряємо баланс
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    commission = 1.0
    total_amount = amount + commission
    if total_amount > balance:
        # Видаляємо повідомлення користувача
        try:
            await message.delete()
            logger.info(f"Deleted user message from user {user_id}: {message.text}")
        except Exception as e:
            logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

        # Видаляємо попереднє повідомлення "Вкажіть адресу..."
        if address_prompt_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=address_prompt_id)
                logger.info(f"Deleted address prompt message {address_prompt_id} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete address prompt message {address_prompt_id}: {str(e)}")

        await message.answer(
            f"❌ Недостатньо коштів на балансі. Доступно: {balance} USDC, потрібно: {total_amount} USDC (включаючи комісію {commission} USDC). Спробуйте ще раз:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="withdraw")]
            ])
        )
        await state.clear()
        conn.close()
        return

    # Якщо все ок, видаляємо попередні повідомлення
    if address_prompt_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=address_prompt_id)
            logger.info(f"Deleted address prompt message {address_prompt_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete address prompt message {address_prompt_id}: {str(e)}")
    if error_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=error_message_id)
            logger.info(f"Deleted error message {error_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete error message {error_message_id}: {str(e)}")

    # Видаляємо всі попередні повідомлення користувача
    if user_messages[user_id]:
        for msg_id in user_messages[user_id]:
            try:
                await bot.delete_message(chat_id=msg_id['chat_id'], message_id=msg_id['message_id'])
                logger.info(f"Deleted user message {msg_id['message_id']} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete user message {msg_id['message_id']}: {str(e)}")
        user_messages[user_id].clear()

    # Зберігаємо адресу в стані
    await state.update_data(to_address=to_address)
    logger.info(f"Saved to_address {to_address} for user {user_id} in state")

    # Показуємо підтвердження
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data="confirm_withdrawal")],
        [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
    ])
    confirmation_message = await message.answer(
        f"Ви обрали суму {amount} USDC.\nКомісія: {commission} USDC\nАдреса: {to_address}\n\nПідтвердити транзакцію?",
        reply_markup=markup
    )
    await state.update_data(confirmation_message_id=confirmation_message.message_id)
    conn.close()

@router.message()
async def handle_unexpected_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_state = await state.get_state()
    logger.info(f"Received message from user {user_id} in state {current_state}: {message.text}")

    # Список станів, у яких бот очікує введення з клавіатури
    expected_input_states = [
        DepositStates.waiting_for_address.state,
        WithdrawStates.waiting_for_address.state,
        WithdrawStates.waiting_for_amount.state,
        CompanyLotteryStates.waiting_for_participants.state,
    ]

    # Якщо бот не очікує введення (немає відповідного стану)
    if current_state not in expected_input_states:
        logger.info(f"Ignoring unexpected input from user {user_id}: {message.text}")
        # Чекаємо 2 секунди і видаляємо повідомлення
        await asyncio.sleep(2)
        try:
            await message.delete()
            logger.info(f"Deleted unexpected message from user {user_id}: {message.text}")
        except Exception as e:
            logger.error(f"Failed to delete unexpected message from user {user_id}: {str(e)}")

@router.message(WithdrawalStates.waiting_for_address)
async def process_withdrawal_address(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    to_address = message.text.strip()
    logger.info(f"User {user_id} entered withdrawal address: {to_address}")
    logger.info("Using updated process_withdrawal_address v4 - 2025-03-27")  # Унікальний лог для перевірки версії

    # Отримуємо дані зі стану
    user_data = await state.get_data()
    address_prompt_id = user_data.get("address_prompt_id")
    error_message_id = user_data.get("error_message_id")
    previous_messages = user_data.get("previous_messages", [])  # Список для зберігання всіх попередніх повідомлень

    # Логуємо початковий стан previous_messages
    logger.info(f"Initial previous_messages for user {user_id}: {previous_messages}")

    # Видаляємо повідомлення користувача
    try:
        await message.delete()
        logger.info(f"Deleted user message from user {user_id}: {message.text}")
    except Exception as e:
        logger.error(f"Failed to delete user message from user {user_id}: {str(e)}")

    # Додаємо поточні повідомлення до списку previous_messages
    if address_prompt_id:
        if isinstance(address_prompt_id, int) and address_prompt_id > 0:
            previous_messages.append({"chat_id": chat_id, "message_id": address_prompt_id})
            logger.info(f"Added address_prompt_id {address_prompt_id} to previous_messages for user {user_id}")
        else:
            logger.warning(f"Invalid address_prompt_id {address_prompt_id} for user {user_id}, skipping")
    if error_message_id:
        if isinstance(error_message_id, int) and error_message_id > 0:
            previous_messages.append({"chat_id": chat_id, "message_id": error_message_id})
            logger.info(f"Added error_message_id {error_message_id} to previous_messages for user {user_id}")
        else:
            logger.warning(f"Invalid error_message_id {error_message_id} for user {user_id}, skipping")

    # Перевіряємо, чи адреса валідна
    if not is_valid_arbitrum_address(to_address):
        # Надсилаємо повідомлення про помилку
        error_message = await message.answer(
            "❌ Вказана адреса не є валідною адресою в мережі Arbitrum. Спробуйте ще раз:"
        )

        # Перевіряємо, чи отримали валідний message_id
        if not error_message.message_id or not isinstance(error_message.message_id, int):
            logger.error(f"Invalid error_message.message_id for user {user_id}: {error_message.message_id}")
            return

        # Надсилаємо новий запит "Вкажіть адресу..."
        address_prompt = await message.answer(
            "💸 Вкажіть адресу для виведення (мережа Arbitrum):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )

        # Перевіряємо, чи отримали валідний message_id
        if not address_prompt.message_id or not isinstance(address_prompt.message_id, int):
            logger.error(f"Invalid address_prompt.message_id for user {user_id}: {address_prompt.message_id}")
            return

        # Додаємо нові повідомлення до списку previous_messages
        previous_messages.append({"chat_id": chat_id, "message_id": error_message.message_id})
        previous_messages.append({"chat_id": chat_id, "message_id": address_prompt.message_id})

        # Логуємо оновлений список
        logger.info(f"Updated previous_messages after invalid address for user {user_id}: {previous_messages}")

        # Оновлюємо стан
        await state.update_data(
            error_message_id=error_message.message_id,
            address_prompt_id=address_prompt.message_id,
            previous_messages=previous_messages
        )
        logger.info(f"Saved new address_prompt_id {address_prompt.message_id} for user {user_id} after invalid address")
        return

    # Якщо адреса валідна, видаляємо всі попередні повідомлення зі списку previous_messages
    logger.info(f"Deleting all previous messages for user {user_id}: {previous_messages}")
    for msg in previous_messages:
        if not isinstance(msg, dict) or "chat_id" not in msg or "message_id" not in msg:
            logger.warning(f"Invalid message format in previous_messages for user {user_id}: {msg}")
            continue
        if not isinstance(msg["message_id"], int) or msg["message_id"] <= 0:
            logger.warning(f"Invalid message_id in previous_messages for user {user_id}: {msg['message_id']}")
            continue
        try:
            await bot.delete_message(chat_id=msg["chat_id"], message_id=msg["message_id"])
            logger.info(f"Deleted previous message {msg['message_id']} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete previous message {msg['message_id']}: {str(e)}")

    # Очищаємо список previous_messages
    previous_messages.clear()

    # Видаляємо всі попередні повідомлення користувача
    if user_id in user_messages and user_messages[user_id]:
        for msg_id in user_messages[user_id]:
            try:
                await bot.delete_message(chat_id=msg_id['chat_id'], message_id=msg_id['message_id'])
                logger.info(f"Deleted user message {msg_id['message_id']} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete user message {msg_id['message_id']}: {str(e)}")
        user_messages[user_id].clear()

    # Зберігаємо адресу в стані
    await state.update_data(to_address=to_address, previous_messages=previous_messages)
    logger.info(f"Saved to_address {to_address} for user {user_id} in state")

    # Перевіряємо, чи є сума в стані (залишаємо перевірку, щоб повідомлення з’явилося)
    amount = user_data.get("withdrawal_amount")
    if not amount:
        logger.info(f"Withdrawal amount not found for user {user_id}, showing temporary message")
        # Надсилаємо повідомлення, яке зникне через 2 секунди
        temp_error_message = await message.answer(
            "❌ Виникла помилка: сума для виведення не була збережена. Будь ласка, вкажіть суму ще раз:"
        )
        # Чекаємо 2 секунди
        await asyncio.sleep(2)
        # Видаляємо повідомлення
        try:
            await bot.delete_message(chat_id=chat_id, message_id=temp_error_message.message_id)
            logger.info(f"Deleted temporary error message {temp_error_message.message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete temporary error message {temp_error_message.message_id}: {str(e)}")

    # Запитуємо суму
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    commission = 1.0
    conn.close()
    message_text = (
        f"💸 Вкажіть суму для виведення (USDC):\n\n"
        f"Доступний баланс: {balance} USDC\n"
        f"Комісія за виведення: {commission} USDC\n"
        f"Мінімальна сума виведення: 5 USDC"
    )
    request_message = await message.answer(
        message_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
        ])
    )
    amount_prompt = await message.answer("Введіть суму:")

    # Оновлюємо message_id у стані
    await state.update_data(
        request_message_id=request_message.message_id,
        amount_prompt_id=amount_prompt.message_id
    )
    await state.set_state(WithdrawalStates.waiting_for_amount)
    logger.info(f"Set state to WithdrawalStates.waiting_for_amount for user {user_id}")

@router.callback_query(lambda c: c.data == "confirm_withdrawal")
async def confirm_withdrawal(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"User {user_id} confirmed withdrawal, chat_id: {chat_id}")

    # Отримуємо дані зі стану
    user_data = await state.get_data()
    amount = user_data.get("withdrawal_amount")
    to_address = user_data.get("to_address")
    confirmation_message_id = user_data.get("confirmation_message_id")

    # Перевіряємо, чи є всі необхідні дані
    if not amount or not to_address:
        logger.error(f"Missing data for withdrawal confirmation for user {user_id}, amount: {amount}, to_address: {to_address}")
        # Видаляємо повідомлення підтвердження
        try:
            await callback.message.delete()
            logger.info(f"Deleted confirmation message {confirmation_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete confirmation message {confirmation_message_id}: {str(e)}")

        await callback.message.answer(
            "❌ Виникла помилка: дані для виведення не були збережені. Спробуйте ще раз з початку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="withdraw")]
            ])
        )
        await state.clear()
        await callback.answer()
        return

    # Перевіряємо баланс
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    commission = 1.0
    total_amount = amount + commission
    if total_amount > balance:
        # Видаляємо повідомлення підтвердження
        try:
            await callback.message.delete()
            logger.info(f"Deleted confirmation message {confirmation_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete confirmation message {confirmation_message_id}: {str(e)}")

        await callback.message.answer(
            f"❌ Недостатньо коштів на балансі. Доступно: {balance} USDC, потрібно: {total_amount} USDC (включаючи комісію {commission} USDC). Спробуйте ще раз:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="withdraw")]
            ])
        )
        await state.clear()
        conn.close()
        await callback.answer()
        return

    try:
        # Списуємо суму з балансу
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (total_amount, user_id))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tx_hash = send_transaction(BOT_ADDRESS, to_address, amount, PRIVATE_KEY)
        if tx_hash:
            c.execute("INSERT INTO withdrawals (user_id, amount, to_address, status, timestamp, tx_hash) VALUES (?, ?, ?, ?, ?, ?)",
                      (user_id, amount, to_address, "completed", timestamp, tx_hash))
            conn.commit()
            message_text = (
                f"✅ Виведення на суму {amount} USDC успішно виконано!\n"
                f"Адреса: {to_address}\n"
                f"Деталі транзакції: [Переглянути на Arbiscan](https://arbiscan.io/tx/{tx_hash})"
            )
            logger.info(f"Withdrawal successful for user {user_id}, tx_hash: {tx_hash}")
        else:
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total_amount, user_id))
            c.execute("INSERT INTO withdrawals (user_id, amount, to_address, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                      (user_id, amount, to_address, "failed", timestamp))
            conn.commit()
            message_text = (
                f"❌ Помилка при виведенні на суму {amount} USDC.\n"
                f"Кошти повернуто на баланс."
            )
            logger.error(f"Withdrawal failed for user {user_id}: Transaction not confirmed")

        # Видаляємо повідомлення підтвердження
        try:
            await callback.message.delete()
            logger.info(f"Deleted confirmation message {confirmation_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete confirmation message {confirmation_message_id}: {str(e)}")

        await callback.message.answer(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
    except Exception as e:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total_amount, user_id))
        c.execute("INSERT INTO withdrawals (user_id, amount, to_address, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (user_id, amount, to_address, "failed", timestamp))
        conn.commit()
        # Видаляємо повідомлення підтвердження
        try:
            await callback.message.delete()
            logger.info(f"Deleted confirmation message {confirmation_message_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete confirmation message {confirmation_message_id}: {str(e)}")

        await callback.message.answer(
            f"❌ Помилка при виведенні: {str(e)}. Кошти повернуто на баланс.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        logger.error(f"Withdrawal failed for user {user_id}: {str(e)}")
    finally:
        conn.close()
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == "history")
async def history(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Processing history for user {user_id}")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Історія покупок", callback_data="history_purchases")],
        [InlineKeyboardButton(text="📜 Історія поповнень", callback_data="history_deposits")],
        [InlineKeyboardButton(text="📜 Історія виведень", callback_data="history_withdrawals")],
        [InlineKeyboardButton(text="📜 Історія лотерей компанії", callback_data="history_company_lottery_dates_from_history")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

    # Видаляємо поточне повідомлення
    try:
        await callback.message.delete()
        logger.info(f"Deleted current message {callback.message.message_id} for user {user_id}")
    except TelegramBadRequest as e:
        logger.warning(f"Failed to delete current message {callback.message.message_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while deleting current message {callback.message.message_id}: {str(e)}")

    # Відправляємо нове повідомлення
    try:
        sent_message = await bot.send_message(chat_id, "📜 Історія\n\nОберіть тип історії:", reply_markup=markup)
        logger.info(f"Sent new message with id {sent_message.message_id} for user {user_id}")
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except TelegramBadRequest as e:
        logger.error(f"Failed to send new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except Exception as e:
        logger.error(f"Unexpected error while sending new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

    await callback.answer()

@router.callback_query(lambda c: c.data == "history_deposits" or c.data.startswith("history_deposits_date_"))
async def history_deposits(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"Entering history_deposits with callback.data: {data}")
    if data == "history_deposits":
        # Показуємо список дат із пагінацією
        deposit_dates = get_activity_dates(user_id, "deposits")
        logger.info(f"Deposit dates for user {user_id}: {deposit_dates}")
        if not deposit_dates:
            message = "📜 Історія поповнень\n\nЗаписів не знайдено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            await callback.answer()
            return

        # Пагінація: максимум 8 дат на сторінці
        dates_per_page = 8
        total_dates = len(deposit_dates)
        total_pages = (total_dates + dates_per_page - 1) // dates_per_page
        page = 1  # Початкова сторінка

        start_idx = (page - 1) * dates_per_page
        end_idx = start_idx + dates_per_page
        page_dates = deposit_dates[start_idx:end_idx]

        message = f"📜 Історія поповнень (Сторінка {page}/{total_pages})\n\nОберіть дату:"
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for date in page_dates:
            date_callback = date.replace(".", "_")
            markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"history_deposits_date_{date_callback}_{page}")])

        # Додаємо кнопки пагінації
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_deposits_page_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_deposits_page_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
    else:
        # Показуємо записи за обрану дату
        parts = data.split("_")
        logger.info(f"Parts after splitting callback.data: {parts}")
        if len(parts) < 7:  # Змінюємо перевірку на 7, оскільки очікуємо 7 частин
            logger.error(f"Invalid callback.data format: {data}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_deposits")]
                ])
            )
            await callback.answer()
            return
        else:
            date = f"{parts[3]}.{parts[4]}.{parts[5]}"  # Конвертуємо назад у DD.MM.YYYY
            page = int(parts[6])  # Сторінка

        try:
            # Перевіряємо, чи date має правильний формат DD.MM.YYYY
            datetime.strptime(date, "%d.%m.%Y")
        except ValueError as e:
            logger.error(f"Invalid date format: {date}, error: {str(e)}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат дати. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_deposits")]
                ])
            )
            await callback.answer()
            return

        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
        c.execute("SELECT deposit_id, amount, from_address, status, timestamp, tx_hash, received_amount FROM deposits WHERE user_id = ? AND SUBSTR(timestamp, 1, 10) = ? AND status != 'pending' ORDER BY timestamp DESC",
                  (user_id, date_sql))
        deposits = c.fetchall()
        logger.info(f"Deposits for user {user_id} on date {date}: {deposits}")

        records_per_page = 5
        total_records = len(deposits)
        total_pages = (total_records + records_per_page - 1) // records_per_page
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * records_per_page
        end_idx = start_idx + records_per_page
        page_deposits = deposits[start_idx:end_idx]

        if not deposits:
            message = f"📜 Історія поповнень за {date}\n\nЗаписів не знайдено."
        else:
            message = f"📜 Історія поповнень за {date} (Сторінка {page}/{total_pages})\n\n"
            for deposit in page_deposits:
                deposit_id, amount, from_address, status, timestamp, tx_hash, received_amount = deposit
                formatted_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
                message += (
                    f"ID: {deposit_id} | Сума: {amount} USDC | Отримано: {received_amount if received_amount is not None else amount} USDC | "
                    f"Адреса: {from_address[:6]}...{from_address[-4:]} | Статус: {status} | Дата: {formatted_timestamp} | "
                    f"Tx: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash[:6]}...</a>\n"
                )

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        date_callback = date.replace(".", "_")
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_deposits_date_{date_callback}_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_deposits_date_{date_callback}_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history_deposits")])

        await callback.message.edit_text(message, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
        await callback.answer()
        conn.close()

@router.callback_query(lambda c: c.data.startswith("deposit_date_"))
async def view_deposit_history_by_date(callback: CallbackQuery):
    user_id = callback.from_user.id
    date = callback.data.replace("deposit_date_", "")
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT amount, from_address, status, timestamp, tx_hash FROM deposits WHERE user_id = ? AND DATE(timestamp) = ? AND status != 'pending'", (user_id, date))
    deposits = c.fetchall()
    conn.close()
    logger.info(f"Fetching deposit history for user {user_id}, date {date}, deposits: {deposits}")
    if not deposits:
        message = f"📥 За {date} немає записів про поповнення."
    else:
        message = f"📥 <b>Історія поповнень за {date}:</b>\n\n"
        for deposit in deposits:
            amount, from_address, status, timestamp, tx_hash = deposit
            arbiscan_url = f"https://arbiscan.io/tx/{tx_hash}"
            message += f"Сума: {amount} USDC\nАдреса: {from_address}\nСтатус: {status}\nДата: {timestamp}\nТранзакція: <a href='{arbiscan_url}'>{tx_hash}</a>\n\n"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_deposits")]
    ])
    try:
        await callback.message.edit_text(message, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await bot.send_message(callback.message.chat.id, message, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("history_deposits_page_"))
async def history_deposits_page(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    logger.info(f"Received callback.data in history_deposits_page: {callback.data}")
    parts = callback.data.split("_")
    if len(parts) < 4:
        logger.error(f"Invalid callback.data format: {callback.data}")
        await callback.message.edit_text(
            "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
        )
        await callback.answer()
        return

    page = int(parts[-1])

    # Отримуємо унікальні дати
    deposit_dates = get_activity_dates(user_id, "deposits")
    logger.info(f"Deposit dates for user {user_id}: {deposit_dates}")

    if not deposit_dates:
        message = "📜 Історія поповнень\n\nЗаписів не знайдено."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        return

    # Пагінація
    dates_per_page = 8
    total_dates = len(deposit_dates)
    total_pages = (total_dates + dates_per_page - 1) // dates_per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * dates_per_page
    end_idx = start_idx + dates_per_page
    page_dates = deposit_dates[start_idx:end_idx]

    message = f"📜 Історія поповнень (Сторінка {page}/{total_pages})\n\nОберіть дату:"
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for date in page_dates:
        date_callback = date.replace(".", "_")
        markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"history_deposits_date_{date_callback}_{page}")])

    # Додаємо кнопки пагінації
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_deposits_page_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_deposits_page_{page+1}"))
    if nav_buttons:
        markup.inline_keyboard.append(nav_buttons)
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "history_purchases" or c.data.startswith("history_purchases_date_"))
async def history_purchases(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"Entering history_purchases with callback.data: {data}")
    if data == "history_purchases":
        # Показуємо список дат із пагінацією
        purchase_dates = get_activity_dates(user_id, "big_game_history")
        purchase_dates.extend(get_activity_dates(user_id, "tournament_history"))
        purchase_dates.extend(get_company_lottery_dates(user_id))
        purchase_dates = sorted(list(set(purchase_dates)), reverse=True)
        logger.info(f"Purchase dates for user {user_id}: {purchase_dates}")
        if not purchase_dates:
            message = "📜 Історія покупок\n\nЗаписів не знайдено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            await callback.answer()
            return

        # Пагінація: максимум 8 дат на сторінці
        dates_per_page = 8
        total_dates = len(purchase_dates)
        total_pages = (total_dates + dates_per_page - 1) // dates_per_page
        page = 1  # Початкова сторінка

        start_idx = (page - 1) * dates_per_page
        end_idx = start_idx + dates_per_page
        page_dates = purchase_dates[start_idx:end_idx]

        message = f"📜 Історія покупок (Сторінка {page}/{total_pages})\n\nОберіть дату:"
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for date in page_dates:
            date_callback = date.replace(".", "_")
            markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"history_purchases_date_{date_callback}_{page}")])

        # Додаємо кнопки пагінації
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_purchases_page_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_purchases_page_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
    else:
        # Показуємо записи за обрану дату
        parts = data.split("_")
        logger.info(f"Parts after splitting callback.data: {parts}")
        if len(parts) < 7:  # Змінюємо перевірку на 7, оскільки очікуємо 7 частин
            logger.error(f"Invalid callback.data format: {data}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_purchases")]
                ])
            )
            await callback.answer()
            return
        else:
            date = f"{parts[3]}.{parts[4]}.{parts[5]}"  # Конвертуємо назад у DD.MM.YYYY
            page = int(parts[6])  # Сторінка

        try:
            # Перевіряємо, чи date має правильний формат DD.MM.YYYY
            datetime.strptime(date, "%d.%m.%Y")
        except ValueError as e:
            logger.error(f"Invalid date format: {date}, error: {str(e)}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат дати. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_purchases")]
                ])
            )
            await callback.answer()
            return

        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")

        # Отримуємо записи з big_game_history
        c.execute("SELECT history_id, budget_level, ticket_price, status, winnings, timestamp FROM big_game_history WHERE user_id = ? AND SUBSTR(timestamp, 1, 10) = ? ORDER BY timestamp DESC",
                  (user_id, date_sql))
        big_game_records = c.fetchall()

        # Отримуємо записи з tournament_history
        c.execute("SELECT history_id, tournament_id, ticket_price, status, winnings, timestamp FROM tournament_history WHERE user_id = ? AND SUBSTR(timestamp, 1, 10) = ? ORDER BY timestamp DESC",
                  (user_id, date_sql))
        tournament_records = c.fetchall()

        # Отримуємо записи з company_lottery_participants
        c.execute("SELECT clp.lottery_id, clp.ticket_price, clp.status, clp.username, cl.budget_level, cl.participant_count, cl.winner_count, cl.status AS lottery_status, clp.timestamp "
                  "FROM company_lottery_participants clp "
                  "JOIN company_lottery cl ON clp.lottery_id = cl.lottery_id "
                  "WHERE clp.user_id = ? AND SUBSTR(clp.timestamp, 1, 10) = ? ORDER BY clp.timestamp DESC",
                  (user_id, date_sql))
        company_lottery_records = c.fetchall()

        # Об'єднуємо всі записи
        all_records = []
        for record in big_game_records:
            history_id, budget_level, ticket_price, status, winnings, timestamp = record
            all_records.append(("big_game", history_id, budget_level, ticket_price, status, winnings, timestamp))
        for record in tournament_records:
            history_id, tournament_id, ticket_price, status, winnings, timestamp = record
            all_records.append(("tournament", history_id, tournament_id, ticket_price, status, winnings, timestamp))
        for record in company_lottery_records:
            lottery_id, ticket_price, status, username, budget_level, participant_count, winner_count, lottery_status, timestamp = record
            all_records.append(("company_lottery", lottery_id, budget_level, ticket_price, status, username, participant_count, winner_count, lottery_status, timestamp))

        # Сортуємо записи за датою
        all_records.sort(key=lambda x: x[-1], reverse=True)

        records_per_page = 5
        total_records = len(all_records)
        total_pages = (total_records + records_per_page - 1) // records_per_page
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * records_per_page
        end_idx = start_idx + records_per_page
        page_records = all_records[start_idx:end_idx]

        if not all_records:
            message = f"📜 Історія покупок за {date}\n\nЗаписів не знайдено."
        else:
            message = f"📜 Історія покупок за {date} (Сторінка {page}/{total_pages})\n\n"
            for record in page_records:
                record_type = record[0]
                timestamp = record[-1]
                formatted_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
                if record_type == "big_game":
                    _, history_id, budget_level, ticket_price, status, winnings, _ = record
                    message += (
                        f"Велика гра | ID: {history_id} | Бюджет: {budget_level.replace('_', '/')} USDC | Квиток: {ticket_price} USDC | "
                        f"Статус: {status} | Виграш: {winnings if winnings is not None else 0} USDC | Дата: {formatted_timestamp}\n"
                    )
                elif record_type == "tournament":
                    _, history_id, tournament_id, ticket_price, status, winnings, _ = record
                    c.execute("SELECT risk_level, participant_count FROM tournaments WHERE tournament_id = ?", (tournament_id,))
                    tournament = c.fetchone()
                    risk_level, participant_count = tournament if tournament else ("Unknown", "Unknown")
                    message += (
                        f"Турнір | ID: {tournament_id} | Ризик: {risk_level}% | Учасники: {participant_count} | Квиток: {ticket_price} USDC | "
                        f"Статус: {status} | Виграш: {winnings if winnings is not None else 0} USDC | Дата: {formatted_timestamp}\n"
                    )
                elif record_type == "company_lottery":
                    _, lottery_id, budget_level, ticket_price, status, username, participant_count, winner_count, lottery_status, _ = record
                    c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
                    current_participants = c.fetchone()[0]
                    message += (
                        f"Лотерея компанії | ID: {lottery_id} | Юзернейм: {username if username else 'Невідомий'} | Квиток: {ticket_price} USDC | "
                        f"Статус: {status} | Бюджет: {budget_level.replace('_', '/')} USDC | Учасники: {current_participants}/{participant_count} | "
                        f"Переможці: {winner_count} | Статус лотереї: {lottery_status} | Дата: {formatted_timestamp}\n"
                    )

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        date_callback = date.replace(".", "_")
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_purchases_date_{date_callback}_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_purchases_date_{date_callback}_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history_purchases")])

        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        conn.close()

@router.callback_query(lambda c: c.data == "history_withdrawals" or c.data.startswith("history_withdrawals_date_"))
async def history_withdrawals(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"Entering history_withdrawals with callback.data: {data}")
    if data == "history_withdrawals":
        # Показуємо список дат із пагінацією
        withdrawal_dates = get_activity_dates(user_id, "withdrawals")
        logger.info(f"Withdrawal dates for user {user_id}: {withdrawal_dates}")
        if not withdrawal_dates:
            message = "📜 Історія виведень\n\nЗаписів не знайдено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            await callback.answer()
            return

        # Пагінація: максимум 8 дат на сторінці
        dates_per_page = 8
        total_dates = len(withdrawal_dates)
        total_pages = (total_dates + dates_per_page - 1) // dates_per_page
        page = 1  # Початкова сторінка

        start_idx = (page - 1) * dates_per_page
        end_idx = start_idx + dates_per_page
        page_dates = withdrawal_dates[start_idx:end_idx]

        message = f"📜 Історія виведень (Сторінка {page}/{total_pages})\n\nОберіть дату:"
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for date in page_dates:
            date_callback = date.replace(".", "_")
            markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"history_withdrawals_date_{date_callback}_{page}")])

        # Додаємо кнопки пагінації
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_withdrawals_page_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_withdrawals_page_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
    else:
        # Показуємо записи за обрану дату
        parts = data.split("_")
        logger.info(f"Parts after splitting callback.data: {parts}")
        if len(parts) < 7:  # Змінюємо перевірку на 7, оскільки очікуємо 7 частин
            logger.error(f"Invalid callback.data format: {data}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_withdrawals")]
                ])
            )
            await callback.answer()
            return
        else:
            date = f"{parts[3]}.{parts[4]}.{parts[5]}"  # Конвертуємо назад у DD.MM.YYYY
            page = int(parts[6])  # Сторінка

        try:
            # Перевіряємо, чи date має правильний формат DD.MM.YYYY
            datetime.strptime(date, "%d.%m.%Y")
        except ValueError as e:
            logger.error(f"Invalid date format: {date}, error: {str(e)}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат дати. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_withdrawals")]
                ])
            )
            await callback.answer()
            return

        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
        c.execute("SELECT withdrawal_id, amount, to_address, status, timestamp, tx_hash FROM withdrawals WHERE user_id = ? AND SUBSTR(timestamp, 1, 10) = ? ORDER BY timestamp DESC",
                  (user_id, date_sql))
        withdrawals = c.fetchall()
        logger.info(f"Withdrawals for user {user_id} on date {date}: {withdrawals}")

        records_per_page = 5
        total_records = len(withdrawals)
        total_pages = (total_records + records_per_page - 1) // records_per_page
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * records_per_page
        end_idx = start_idx + records_per_page
        page_withdrawals = withdrawals[start_idx:end_idx]

        if not withdrawals:
            message = f"📜 Історія виведень за {date}\n\nЗаписів не знайдено."
        else:
            message = f"📜 Історія виведень за {date} (Сторінка {page}/{total_pages})\n\n"
            for withdrawal in page_withdrawals:
                withdrawal_id, amount, to_address, status, timestamp, tx_hash = withdrawal
                formatted_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
                message += (
                    f"ID: {withdrawal_id} | Сума: {amount} USDC | Адреса: {to_address[:6]}...{to_address[-4:]} | "
                    f"Статус: {status} | Дата: {formatted_timestamp} | "
                    f"Tx: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash[:6]}...</a>\n"
                )

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        date_callback = date.replace(".", "_")
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_withdrawals_date_{date_callback}_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_withdrawals_date_{date_callback}_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history_withdrawals")])

        await callback.message.edit_text(message, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
        await callback.answer()
        conn.close()

@router.callback_query(lambda c: c.data == "history_purchases")
async def history_purchases_page(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    logger.info(f"Received callback.data in history_purchases_page: {callback.data}")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Історія Великої гри", callback_data="history_big_game_dates")],
        [InlineKeyboardButton(text="📜 Історія турнірів", callback_data="history_tournament_dates")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
    ])
    await callback.message.edit_text("Оберіть розділ історії покупок:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("hcl_date_") | c.data.startswith("history_company_lottery_dates"))
async def history_company_lottery_dates(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data
    logger.info(f"Received callback.data in history_company_lottery_dates: {data}")

    # Визначаємо, звідки прийшов користувач, і куди повертатися кнопкою "⬅️ Назад"
    if data.endswith("_from_history"):
        back_callback = "history"  # Повертаємося до "📜 Історія"
        list_dates_callback = "history_company_lottery_dates_from_history"  # Повернення до списку дат
        logger.info(f"User {user_id} came from 'history', setting back_callback to 'history' and list_dates_callback to 'history_company_lottery_dates_from_history'")
    elif data.endswith("_from_company_lottery"):
        back_callback = "company_lottery"  # Повертаємося до "🏢 Лотерея компанією"
        list_dates_callback = "history_company_lottery_dates_from_company_lottery"  # Повернення до списку дат
        logger.info(f"User {user_id} came from 'company_lottery', setting back_callback to 'company_lottery' and list_dates_callback to 'history_company_lottery_dates_from_company_lottery'")
    else:
        # Якщо data не закінчується на _from_history чи _from_company_lottery, перевіряємо попередній контекст
        if "history_company_lottery_dates_from_history" in data:
            back_callback = "history"
            list_dates_callback = "history_company_lottery_dates_from_history"
            logger.info(f"User {user_id} data contains 'history_company_lottery_dates_from_history', setting back_callback to 'history'")
        else:
            back_callback = "company_lottery"
            list_dates_callback = "history_company_lottery_dates_from_company_lottery"
            logger.info(f"User {user_id} data does not match known patterns, defaulting back_callback to 'company_lottery'")
    logger.info(f"Final back_callback for user {user_id}: {back_callback}, list_dates_callback: {list_dates_callback}")

    try:
        # Обробка пагінації
        if data.startswith("history_company_lottery_dates_page_"):
            logger.info(f"Processing pagination for user {user_id}, callback_data: {data}")
            parts = data.split("_")
            logger.info(f"Parts after splitting callback.data: {parts}, length: {len(parts)}")

            # Перевіряємо формат callback_data
            if len(parts) != 6:  # history_company_lottery_dates_page_2 -> 6 частин
                logger.error(f"Invalid callback.data format for pagination: {data}, expected 6 parts, got {len(parts)}")
                message = "❌ Помилка: неправильний формат запиту для пагінації. Спробуйте ще раз."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]
                ])
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                return

            # Парсимо номер сторінки
            try:
                page = int(parts[5])
                logger.info(f"Parsed page for pagination: {page}")
            except (IndexError, ValueError) as e:
                logger.error(f"Failed to parse page from callback_data {data}: {str(e)}")
                message = "❌ Помилка: не вдалося обробити сторінку. Спробуйте ще раз."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]
                ])
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                return

            # Отримуємо список дат
            company_lottery_dates = get_company_lottery_dates(user_id)
            logger.info(f"Company lottery dates for user {user_id}: {company_lottery_dates}")
            if not company_lottery_dates:
                message = "📜 Історія лотерей компанії\n\nЗаписів не знайдено."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]
                ])
                logger.info(f"Editing message for user {user_id} with no records")
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                return

            # Унікалізуємо дати
            company_lottery_dates = list(dict.fromkeys(company_lottery_dates))  # Зберігаємо порядок і видаляємо дублікати
            logger.info(f"Unique company lottery dates for user {user_id}: {company_lottery_dates}")

            # Пагінація: максимум 8 дат на сторінці
            dates_per_page = 8
            total_dates = len(company_lottery_dates)
            total_pages = (total_dates + dates_per_page - 1) // dates_per_page
            page = max(1, min(page, total_pages))  # Переконуємося, що сторінка в межах допустимого
            logger.info(f"Pagination: dates_per_page={dates_per_page}, total_dates={total_dates}, total_pages={total_pages}, adjusted page={page}")

            start_idx = (page - 1) * dates_per_page
            end_idx = start_idx + dates_per_page
            page_dates = company_lottery_dates[start_idx:end_idx]
            logger.info(f"Page dates for page {page}: {page_dates}")

            message = f"📜 Історія лотерей компанії (Сторінка {page}/{total_pages})\n\nОберіть дату:"
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            for date in page_dates:
                date_callback = date.replace(".", "_")
                callback_data = f"hcl_date_{date_callback}_{page}"
                logger.info(f"Generating button for date {date} with callback_data: {callback_data}")
                markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=callback_data)])

            # Додаємо кнопки пагінації
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_company_lottery_dates_page_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_company_lottery_dates_page_{page+1}"))
            if nav_buttons:
                markup.inline_keyboard.append(nav_buttons)
            markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])
            logger.info(f"Markup for page {page}: {markup.inline_keyboard}")

            logger.info(f"Editing message for user {user_id} with dates, page {page}/{total_pages}")
            try:
                await callback.message.edit_text(message, reply_markup=markup)
                logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
            except TelegramBadRequest as e:
                logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
            await callback.answer()
            return

        # Обробка списку дат
        if data in ["history_company_lottery_dates", "history_company_lottery_dates_from_history", "history_company_lottery_dates_from_company_lottery"]:
            logger.info(f"Processing history_company_lottery_dates for user {user_id}")
            company_lottery_dates = get_company_lottery_dates(user_id)
            logger.info(f"Company lottery dates for user {user_id}: {company_lottery_dates}")
            if not company_lottery_dates:
                message = "📜 Історія лотерей компанії\n\nЗаписів не знайдено."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]
                ])
                logger.info(f"Editing message for user {user_id} with no records")
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                return

            # Унікалізуємо дати
            company_lottery_dates = list(dict.fromkeys(company_lottery_dates))  # Зберігаємо порядок і видаляємо дублікати
            logger.info(f"Unique company lottery dates for user {user_id}: {company_lottery_dates}")

            # Пагінація: максимум 8 дат на сторінці
            dates_per_page = 8
            total_dates = len(company_lottery_dates)
            total_pages = (total_dates + dates_per_page - 1) // dates_per_page
            page = 1  # Початкова сторінка
            logger.info(f"Pagination: dates_per_page={dates_per_page}, total_dates={total_dates}, total_pages={total_pages}, page={page}")

            start_idx = (page - 1) * dates_per_page
            end_idx = start_idx + dates_per_page
            page_dates = company_lottery_dates[start_idx:end_idx]
            logger.info(f"Page dates for page {page}: {page_dates}")

            message = f"📜 Історія лотерей компанії (Сторінка {page}/{total_pages})\n\nОберіть дату:"
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            for date in page_dates:
                date_callback = date.replace(".", "_")
                callback_data = f"hcl_date_{date_callback}_{page}"
                logger.info(f"Generating button for date {date} with callback_data: {callback_data}")
                markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=callback_data)])

            # Додаємо кнопки пагінації
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_company_lottery_dates_page_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_company_lottery_dates_page_{page+1}"))
            if nav_buttons:
                markup.inline_keyboard.append(nav_buttons)
            markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])
            logger.info(f"Markup for page {page}: {markup.inline_keyboard}")

            logger.info(f"Editing message for user {user_id} with dates, page {page}/{total_pages}")
            try:
                await callback.message.edit_text(message, reply_markup=markup)
                logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
            except TelegramBadRequest as e:
                logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
            await callback.answer()
        else:
            # Показуємо записи за обрану дату
            logger.info(f"Processing date selection for user {user_id}, callback_data: {data}")
            parts = data.split("_")
            logger.info(f"Parts after splitting callback.data: {parts}, length: {len(parts)}")

            # Перевіряємо формат callback_data
            if len(parts) != 6:  # hcl_date_23_03_2025_1 -> 6 частин
                logger.error(f"Invalid callback.data format: {data}, expected 6 parts, got {len(parts)}")
                message = "❌ Помилка: неправильний формат запиту. Спробуйте ще раз."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=list_dates_callback)]
                ])
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                return

            # Парсимо дату і сторінку
            try:
                day, month, year = parts[2], parts[3], parts[4]
                date = f"{day}.{month}.{year}"
                page = int(parts[5])
                logger.info(f"Parsed date: {date}, page: {page}")
            except (IndexError, ValueError) as e:
                logger.error(f"Failed to parse date or page from callback_data {data}: {str(e)}")
                message = "❌ Помилка: не вдалося обробити дату. Спробуйте ще раз."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=list_dates_callback)]
                ])
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                return

            # Виконуємо SQL-запит
            try:
                conn = sqlite3.connect("lottery.db")
                c = conn.cursor()
                date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
                logger.info(f"Executing SQL query for user {user_id} on date {date_sql}")
                c.execute("SELECT clp.lottery_id, clp.ticket_price, clp.status, clp.username, cl.budget_level, cl.participant_count, cl.winner_count, cl.status AS lottery_status "
                          "FROM company_lottery_participants clp "
                          "JOIN company_lottery cl ON clp.lottery_id = cl.lottery_id "
                          "WHERE clp.user_id = ? AND SUBSTR(clp.timestamp, 1, 10) = ? ORDER BY clp.timestamp DESC",
                          (user_id, date_sql))
                lotteries = c.fetchall()
                logger.info(f"Company lotteries for user {user_id} on date {date}: {lotteries}")
            except Exception as e:
                logger.error(f"SQL query failed for user {user_id} on date {date_sql}: {str(e)}")
                message = "❌ Помилка: не вдалося отримати дані з бази. Спробуйте ще раз."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=list_dates_callback)]
                ])
                try:
                    await callback.message.edit_text(message, reply_markup=markup)
                    logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
                except TelegramBadRequest as e:
                    logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                    sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                    logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
                await callback.answer()
                if 'conn' in locals():
                    conn.close()
                return

            # Обробляємо результати
            records_per_page = 5
            total_records = len(lotteries)
            total_pages = (total_records + records_per_page - 1) // records_per_page
            page = max(1, min(page, total_pages))
            logger.info(f"Records pagination: records_per_page={records_per_page}, total_records={total_records}, total_pages={total_pages}, page={page}")

            start_idx = (page - 1) * records_per_page
            end_idx = start_idx + records_per_page
            page_lotteries = lotteries[start_idx:end_idx]
            logger.info(f"Page lotteries for page {page}: {page_lotteries}")

            if not lotteries:
                message = f"📜 Історія лотерей компанії за {date}\n\nЗаписів не знайдено."
            else:
                message = f"📜 Історія лотерей компанії за {date} (Сторінка {page}/{total_pages})\n\n"
                for lottery in page_lotteries:
                    lottery_id, ticket_price, status, username, budget_level, participant_count, winner_count, lottery_status = lottery
                    try:
                        c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
                        current_participants = c.fetchone()[0]
                        logger.info(f"Current participants for lottery {lottery_id}: {current_participants}")
                        message += (
                            f"ID: {lottery_id} | Юзернейм: {username if username else 'Невідомий'} | Квиток: {ticket_price} USDC | "
                            f"Статус: {status} | Бюджет: {budget_level.replace('_', '/')} USDC | Учасники: {current_participants}/{participant_count} | "
                            f"Переможці: {winner_count} | Статус лотереї: {lottery_status}\n"
                        )
                    except Exception as e:
                        logger.error(f"Failed to fetch current participants for lottery {lottery_id}: {str(e)}")
                        message += (
                            f"ID: {lottery_id} | Юзернейм: {username if username else 'Невідомий'} | Квиток: {ticket_price} USDC | "
                            f"Статус: {status} | Бюджет: {budget_level.replace('_', '/')} USDC | Учасники: Невідомо/{participant_count} | "
                            f"Переможці: {winner_count} | Статус лотереї: {lottery_status}\n"
                        )

            markup = InlineKeyboardMarkup(inline_keyboard=[])
            date_callback = date.replace(".", "_")
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"hcl_date_{date_callback}_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"hcl_date_{date_callback}_{page+1}"))
            if nav_buttons:
                markup.inline_keyboard.append(nav_buttons)
            markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=list_dates_callback)])
            logger.info(f"Markup for lotteries on date {date}, page {page}: {markup.inline_keyboard}")

            logger.info(f"Editing message for user {user_id} with lotteries for date {date}, page {page}/{total_pages}")
            try:
                await callback.message.edit_text(message, reply_markup=markup)
                logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
            except TelegramBadRequest as e:
                logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
                sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
                logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
                await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
            await callback.answer()
            conn.close()
    except Exception as e:
        logger.error(f"Error in history_company_lottery_dates for user {user_id}: {str(e)}")
        message = "❌ Виникла помилка. Спробуйте ще раз."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
        ])
        try:
            await callback.message.edit_text(message, reply_markup=markup)
            logger.info(f"Successfully edited message {callback.message.message_id} for user {user_id}")
        except TelegramBadRequest as e:
            logger.warning(f"Failed to edit message {callback.message.message_id}: {str(e)}")
            sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
            logger.info(f"Sent new message with id {sent_message.message_id} as fallback")
            await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        await callback.answer()

@router.callback_query(lambda c: c.data.startswith("view_company_session_"))
async def view_company_session(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data
    
    try:
        lottery_id = int(data.split("_")[-1])
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing lottery_id in view_company_session for user {user_id}: {str(e)}")
        message = "❌ Помилка при обробці запиту. Спробуйте ще раз."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        return
    
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    
    # Отримуємо деталі сеансу
    c.execute("SELECT clp.ticket_price, cl.participant_count, cl.budget_level, cl.winner_count "
              "FROM company_lottery_participants clp "
              "JOIN company_lottery cl ON clp.lottery_id = cl.lottery_id "
              "WHERE clp.user_id = ? AND clp.lottery_id = ? AND clp.status = 'active' AND cl.status = 'pending'",
              (user_id, lottery_id))
    session = c.fetchone()
    
    if not session:
        message = "📜 Лотерея для компанії\n\nСеанс не знайдено."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        conn.close()
        await callback.answer()
        return

    ticket_price, participant_count, budget_level, winner_count = session
    c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
    current_participants = c.fetchone()[0]
    
    # Генеруємо посилання на лотерею
    link = generate_lottery_link(lottery_id)
    
    # Перевіряємо ticket_price перед конвертацією
    try:
        ticket_price_int = int(float(ticket_price))
    except (TypeError, ValueError) as e:
        logger.error(f"Error converting ticket_price in view_company_session for user {user_id}, lottery_id {lottery_id}: {str(e)}")
        message = "❌ Помилка при обробці запиту: некоректна ціна квитка."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        conn.close()
        await callback.answer()
        return
    
    message = (
        f"📜 Лотерея для компанії\n\n"
        f"Посилання: {link}\n"
        f"Деталі гри:\n"
        f"- Кількість учасників: {current_participants}/{participant_count}\n"
        f"- Переможці: {winner_count}\n"
        f"- Бюджет: {budget_level.replace('_', '/')}$\n"
        f"- Ваш квиток: {ticket_price} USDC\n"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Відмовитись", callback_data=f"cancel_company_lottery_{lottery_id}_{ticket_price_int}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
    ])
    logger.info(f"Formed callback_data for cancel_company_lottery: cancel_company_lottery_{lottery_id}_{ticket_price_int}")
    await callback.message.edit_text(message, reply_markup=markup)
    conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("cancel_company_lottery_"))
async def cancel_company_lottery(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Processing cancel_company_lottery for user {user_id}, chat_id {chat_id}, callback_data: {callback.data}")

    try:
        data = callback.data.split("_")
        if len(data) != 5:  # Очікуємо ["cancel", "company", "lottery", lottery_id, ticket_price]
            raise ValueError(f"Invalid callback_data format: {callback.data}")
        lottery_id = int(data[3])  # Використовуємо data[3] для lottery_id
        ticket_price = float(data[4])  # Використовуємо data[4] для ticket_price
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing callback_data in cancel_company_lottery for user {user_id}: {str(e)}")
        message = "❌ Помилка при обробці запиту. Спробуйте ще раз."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        return

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()

    # Перевіряємо, чи користувач зареєстрований у таблиці users
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        logger.warning(f"User {user_id} not found in users table, creating new record")
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0.0))
        conn.commit()

    # Перевіряємо, чи користувач бере участь у лотереї
    c.execute("SELECT participation_id FROM company_lottery_participants WHERE lottery_id = ? AND user_id = ? AND status = 'active'",
              (lottery_id, user_id))
    participation = c.fetchone()
    if not participation:
        logger.warning(f"User {user_id} is not participating in lottery {lottery_id}")
        message = "❌ Ви не берете участь у цій лотереї."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        conn.close()
        await callback.answer()
        return

    participation_id = participation[0]
    try:
        # Повертаємо кошти на баланс
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ticket_price, user_id))
        # Оновлюємо статус участі
        c.execute("UPDATE company_lottery_participants SET status = 'cancelled' WHERE participation_id = ?", (participation_id,))
        conn.commit()
        logger.info(f"User {user_id} cancelled participation in lottery {lottery_id}, refunded {ticket_price} USDC")

        message = "✅ Ви відмовилися від участі в лотереї. Кошти повернуті на ваш баланс."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error cancelling company lottery participation for user {user_id}: {str(e)}")
        message = f"❌ Помилка при відмові від участі: {str(e)}"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
    finally:
        conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("withdrawal_date_"))
async def view_withdrawal_history_by_date(callback: CallbackQuery):
    user_id = callback.from_user.id
    date = callback.data.replace("withdrawal_date_", "")
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT amount, to_address, status, timestamp, tx_hash FROM withdrawals WHERE user_id = ? AND DATE(timestamp) = ? AND status != 'pending'", (user_id, date))
    withdrawals = c.fetchall()
    conn.close()
    if not withdrawals:
        message = f"💸 За {date} немає записів про виведення."
    else:
        message = f"💸 <b>Історія виведень за {date}:</b>\n\n"
        for withdrawal in withdrawals:
            amount, to_address, status, timestamp, tx_hash = withdrawal
            arbiscan_url = f"https://arbiscan.io/tx/{tx_hash}"
            message += f"Сума: {amount} USDC\nАдреса: {to_address}\nСтатус: {status}\nДата: {timestamp}\nТранзакція: <a href='{arbiscan_url}'>{tx_hash}</a>\n\n"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_withdrawals")]
    ])
    await callback.message.edit_text(message, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("history_withdrawals_page_"))
async def history_withdrawals_page(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    logger.info(f"Received callback.data in history_withdrawals_page: {callback.data}")
    parts = callback.data.split("_")
    if len(parts) < 4:
        logger.error(f"Invalid callback.data format: {callback.data}")
        await callback.message.edit_text(
            "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
        )
        await callback.answer()
        return

    page = int(parts[-1])

    # Отримуємо унікальні дати
    withdrawal_dates = get_activity_dates(user_id, "withdrawals")
    logger.info(f"Withdrawal dates for user {user_id}: {withdrawal_dates}")

    if not withdrawal_dates:
        message = "📜 Історія виведень\n\nЗаписів не знайдено."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        return

    # Пагінація
    dates_per_page = 8
    total_dates = len(withdrawal_dates)
    total_pages = (total_dates + dates_per_page - 1) // dates_per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * dates_per_page
    end_idx = start_idx + dates_per_page
    page_dates = withdrawal_dates[start_idx:end_idx]

    message = f"📜 Історія виведень (Сторінка {page}/{total_pages})\n\nОберіть дату:"
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for date in page_dates:
        date_callback = date.replace(".", "_")
        markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"history_withdrawals_date_{date_callback}_{page}")])

    # Додаємо кнопки пагінації
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_withdrawals_page_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_withdrawals_page_{page+1}"))
    if nav_buttons:
        markup.inline_keyboard.append(nav_buttons)
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("history_purchases_"))
async def history_purchases(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"Processing history_purchases for user {user_id}, callback_data: {data}")

    if data == "history_purchases_1":
        # Показуємо список дат
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        try:
            c.execute("SELECT timestamp FROM deposits WHERE user_id = ? AND status = 'completed'", (user_id,))
            timestamps = [row[0] for row in c.fetchall()]
            logger.info(f"All timestamps from deposits for user {user_id}: {timestamps}")
        except sqlite3.Error as e:
            logger.error(f"Database error while fetching timestamps for user {user_id}: {str(e)}")
            message = "❌ Помилка при отриманні історії покупок. Спробуйте ще раз пізніше."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            conn.close()
            await callback.answer()
            return

        if not timestamps:
            message = "📜 Історія покупок\n\nЗаписів не знайдено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            conn.close()
            await callback.answer()
            return

        # Витягуємо дати вручну з timestamp
        dates = []
        for timestamp in timestamps:
            try:
                date_part = timestamp.split(" ")[0]  # Беремо лише дату (YYYY-MM-DD)
                dates.append(date_part)
            except Exception as e:
                logger.error(f"Failed to parse timestamp {timestamp}: {str(e)}")
                continue

        # Видаляємо дублікати і сортуємо
        dates = sorted(list(set(dates)), reverse=True)
        logger.info(f"Raw dates from deposits for user {user_id}: {dates}")

        if not dates:
            message = "📜 Історія покупок\n\nЗаписів не знайдено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            conn.close()
            await callback.answer()
            return

        # Конвертуємо формат дати для відображення в DD.MM.YYYY
        formatted_dates = []
        for date in dates:
            try:
                formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
                formatted_dates.append(formatted_date)
            except ValueError as e:
                logger.error(f"Failed to format date {date}: {str(e)}")
                continue
        logger.info(f"Formatted dates for user {user_id}: {formatted_dates}")

        if not formatted_dates:
            message = "📜 Історія покупок\n\nЗаписів не знайдено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            conn.close()
            await callback.answer()
            return

        message = "📜 Історія покупок\n\nОберіть дату:"
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for date in formatted_dates:
            date_callback = date.replace(".", "_")
            markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"history_purchases_date_{date_callback}_1")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])
        await callback.message.edit_text(message, reply_markup=markup)
        conn.close()
    else:
        # Показуємо записи за обрану дату
        try:
            parts = data.split("_")
            date = f"{parts[4]}.{parts[5]}.{parts[6]}"  # Конвертуємо назад у DD.MM.YYYY
            page = int(parts[7])  # Сторінка
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing callback_data in history_purchases for user {user_id}: {str(e)}")
            message = "❌ Помилка при обробці запиту. Спробуйте ще раз."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            await callback.answer()
            return

        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        try:
            date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
            c.execute("SELECT amount, timestamp, tx_hash FROM deposits WHERE user_id = ? AND SUBSTR(timestamp, 1, 10) = ? AND status = 'completed' ORDER BY timestamp DESC",
                      (user_id, date_sql))
            deposits = c.fetchall()
            logger.info(f"Deposits for user {user_id} on date {date}: {deposits}")
        except sqlite3.Error as e:
            logger.error(f"Database error while fetching deposits for user {user_id}: {str(e)}")
            message = "❌ Помилка при отриманні історії покупок. Спробуйте ще раз пізніше."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            conn.close()
            await callback.answer()
            return

        records_per_page = 5
        total_records = len(deposits)
        total_pages = (total_records + records_per_page - 1) // records_per_page
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * records_per_page
        end_idx = start_idx + records_per_page
        page_deposits = deposits[start_idx:end_idx]

        if not deposits:
            message = f"📜 Історія покупок за {date}\n\nЗаписів не знайдено."
        else:
            message = f"📜 Історія покупок за {date} (Сторінка {page}/{total_pages})\n\n"
            for deposit in page_deposits:
                amount, timestamp, tx_hash = deposit
                formatted_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
                # Перевіряємо, чи tx_hash не є None
                tx_display = f"Tx: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash[:6]}...</a>\n" if tx_hash else "Tx: Немає даних\n"
                message += (
                    f"Сума: {amount} USDC\n"
                    f"Дата: {formatted_timestamp}\n"
                    f"{tx_display}\n"
                )

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        date_callback = date.replace(".", "_")
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_purchases_date_{date_callback}_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_purchases_date_{date_callback}_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

        await callback.message.edit_text(message, reply_markup=markup)
        conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("purchase_date_"))
async def view_purchase_history_by_date(callback: CallbackQuery):
    user_id = callback.from_user.id
    # Отримуємо дату з callback_data (purchase_date_DD_MM_YYYY)
    parts = callback.data.split("_")
    logger.info(f"Processing view_purchase_history_by_date with callback_data: {callback.data}, parts: {parts}")
    if len(parts) != 5:  # purchase_date_DD_MM_YYYY
        logger.error(f"Invalid callback.data format: {callback.data}, expected 5 parts, got {len(parts)}")
        await callback.message.edit_text(
            "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_purchases")]
            ]),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        await callback.answer()
        return

    day, month, year = parts[2], parts[3], parts[4]
    date = f"{day}.{month}.{year}"
    date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
    logger.info(f"Processing purchase history for user {user_id} on date {date_sql}")

    # Виконуємо SQL-запит лише для "Великої гри" і "Турнірів"
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute(
        "SELECT 'big_game' AS type, budget_level AS level, ticket_price, status, timestamp, tx_hash "
        "FROM big_game_participants WHERE user_id = ? AND DATE(timestamp) = ? "
        "UNION "
        "SELECT 'tournament' AS type, risk_level || ' (' || participant_count || ')' AS level, ticket_price, status, timestamp, tx_hash "
        "FROM tournament_participants WHERE user_id = ? AND DATE(timestamp) = ?",
        (user_id, date_sql, user_id, date_sql)
    )
    purchases = c.fetchall()
    logger.info(f"Purchases for user {user_id} on date {date_sql}: {purchases}")

    # Додатково перевіряємо, чи є записи в company_lottery_participants (для діагностики)
    c.execute(
        "SELECT 'company_lottery' AS type, budget_level AS level, ticket_price, status, timestamp, tx_hash "
        "FROM company_lottery_participants WHERE user_id = ? AND DATE(timestamp) = ?",
        (user_id, date_sql)
    )
    company_lottery_purchases = c.fetchall()
    logger.info(f"Company lottery purchases for user {user_id} on date {date_sql} (should not be displayed): {company_lottery_purchases}")
    conn.close()

    # Формуємо повідомлення
    if not purchases:
        message = f"🎫 За {date} немає записів про покупки."
    else:
        message = f"🎫 <b>Історія покупок за {date}:</b>\n\n"
        type_translations = {
            "big_game": "Велика гра",
            "tournament": "Турнір",
            "company_lottery": "Лотерея компанією"  # Залишаємо для сумісності, але не використовується
        }
        for purchase in purchases:
            trans_type, level, price, status, timestamp, tx_hash = purchase
            trans_type_display = type_translations.get(trans_type, trans_type)
            arbiscan_url = f"https://arbiscan.io/tx/{tx_hash}"
            message += (
                f"Тип: {trans_type_display}\n"
                f"Рівень: {level}\n"
                f"Сума: {price} USDC\n"
                f"Статус: {status}\n"
                f"Дата: {timestamp}\n"
                f"Транзакція: <a href='{arbiscan_url}'>{tx_hash}</a>\n\n"
            )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_purchases")]
    ])
    await callback.message.edit_text(
        message,
        reply_markup=markup,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("history_purchases_page_") | c.data.startswith("history_purchases"))
async def history_purchases_page(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"Received callback.data in history_purchases_page: {data}")

    # Обробка пагінації
    if data.startswith("history_purchases_page_"):
        parts = data.split("_")
        if len(parts) != 4:  # history_purchases_page_X
            logger.error(f"Invalid callback.data format: {data}, expected 4 parts, got {len(parts)}")
            await callback.message.edit_text(
                "❌ Помилка: неправильний формат запиту. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
                ])
            )
            await callback.answer()
            return

        page = int(parts[-1])
    else:
        page = 1  # Початкова сторінка

    # Отримуємо унікальні дати для "Великої гри" і "Турнірів"
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT SUBSTR(timestamp, 1, 10) FROM big_game_participants WHERE user_id = ? "
        "UNION "
        "SELECT DISTINCT SUBSTR(timestamp, 1, 10) FROM tournament_participants WHERE user_id = ? "
        "ORDER BY timestamp DESC",
        (user_id, user_id)
    )
    purchase_dates = [datetime.strptime(date[0], "%Y-%m-%d").strftime("%d.%m.%Y") for date in c.fetchall()]
    logger.info(f"Purchase dates for user {user_id} from big_game_participants and tournament_participants: {purchase_dates}")

    # Додатково перевіряємо дати з company_lottery_participants (для діагностики)
    c.execute(
        "SELECT DISTINCT SUBSTR(timestamp, 1, 10) FROM company_lottery_participants WHERE user_id = ? ORDER BY timestamp DESC",
        (user_id,)
    )
    company_lottery_dates = [datetime.strptime(date[0], "%Y-%m-%d").strftime("%d.%m.%Y") for date in c.fetchall()]
    logger.info(f"Company lottery dates for user {user_id} (should not be in purchase_dates): {company_lottery_dates}")
    conn.close()

    if not purchase_dates:
        message = "📜 Історія покупок\n\nЗаписів не знайдено."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        return

    # Пагінація
    dates_per_page = 8
    total_dates = len(purchase_dates)
    total_pages = (total_dates + dates_per_page - 1) // dates_per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * dates_per_page
    end_idx = start_idx + dates_per_page
    page_dates = purchase_dates[start_idx:end_idx]
    logger.info(f"Page dates for page {page}: {page_dates}")

    message = f"📜 Історія покупок (Сторінка {page}/{total_pages})\n\nОберіть дату:"
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for date in page_dates:
        date_callback = date.replace(".", "_")
        markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"purchase_date_{date_callback}")])

    # Додаємо кнопки пагінації
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_purchases_page_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_purchases_page_{page+1}"))
    if nav_buttons:
        markup.inline_keyboard.append(nav_buttons)
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("history_pending") and not c.data.startswith("history_pending_confirm_"))
async def history_pending(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"Processing history_pending with data: {data}")

    if data == "history_pending" or (data.startswith("history_pending_") and not data.startswith("history_pending_cancel_")):
        # Показуємо список транзакцій
        data_parts = data.split("_")
        page = int(data_parts[-1]) if len(data_parts) > 2 and data_parts[-1].isdigit() else 1

        active_transactions = get_active_transactions(user_id)
        logger.info(f"Active transactions for user {user_id}: {active_transactions}")
        records_per_page = 5
        total_records = len(active_transactions)
        total_pages = (total_records + records_per_page - 1) // records_per_page
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * records_per_page
        end_idx = start_idx + records_per_page
        page_transactions = active_transactions[start_idx:end_idx]

        if not active_transactions:
            message = "⏳ Очікують\n\nЗаписів не знайдено."
        else:
            message = f"⏳ Очікують (Сторінка {page}/{total_pages})\n\n"
            for trans in page_transactions:
                trans_type, participation_id, level, price, timestamp = trans
                trans_type_display = {
                    "big_game": "Велика гра",
                    "tournament": "Турнір",
                    "company_lottery": "Лотерея компанії"
                }.get(trans_type, trans_type)
                message += f"{trans_type_display} | ID: {participation_id} | {level} | {price} USDC | {timestamp}\n"

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        # Додаємо кнопки "Відмовитись" для кожної транзакції
        for trans in page_transactions:
            trans_type, participation_id, level, price, timestamp = trans
            # Спрощуємо trans_type для callback_data
            trans_type_short = {"big_game": "bg", "tournament": "t", "company_lottery": "cl"}.get(trans_type, trans_type)
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"Відмовитись від ID {participation_id}", callback_data=f"history_pending_cancel_{trans_type_short}_{participation_id}")])
        # Додаємо кнопки пагінації
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"history_pending_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"history_pending_{page+1}"))
        if nav_buttons:
            markup.inline_keyboard.append(nav_buttons)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="history")])

        await callback.message.edit_text(message, reply_markup=markup)
    elif data.startswith("history_pending_cancel_"):
        # Показуємо підтвердження відмови
        parts = data.split("_")
        trans_type_short = parts[3]
        participation_id = int(parts[4])

        # Перетворюємо скорочений trans_type назад у повний
        trans_type_map = {"bg": "big_game", "t": "tournament", "cl": "company_lottery"}
        trans_type = trans_type_map.get(trans_type_short, trans_type_short)

        # Перевіряємо, чи можна відмовитися (для "Великої гри")
        if trans_type == "big_game":
            is_active, time_status = get_big_game_status()
            if not is_active:
                message = "❌ Відмовитись від квитка 'Велика гра' можна лише до 45-ї хвилини кожної години. Набір учасників завершено."
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending_1")]
                ])
                await callback.message.edit_text(message, reply_markup=markup)
                await callback.answer()
                return

        # Отримуємо інформацію про транзакцію
        active_transactions = get_active_transactions(user_id)
        trans = next((t for t in active_transactions if t[0] == trans_type and t[1] == participation_id), None)
        if not trans:
            message = "❌ Транзакція не знайдена."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending_1")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            await callback.answer()
            return

        trans_type, participation_id, level, price, timestamp = trans
        trans_type_display = {
            "big_game": "Велика гра",
            "tournament": "Турнір",
            "company_lottery": "Лотерея компанії"
        }.get(trans_type, trans_type)

        message = (
            f"Ви впевнені, що хочете відмовитись від транзакції?\n\n"
            f"Тип: {trans_type_display}\n"
            f"ID: {participation_id}\n"
            f"Рівень: {level}\n"
            f"Сума: {price} USDC\n"
            f"Дата: {timestamp}\n\n"
        )
        if trans_type == "big_game":
            message += f"Комісія за відміну: 1 USDC\nСума до повернення: {price - 1} USDC"
        else:
            message += f"Сума до повернення: {price} USDC"

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Підтвердити відміну", callback_data=f"history_pending_confirm_{trans_type_short}_{participation_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending_1")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
    else:
        logger.warning(f"Unhandled callback_data in history_pending: {data}")
        message = "❌ Помилка: невідомий запит."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)

    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("history_pending_confirm_"))
async def history_pending_confirm(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data

    logger.info(f"Processing history_pending_confirm_ with data: {data}")
    parts = data.split("_")
    trans_type_short = parts[3]
    participation_id = int(parts[4])
    logger.info(f"Extracted trans_type_short: {trans_type_short}, participation_id: {participation_id}")

    # Перетворюємо скорочений trans_type назад у повний
    trans_type_map = {"bg": "big_game", "t": "tournament", "cl": "company_lottery"}
    trans_type = trans_type_map.get(trans_type_short, trans_type_short)
    logger.info(f"Resolved trans_type: {trans_type}")

    # Отримуємо інформацію про транзакцію
    active_transactions = get_active_transactions(user_id)
    logger.info(f"Active transactions for user {user_id}: {active_transactions}")
    trans = next((t for t in active_transactions if t[0] == trans_type and t[1] == participation_id), None)
    if not trans:
        logger.warning(f"Transaction not found for trans_type: {trans_type}, participation_id: {participation_id}")
        message = "❌ Транзакція не знайдена. Можливо, вона вже була скасована або завершена."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад до Очікують", callback_data="history_pending_1")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
        await callback.answer()
        return

    trans_type, participation_id, level, price, timestamp = trans
    trans_type_display = {
        "big_game": "Велика гра",
        "tournament": "Турнір",
        "company_lottery": "Лотерея компанії"
    }.get(trans_type, trans_type)
    logger.info(f"Found transaction: {trans}")

    # Перевіряємо час для "Великої гри"
    if trans_type == "big_game":
        is_active, time_status = get_big_game_status()
        logger.info(f"Big game status: is_active={is_active}, time_status={time_status}")
        if not is_active:
            message = "❌ Відмовитись від квитка 'Велика гра' можна лише до 45-ї хвилини кожної години. Набір учасників завершено."
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data=f"back_to_main_{callback.message.message_id}")]
            ])
            await callback.message.edit_text(message, reply_markup=markup)
            await callback.answer()
            return

    # Обчислюємо суму до повернення
    refund_amount = price
    if trans_type == "big_game":
        refund_amount = price - 1  # Комісія 1 USDC
    logger.info(f"Refund amount: {refund_amount}")

    # Оновлюємо баланс користувача і статус транзакції
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
        if trans_type == "big_game":
            c.execute("UPDATE big_game_participants SET status = 'cancelled' WHERE participation_id = ? AND user_id = ?", (participation_id, user_id))
        elif trans_type == "tournament":
            c.execute("UPDATE tournament_participants SET status = 'cancelled' WHERE participation_id = ? AND user_id = ?", (participation_id, user_id))
        elif trans_type == "company_lottery":
            c.execute("UPDATE company_lottery_participants SET status = 'cancelled' WHERE participation_id = ? AND user_id = ?", (participation_id, user_id))
        conn.commit()

        # Отримуємо новий баланс
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = c.fetchone()[0]
        logger.info(f"Updated balance for user {user_id}: {new_balance}")

        message = (
            f"✅ Відмова від транзакції успішна!\n\n"
            f"Тип: {trans_type_display}\n"
            f"ID: {participation_id}\n"
            f"Сума повернення: {refund_amount} USDC\n"
            f"Новий баланс: {new_balance} USDC"
        )
        if trans_type == "big_game":
            message += f"\nКомісія за відміну: 1 USDC"

        # Додаємо кнопку "Назад" разом із "На головну сторінку"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад до Очікують", callback_data="history_pending_1")],
            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data=f"back_to_main_{callback.message.message_id}")]
        ])
        await callback.message.edit_text(message, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during transaction cancellation: {str(e)}")
        message = f"❌ Помилка при відміні транзакції: {str(e)}"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data=f"back_to_main_{callback.message.message_id}")]
        ])
        await callback.message.edit_text(message, reply_markup=markup)
    finally:
        conn.close()

    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("pending_transaction_"))
async def view_pending_transaction(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    logger.info(f"Received callback_data: {callback.data}")
    try:
        data_after_prefix = callback.data.replace("pending_transaction_", "")
        if "back" in data_after_prefix.lower():  # Обробка кнопки "Назад"
            await history_pending(callback)
            return

        participation_id, trans_type_short = map(str, data_after_prefix.split("_", 1))
        logger.info(f"Parsed - participation_id: {participation_id}, trans_type_short: {trans_type_short}")
        transaction_type = 'big_game' if trans_type_short == 'bg' else 'tournament' if trans_type_short == 'tm' else 'company_lottery' if trans_type_short == 'cl' else None
        if not transaction_type:
            raise ValueError("Невідомий тип транзакції")
    except ValueError as e:
        await callback.message.edit_text(
            f"❌ Помилка при обробці транзакції: {e}. Зверніться до служби підтримки (@SupportBot).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
            ])
        )
        await callback.answer()
        return

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    try:
        if transaction_type == "big_game":
            c.execute("SELECT budget_level, ticket_price, timestamp FROM big_game_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
            result = c.fetchone()
            if result:
                level, price, timestamp = result
                message = f"⏳ **Деталі транзакції (Велика гра):**\n\nТип: {level}\nСума: {price} USDC\nДата: {timestamp}"
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚫 Відмовитись", callback_data=f"cancel_transaction_{participation_id}_{trans_type_short}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pending_transaction_{participation_id}_{trans_type_short}_back")]
                ])
                await callback.message.edit_text(message, reply_markup=markup)
        elif transaction_type == "tournament":
            c.execute("SELECT risk_level || ' (' || participant_count || ')', ticket_price, timestamp FROM tournament_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
            result = c.fetchone()
            if result:
                level, price, timestamp = result
                message = f"⏳ **Деталі транзакції (Турнір):**\n\nТип: {level}\nСума: {price} USDC\nДата: {timestamp}"
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚫 Відмовитись", callback_data=f"cancel_transaction_{participation_id}_{trans_type_short}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pending_transaction_{participation_id}_{trans_type_short}_back")]
                ])
                await callback.message.edit_text(message, reply_markup=markup)
        elif transaction_type == "company_lottery":
            c.execute("SELECT budget_level, ticket_price, timestamp FROM company_lottery_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
            result = c.fetchone()
            if result:
                level, price, timestamp = result
                message = f"⏳ **Деталі транзакції (Лотерея компанії):**\n\nТип: {level}\nСума: {price} USDC\nДата: {timestamp}"
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚫 Відмовитись", callback_data=f"cancel_transaction_{participation_id}_{trans_type_short}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pending_transaction_{participation_id}_{trans_type_short}_back")]
                ])
                await callback.message.edit_text(message, reply_markup=markup)
    except Exception as e:
        logger.error(f"Помилка при перегляді транзакції: {e}")
        await callback.message.edit_text(
            f"❌ Виникла помилка: {e}. Зверніться до служби підтримки (@SupportBot).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
            ])
        )
    finally:
        conn.close()
        await callback.answer()

@router.callback_query(lambda c: c.data.startswith("cancel_transaction_"))
async def cancel_transaction(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Received callback_data: {callback.data}")
    try:
        data_after_prefix = callback.data.replace("cancel_transaction_", "")
        participation_id, trans_type_short = map(str, data_after_prefix.split("_", 1))
        logger.info(f"Parsed - participation_id: {participation_id}, trans_type_short: {trans_type_short}")
        transaction_type = 'big_game' if trans_type_short == 'bg' else 'tournament' if trans_type_short == 'tm' else 'company_lottery' if trans_type_short == 'cl' else None
        if not transaction_type:
            raise ValueError("Невідомий тип транзакції")
    except ValueError as e:
        await callback.message.edit_text(
            f"❌ Помилка при обробці транзакції: {e}. Зверніться до служби підтримки (@SupportBot).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
            ])
        )
        await callback.answer()
        return

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    try:
        if transaction_type == "big_game":
            c.execute("SELECT budget_level FROM big_game_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
            result = c.fetchone()
            if result:
                budget_level = result[0]
                is_active, time_status = get_big_game_status()
                participants = count_big_game_participants(budget_level)
                if not is_active or participants >= 20:
                    await callback.message.edit_text(
                        "Вже неможливо відмовитись від транзакції, оскільки розподіл пулу вже почався.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                        ])
                    )
                    await callback.answer()
                    return
                c.execute("SELECT ticket_price FROM big_game_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
                result = c.fetchone()
                if result:
                    ticket_price = result[0]
                    refund_amount = ticket_price - 2  # Комісія 2 USDC
                    if refund_amount > 0:
                        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
                        c.execute("UPDATE big_game_participants SET status = 'cancelled' WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
                        tx_hash = send_transaction(BOT_ADDRESS, BOT_ADDRESS, refund_amount, PRIVATE_KEY)
                        conn.commit()
                        await callback.message.edit_text(
                            f"🚫 Відмова від транзакції прийнята. Повернення {refund_amount} USDC обробляється.\n"
                            f"Транзакція: <code>{tx_hash}</code>\nЗверніть увагу: 2 USDC утримані як комісія.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                            ]),
                            parse_mode="HTML"
                        )
                        await history_pending(callback)
                    else:
                        await callback.message.edit_text(
                            "❌ Помилка: Немає достатньо коштів для повернення після утримання комісії.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                            ])
                        )
            else:
                await callback.message.edit_text(
                    "❌ Помилка: Транзакція не знайдена або вже оброблена. Зверніться до служби підтримки (@SupportBot).",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                    ])
                )
        elif transaction_type == "tournament":
            c.execute("SELECT risk_level, participant_count, ticket_price FROM tournament_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
            result = c.fetchone()
            if result:
                risk_level, participant_count, ticket_price = result
                logger.info(f"Cancel check: risk_level={risk_level}, participant_count={participant_count}")
                participants = count_tournament_participants(risk_level, participant_count)
                logger.info(f"Cancel check: participants={participants}")
                # Перевіряємо, чи набрано потрібну кількість учасників
                if participants >= participant_count:
                    await callback.message.edit_text(
                        "Вже неможливо відмовитись від транзакції, оскільки розподіл пулу вже почався.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                        ])
                    )
                    await callback.answer()
                    return
                # Скасування можливе
                refund_amount = ticket_price  # Без комісії для турнірів
                if refund_amount > 0:
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
                    c.execute("UPDATE tournament_participants SET status = 'cancelled' WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
                    tx_hash = send_transaction(BOT_ADDRESS, BOT_ADDRESS, refund_amount, PRIVATE_KEY)
                    conn.commit()
                    await callback.message.edit_text(
                        f"🚫 Відмова від транзакції прийнята. Повернення {refund_amount} USDC обробляється.\n"
                        f"Транзакція: <code>{tx_hash}</code>\nКомісія не стягнута.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                        ]),
                        parse_mode="HTML"
                    )
                    await history_pending(callback)
                else:
                    await callback.message.edit_text(
                        "❌ Помилка: Немає достатньо коштів для повернення.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                        ])
                    )
            else:
                await callback.message.edit_text(
                    "❌ Помилка: Транзакція не знайдена або вже оброблена. Зверніться до служби підтримки (@SupportBot).",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                    ])
                )
        elif transaction_type == "company_lottery":
            c.execute("SELECT ticket_price FROM company_lottery_participants WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
            result = c.fetchone()
            if result:
                ticket_price = result[0]
                refund_amount = ticket_price - 2  # Комісія для "Лотереї компанією"
                if refund_amount > 0:
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
                    c.execute("UPDATE company_lottery_participants SET status = 'cancelled' WHERE participation_id = ? AND user_id = ? AND status = 'active'", (participation_id, user_id))
                    tx_hash = send_transaction(BOT_ADDRESS, BOT_ADDRESS, refund_amount, PRIVATE_KEY)
                    conn.commit()
                    await callback.message.edit_text(
                        f"🚫 Відмова від транзакції прийнята. Повернення {refund_amount} USDC обробляється.\n"
                        f"Транзакція: <code>{tx_hash}</code>\nЗверніть увагу: 2 USDC утримані як комісія.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                        ]),
                        parse_mode="HTML"
                    )
                    await history_pending(callback)
                else:
                    await callback.message.edit_text(
                        "❌ Помилка: Немає достатньо коштів для повернення після утримання комісії.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                        ])
                    )
            else:
                await callback.message.edit_text(
                    "❌ Помилка: Транзакція не знайдена або вже оброблена. Зверніться до служби підтримки (@SupportBot).",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                    ])
                )
        else:
            await callback.message.edit_text(
                "❌ Помилка: Невідомий тип транзакції. Зверніться до служби підтримки (@SupportBot).",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
                ])
            )
    except Exception as e:
        conn.rollback()
        logger.error(f"Помилка при скасуванні транзакції: {e}")
        await callback.message.edit_text(
            f"❌ Виникла помилка: {e}. Зверніться до служби підтримки (@SupportBot).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_pending")]
            ])
        )
    finally:
        conn.close()
        await state.clear()
        await callback.answer()

@router.callback_query(lambda c: c.data == "play")
async def play(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"User {user_id} accessing play menu")

    # Видаляємо поточне повідомлення
    try:
        await callback.message.delete()
        logger.info(f"Deleted current message {callback.message.message_id} for user {user_id}")
    except TelegramBadRequest as e:
        logger.warning(f"Failed to delete current message {callback.message.message_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while deleting current message {callback.message.message_id}: {str(e)}")

    # Перевіряємо кількість активних квитків
    active_tickets = count_active_tickets(user_id)
    if active_tickets >= 3:
        transactions = get_active_transactions(user_id)
        message = "❌ Ви досягли ліміту в 3 активних квитки. Зачекайте, поки один із квитків завершиться (виграш/програш), щоб придбати новий.\n\n**Ваші активні квитки:**\n"
        for trans_type, trans_id, level, ticket_price, timestamp in transactions:
            if trans_type == "big_game":
                message += f"Велика гра | ID: {trans_id} | Рівень: {level.replace('_', '/')} USDC | Квиток: {ticket_price} USDC | Час: {timestamp}\n"
            elif trans_type == "tournament":
                message += f"Турнір | ID: {trans_id} | Рівень: {level} | Квиток: {ticket_price} USDC | Час: {timestamp}\n"
            elif trans_type == "company_lottery":
                message += f"Лотерея компанії | ID: {trans_id} | Бюджет: {level.replace('_', '/')} USDC | Квиток: {ticket_price} USDC | Час: {timestamp}\n"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
        try:
            sent_message = await bot.send_message(chat_id, message, reply_markup=markup)
            logger.info(f"Sent new message with id {sent_message.message_id} for user {user_id}")
            await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        except TelegramBadRequest as e:
            logger.error(f"Failed to send new message for user {user_id}: {str(e)}")
            sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
            await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        except Exception as e:
            logger.error(f"Unexpected error while sending new message for user {user_id}: {str(e)}")
            sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
            await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        await callback.answer()
        return

    # Якщо ліміт не досягнуто, показуємо меню вибору гри
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Велика гра", callback_data="big_game")],
        [InlineKeyboardButton(text="🏆 Турніри", callback_data="tournaments")],
        [InlineKeyboardButton(text="🏢 Лотерея компанією", callback_data="company_lottery")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    try:
        sent_message = await bot.send_message(chat_id, "🎮 Оберіть тип гри:", reply_markup=markup)
        logger.info(f"Sent new message with id {sent_message.message_id} for user {user_id}")
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except TelegramBadRequest as e:
        logger.error(f"Failed to send new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except Exception as e:
        logger.error(f"Unexpected error while sending new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

    await callback.answer()

@router.callback_query(lambda c: c.data == "company_lottery")
async def company_lottery_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Entering company_lottery for user {user_id}, chat_id {chat_id}")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Створити гру для компанії", callback_data="create_company_lottery")],
        [InlineKeyboardButton(text="📜 Правила та умови лотереї для компанії", callback_data="company_lottery_rules")],
        [InlineKeyboardButton(text="📜 Історія лотерей компанії", callback_data="history_company_lottery_dates_from_company_lottery")],  # Додаємо контекст
        [InlineKeyboardButton(text="📜 Активні лотереї", callback_data="active_company_lotteries_1")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]  # Змінено на "play"
    ])

    # Видаляємо поточне повідомлення
    try:
        await callback.message.delete()
        logger.info(f"Deleted current message {callback.message.message_id} for user {user_id}")
    except TelegramBadRequest as e:
        logger.warning(f"Failed to delete current message {callback.message.message_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while deleting current message {callback.message.message_id}: {str(e)}")

    # Відправляємо нове повідомлення
    try:
        sent_message = await bot.send_message(chat_id, "🏢 Лотерея компанією:", reply_markup=markup)
        logger.info(f"Sent new message with id {sent_message.message_id} for user {user_id}")
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except TelegramBadRequest as e:
        logger.error(f"Failed to send new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except Exception as e:
        logger.error(f"Unexpected error while sending new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

    await callback.answer()

@router.callback_query(lambda c: c.data == "company_lottery_menu")
async def company_lottery_menu_back(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"User {user_id} returning to play menu from company_lottery")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Лотерея компанією", callback_data="company_lottery")],
        [InlineKeyboardButton(text="🎰 Турнір", callback_data="tournament")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

    # Видаляємо поточне повідомлення
    try:
        await callback.message.delete()
        logger.info(f"Deleted current message {callback.message.message_id} for user {user_id}")
    except TelegramBadRequest as e:
        logger.warning(f"Failed to delete current message {callback.message.message_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while deleting current message {callback.message.message_id}: {str(e)}")

    # Відправляємо нове повідомлення
    try:
        sent_message = await bot.send_message(chat_id, "🎮 Оберіть тип гри:", reply_markup=markup)
        logger.info(f"Sent new message with id {sent_message.message_id} for user {user_id}")
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except TelegramBadRequest as e:
        logger.error(f"Failed to send new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except Exception as e:
        logger.error(f"Unexpected error while sending new message for user {user_id}: {str(e)}")
        sent_message = await bot.send_message(chat_id, "❌ Виникла помилка. Спробуйте ще раз.", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

    await callback.answer()

@router.callback_query(lambda c: c.data == "company_lottery_rules")
async def company_lottery_rules(callback: CallbackQuery):
    message = (
        "📜 **Правила та умови лотереї для компанії**\n\n"
        "1. Лотерея для компанії дозволяє створювати групові лотереї з 5 до 20 учасників.\n"
        "2. Творець лотереї обирає кількість учасників, бюджет, кількість переможців і рівень ризику.\n"
        "3. Учасники приєднуються за посиланням, купують білети, і коли збирається потрібна кількість учасників, пул ділиться між переможцями.\n"
        "4. Пул ділиться порівну між обраною кількістю переможців.\n"
        "5. Творець може скасувати лотерею в будь-який момент, і кошти повертаються учасникам.\n"
        "6. Учасники можуть відмовитися від участі, і їхні кошти повертаються без комісії."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "create_company_lottery")
async def create_company_lottery(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Entering create_company_lottery for user {user_id}, chat_id {chat_id}")

    try:
        logger.info(f"Connecting to database to fetch balance for user {user_id}")
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        logger.info(f"Fetching balance for user {user_id}")
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = c.fetchone()[0]
        logger.info(f"User {user_id} balance: {balance}")
        if balance < 5:
            logger.info(f"User {user_id} balance too low for creating lottery: {balance}")
            await callback.message.edit_text(
                f"❌ Ваш баланс ({balance} USDC) замалий для створення лотереї. Мінімальний баланс — 5 USDC.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
                ])
            )
            await callback.answer()
            conn.close()
            return
        logger.info(f"User {user_id} passed balance check, sending participant count prompt")
        participants_message = await callback.message.edit_text(
            "🎯 Створення гри для компанії\n\nВкажіть кількість учасників (від 5 до 20):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        logger.info(f"Setting state to CompanyLotteryCreation.waiting_for_participants for user {user_id}")
        await state.set_state(CompanyLotteryCreation.waiting_for_participants)
        await state.update_data(participants_message_id=participants_message.message_id)
        current_state = await state.get_state()
        logger.info(f"Current state for user {user_id} after setting: {current_state}")
        conn.close()
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in create_company_lottery for user {user_id}: {str(e)}")
        await callback.message.edit_text(
            "❌ Помилка при створенні гри для компанії. Спробуйте ще раз пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await callback.answer()
        if 'conn' in locals():
            conn.close()

@router.message(CompanyLotteryStates.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = message.text.strip()
    logger.info(f"User {user_id} entered username: {username}")

    user_data = await state.get_data()
    lottery_id = user_data.get("lottery_id")
    if not lottery_id:
        await message.answer(
            "❌ Помилка: ID лотереї не вказано. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        await state.clear()
        return

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT participant_count, budget_level, status FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
    lottery = c.fetchone()
    if not lottery:
        await message.answer(
            "❌ Лотерея не знайдена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        conn.close()
        await state.clear()
        return

    participant_count, budget_level, status = lottery
    if status != "pending":
        await message.answer(
            "❌ Лотерея вже завершена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        conn.close()
        await state.clear()
        return

    c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
    current_participants = c.fetchone()[0]
    if current_participants >= participant_count:
        await message.answer(
            "❌ Лотерея вже набрала потрібну кількість учасників.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        conn.close()
        await state.clear()
        return

    await state.update_data(username=username)
    sums = {
        "5_10_20": (5, 10, 20),
        "10_20_40": (10, 20, 40),
        "20_40_80": (20, 40, 80),
        "50_100_200": (50, 100, 200)
    }
    level_sums = sums[budget_level]
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{level_sums[0]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[0]}")],
        [InlineKeyboardButton(text=f"{level_sums[1]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[1]}")],
        [InlineKeyboardButton(text=f"{level_sums[2]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[2]}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_join_{lottery_id}")]
    ])
    await message.answer(
        f"Оберіть суму квитка (Рівень {budget_level.replace('_', '/')}$):",
        reply_markup=markup
    )
    await state.set_state(CompanyLotteryStates.waiting_for_confirmation)
    conn.close()

@router.callback_query(lambda c: c.data == "big_game")
async def big_game(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_active, time_status = get_big_game_status()
    if not is_active:
        await callback.message.edit_text(
            f"🎮 Велика гра\n\n{time_status}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
            ])
        )
        await callback.answer()
        return
    participants_5_20 = count_big_game_participants("5_10_20")
    participants_20_100 = count_big_game_participants("20_50_100")
    participants_70_300 = count_big_game_participants("70_150_300")
    message = (
        f"🎮 Велика гра\n\n"
        f"Час: {time_status}\n\n"
        f"Кількість учасників:\n"
        f"Рівень 5$/10$/20$: {participants_5_20}\n"
        f"Рівень 20$/50$/100$: {participants_20_100}\n"
        f"Рівень 70$/150$/300$: {participants_70_300}\n\n"
        f"Умови:\n"
        f"- Набір учасників триває 45 хвилин кожної години.\n"
        f"- Якщо зібрано 20-100 учасників: виграють 49% учасників (рандомно).\n"
        f"- Якщо зібрано <20 учасників: лотерея не починається, кошти повертаються.\n"
        f"- Якщо зібрано >100 учасників: 20% учасників виграють (рандомно).\n"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Погодитись та брати участь у лотереї", callback_data="big_game_agree")],
        [InlineKeyboardButton(text="❌ Не погоджуюсь", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "big_game_agree")
async def big_game_agree(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.set_state(BigGameStates.waiting_for_budget)
    message = "🎮 Вам треба обрати рівень бюджету, з яким ви готові брати участь:"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5$, 10$, 20$", callback_data="big_game_budget_5_10_20")],
        [InlineKeyboardButton(text="20$, 50$, 100$", callback_data="big_game_budget_20_50_100")],
        [InlineKeyboardButton(text="70$, 150$, 300$", callback_data="big_game_budget_70_150_300")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="big_game")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("big_game_budget_"))
async def big_game_budget(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    budget_level = callback.data.replace("big_game_budget_", "")
    await state.set_state(BigGameStates.waiting_for_ticket_purchase)
    sums = {
        "5_10_20": (5, 10, 20),
        "20_50_100": (20, 50, 100),
        "70_150_300": (70, 150, 300)
    }
    level_sums = sums[budget_level]
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{level_sums[0]}$", callback_data=f"big_game_ticket_{budget_level}_{level_sums[0]}")],
        [InlineKeyboardButton(text=f"{level_sums[1]}$", callback_data=f"big_game_ticket_{budget_level}_{level_sums[1]}")],
        [InlineKeyboardButton(text=f"{level_sums[2]}$", callback_data=f"big_game_ticket_{budget_level}_{level_sums[2]}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="big_game")]
    ])
    await callback.message.edit_text(f"Оберіть суму квитка (Рівень {budget_level.replace('_', '/')}):", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("big_game_ticket_"))
async def big_game_ticket(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data.split("_")
    budget_level = f"{data[3]}_{data[4]}_{data[5]}"
    ticket_price = float(data[6])
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    if balance < ticket_price:
        await callback.message.edit_text(
            f"❌ Недостатньо коштів для покупки квитка!\nВаш баланс: {balance} USDC, ціна квитка: {ticket_price} USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Поповнити баланс", url=DEPOSIT_URL)],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"big_game_budget_{budget_level}")]
            ])
        )
        await callback.answer()
        conn.close()
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"confirm_big_game_{budget_level}_{ticket_price}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"big_game_budget_{budget_level}")]
    ])
    await callback.message.edit_text(f"Ви обрали суму {ticket_price} USDC. Підтвердити транзакцію?", reply_markup=markup)
    await state.set_state(BigGameStates.waiting_for_confirmation)
    await state.update_data(budget_level=budget_level, ticket_price=ticket_price)
    conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("confirm_big_game_"))
async def confirm_big_game(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Received callback_data in confirm_big_game: {callback.data}")  # Додаємо логування
    data = callback.data.split("_")
    
    # Перевіряємо, чи достатньо елементів у callback.data
    if len(data) != 7:  # Очікуємо 7 частин: "confirm_big_game_<budget_level>_<ticket_price>"
        logger.error(f"Invalid callback_data format: {callback.data}, expected 7 parts but got {len(data)}")
        await callback.message.edit_text(
            "❌ Помилка: неправильний формат даних. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        return

    budget_level = f"{data[3]}_{data[4]}_{data[5]}"
    ticket_price = float(data[6])
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    active_tickets = count_active_tickets(user_id)
    active_big_game_tickets = count_active_big_game_tickets(user_id, budget_level)

    if active_tickets >= 3:
        await callback.message.edit_text(
            "❌ Ви досягли ліміту в 3 активних квитки. Зачекайте, поки один із квитків завершиться (виграш/програш), щоб придбати новий.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return
    if active_big_game_tickets >= 3:
        await callback.message.edit_text(
            f"❌ Ви досягли ліміту в 3 квитки для цього рівня ({budget_level.replace('_', '/')}$).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return
    if balance < ticket_price:
        await callback.message.edit_text(
            f"❌ Недостатньо коштів для покупки квитка!\nВаш баланс: {balance} USDC, ціна квитка: {ticket_price} USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Поповнити баланс", url=DEPOSIT_URL)],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return

    try:
        logger.info(f"Confirming big game ticket for user {user_id}, budget_level={budget_level}, ticket_price={ticket_price}")
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (ticket_price, user_id))
        tx_hash = send_transaction(BOT_ADDRESS, BOT_ADDRESS, ticket_price, PRIVATE_KEY)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        c.execute("INSERT INTO big_game_participants (user_id, budget_level, ticket_price, status, timestamp, tx_hash) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, budget_level, ticket_price, "active", timestamp, tx_hash))
        c.execute("INSERT INTO big_game_history (user_id, budget_level, ticket_price, status, winnings, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, budget_level, ticket_price, "active", 0.0, timestamp))
        conn.commit()
        await callback.message.edit_text(
            f"✅ Квиток придбано успішно!\nСума: {ticket_price} USDC\nРівень: {budget_level.replace('_', '/')} USDC\n\nДочекайтеся закінчення набору учасників або скасуйте квиток у 'Історія' -> 'Очікують'.\nТранзакція: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash}</a>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ]),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        conn.rollback()
        conn.close()
        await callback.message.edit_text(
            f"❌ Помилка при покупці квитка: {str(e)}. Спробуйте ще раз пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data=f"big_game_budget_{budget_level}")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == "tournaments")
async def tournaments(callback: CallbackQuery, state: FSMContext):
    message = (
        "🏆 **Турніри**\n\n"
        "Умови:\n"
        "- Оберіть рівень ризику (33%, 20%, 10% виграш).\n"
        "- Виберіть кількість учасників (50 або 100).\n"
        "- Придбайте квиток і чекайте, поки збереться потрібна кількість учасників.\n"
        "- Виграш залежить від рівня ризику: пул розподіляється між обраним відсотком переможців.\n"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Погодитись", callback_data="tournaments_agree")],
        [InlineKeyboardButton(text="❌ Відмовитись", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "tournaments_agree")
async def tournaments_agree(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TournamentStates.waiting_for_risk_level)
    message = "🏆 Оберіть рівень ризику, з яким ви хочете почати лотерею:"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="33% виграш", callback_data="tournament_risk_33")],
        [InlineKeyboardButton(text="20% виграш", callback_data="tournament_risk_20")],
        [InlineKeyboardButton(text="10% виграш", callback_data="tournament_risk_10")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tournaments")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("tournament_risk_"))
async def tournament_risk_level(callback: CallbackQuery, state: FSMContext):
    risk_level = callback.data.split("_")[-1]
    await state.update_data(risk_level=risk_level)
    await state.set_state(TournamentStates.waiting_for_participants)
    message = "🏆 Оберіть кількість учасників для турніру:"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50 учасників", callback_data="tournament_participants_50")],
        [InlineKeyboardButton(text="100 учасників", callback_data="tournament_participants_100")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tournaments_agree")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("tournament_participants_"))
async def tournament_participants(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id  # Додаємо визначення user_id
    participant_count = int(callback.data.split("_")[-1])
    user_data = await state.get_data()
    risk_level = user_data.get("risk_level")
    await state.update_data(participant_count=participant_count)
    await state.set_state(TournamentStates.waiting_for_room_selection)

    # Отримуємо або створюємо турніри для трьох "кімнат"
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    rooms = []
    ticket_price_options = "3_7_15"  # Фіксовані ціни квитків для всіх "кімнат"

    for room_number in range(1, 4):
        # Перевіряємо, чи існує турнір для цієї "кімнати"
        c.execute("SELECT tournament_id FROM tournaments WHERE risk_level = ? AND participant_count = ? AND ticket_price_options = ? AND status = 'pending' LIMIT 1",
                  (risk_level, participant_count, ticket_price_options))
        tournament = c.fetchone()
        if tournament:
            tournament_id = tournament[0]
        else:
            # Створюємо новий турнір для "кімнати"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO tournaments (creator_id, participant_count, risk_level, ticket_price_options, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                      (user_id, participant_count, risk_level, ticket_price_options, "pending", timestamp))
            tournament_id = c.lastrowid
            conn.commit()

        # Підраховуємо учасників для цього турніру
        participants = count_tournament_participants(tournament_id)
        rooms.append((tournament_id, participants))

    message = "🏆 Оберіть турнір для участі:"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Зібрано {min(rooms[0][1], participant_count)}/{participant_count} учасників", callback_data=f"tournament_room_{rooms[0][0]}")],
        [InlineKeyboardButton(text=f"Зібрано {min(rooms[1][1], participant_count)}/{participant_count} учасників", callback_data=f"tournament_room_{rooms[1][0]}")],
        [InlineKeyboardButton(text=f"Зібрано {min(rooms[2][1], participant_count)}/{participant_count} учасників", callback_data=f"tournament_room_{rooms[2][0]}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tournaments_agree")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("tournament_room_"))
async def tournament_room_selection(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    risk_level = user_data.get("risk_level")
    participant_count = user_data.get("participant_count")
    tournament_id = int(callback.data.split("_")[-1])
    await state.set_state(TournamentStates.waiting_for_ticket_purchase)
    await state.update_data(tournament_id=tournament_id)
    message = "🏆 Оберіть суму квитка для участі у турнірі:"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3$", callback_data=f"tournament_ticket_{tournament_id}_3")],
        [InlineKeyboardButton(text="7$", callback_data=f"tournament_ticket_{tournament_id}_7")],
        [InlineKeyboardButton(text="15$", callback_data=f"tournament_ticket_{tournament_id}_15")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tournaments_agree")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("tournament_ticket_"))
async def tournament_purchase_ticket(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data.split("_")
    tournament_id = int(data[2])
    ticket_price = float(data[3])
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    if balance < ticket_price:
        await callback.message.edit_text(
            f"❌ Недостатньо коштів для покупки квитка!\nВаш баланс: {balance} USDC, ціна квитка: {ticket_price} USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data="tournaments_agree")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"confirm_tournament_{tournament_id}_{ticket_price}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tournaments_agree")]
    ])
    await callback.message.edit_text(f"Ви обрали суму {ticket_price} USDC. Підтвердити транзакцію?", reply_markup=markup)
    await state.update_data(ticket_price=ticket_price)
    await state.set_state(TournamentStates.waiting_for_confirmation)
    conn.close()

@router.callback_query(lambda c: c.data.startswith("confirm_tournament_"))
async def confirm_tournament_ticket(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data.split("_")
    tournament_id = int(data[2])
    ticket_price = float(data[3])

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    active_tournament_tickets = count_active_tournament_tickets(user_id)
    same_tournament_tickets = count_tournament_tickets_by_params(user_id, tournament_id, ticket_price)

    if active_tournament_tickets >= 5:
        await callback.message.edit_text(
            "❌ Ви досягли ліміту в 5 активних квитків у турнірах загалом. Зачекайте, поки один із квитків завершиться (виграш/програш), щоб придбати новий.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return
    if same_tournament_tickets >= 3:
        await callback.message.edit_text(
            f"❌ Ви досягли ліміту в 3 квитки для цього турніру (ID: {tournament_id}, ціна: ${ticket_price}).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return
    if balance < ticket_price:
        await callback.message.edit_text(
            f"❌ Недостатньо коштів для покупки квитка!\nВаш баланс: {balance} USDC, ціна квитка: {ticket_price} USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data="tournaments_agree")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        conn.close()
        return

    try:
        logger.info(f"Confirming tournament ticket for user {user_id}, tournament_id={tournament_id}, ticket_price={ticket_price}")
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (ticket_price, user_id))
        tx_hash = send_transaction(BOT_ADDRESS, BOT_ADDRESS, ticket_price, PRIVATE_KEY)
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        c.execute("INSERT INTO tournament_participants (tournament_id, user_id, ticket_price, status, timestamp, tx_hash) VALUES (?, ?, ?, ?, ?, ?)",
                  (tournament_id, user_id, ticket_price, "active", timestamp, tx_hash))
        c.execute("INSERT INTO tournament_history (user_id, tournament_id, ticket_price, status, winnings, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, tournament_id, ticket_price, "active", 0.0, timestamp))
        conn.commit()
        await asyncio.sleep(2)

        # Отримуємо дані турніру
        c.execute("SELECT participant_count, risk_level FROM tournaments WHERE tournament_id = ?", (tournament_id,))
        tournament_data = c.fetchone()
        participant_count, risk_level = tournament_data
        participants = count_tournament_participants(tournament_id)

        if participants >= participant_count:
            # Турнір завершений, розподіляємо пул
            c.execute("SELECT user_id, ticket_price FROM tournament_participants WHERE tournament_id = ? AND status = 'active'", (tournament_id,))
            all_participants = c.fetchall()
            random.shuffle(all_participants)

            # Визначаємо кількість переможців
            winners_percentage = float(risk_level) / 100
            winners_count = max(1, int(participant_count * winners_percentage))
            winners = all_participants[:winners_count]

            # Розподіл пулу пропорційно вартості квитків
            total_pool = sum(participant[1] for participant in all_participants)
            total_winner_tickets = sum(winner[1] for winner in winners)
            coefficient = total_pool / total_winner_tickets if total_winner_tickets > 0 else 0

            for winner in winners:
                winner_id, winner_ticket_price = winner
                prize = winner_ticket_price * coefficient
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                if winner_id != BOT_ADDRESS:
                    send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize, PRIVATE_KEY)
                c.execute("UPDATE tournament_participants SET status = 'completed' WHERE tournament_id = ? AND user_id = ?", (tournament_id, winner_id))
                c.execute("UPDATE tournament_history SET status = 'won', winnings = ? WHERE tournament_id = ? AND user_id = ? AND status = 'active'",
                          (prize, tournament_id, winner_id))
                # Надсилаємо сповіщення переможцю
                try:
                    await bot.send_message(
                        winner_id,
                        f"🎉 Вітаємо! Ви виграли в турнірі {tournament_id}!\nВаш виграш: {prize} USDC\nВаш квиток: {winner_ticket_price} USDC\nТранзакція: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash}</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Failed to send win notification to user {winner_id}: {str(e)}")

            # Оновлюємо статус турніру та учасників, які програли
            c.execute("UPDATE tournaments SET status = 'completed' WHERE tournament_id = ?", (tournament_id,))
            c.execute("UPDATE tournament_participants SET status = 'lost' WHERE tournament_id = ? AND status = 'active'", (tournament_id,))
            c.execute("UPDATE tournament_history SET status = 'lost' WHERE tournament_id = ? AND status = 'active'", (tournament_id,))

            # Повідомлення користувачу
            c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            final_balance = c.fetchone()[0]
            if user_id in [winner[0] for winner in winners]:
                prize = ticket_price * coefficient
                result_message = (
                    f"🎉 Вітаємо! Ви виграли у Турнірі!\nРівень ризику: {risk_level}%\n"
                    f"Кількість учасників: {participant_count}\nВаш виграш: {prize:.2f} USDC\n"
                    f"Новий баланс: {final_balance:.2f} USDC\n"
                    f"Транзакція: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash}</a>"
                )
            else:
                result_message = (
                    f"😔 На жаль, ви не виграли у Турнірі.\nРівень ризику: {risk_level}%\n"
                    f"Кількість учасників: {participant_count}\nВаш баланс: {final_balance:.2f} USDC\n"
                    f"Транзакція: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash}</a>"
                )
            await callback.message.edit_text(
                result_message,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                ]),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            await callback.message.edit_text(
                f"✅ Квиток придбано успішно!\nСума: {ticket_price} USDC\nРівень ризику: {risk_level}%\n"
                f"Кількість учасників: {participants}/{participant_count}\n\nДочекайтеся, поки збереться потрібна кількість учасників або скасуйте квиток у 'Історія' -> 'Очікують'.\nТранзакція: <a href='https://arbiscan.io/tx/{tx_hash}'>{tx_hash}</a>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                ]),
                parse_mode="HTML",
                disable_web_page_preview=True
            )

    except Exception as e:
        conn.rollback()
        conn.close()
        await callback.message.edit_text(
            f"❌ Помилка при покупці квитка: {str(e)}. Спробуйте ще раз пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data="tournaments_agree")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
            ])
        )
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == "company_lottery")
async def company_lottery(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Set state to waiting_for_participants for user {user_id}")

    # Видаляємо попередні повідомлення
    if user_id in user_messages:
        await delete_deposit_messages(user_id, chat_id)

    # Видаляємо повідомлення "Оберіть тип гри"
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        logger.warning(f"Failed to delete 'Оберіть тип гри' message for user {user_id}: {str(e)}")

    await state.set_state(CompanyLotteryStates.waiting_for_participants)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Правила та умови лотереї для компанії", callback_data="company_rules")],
        [InlineKeyboardButton(text="📜 Активні лотереї", callback_data="active_company_lotteries_1")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="play")]
    ])
    sent_message = await bot.send_message(chat_id, "Вкажіть скільки учасників братимуть участь в лотереї (5-20):", reply_markup=markup)
    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    await callback.answer()

@router.callback_query(lambda c: c.data == "company_rules")
async def company_rules(callback: CallbackQuery):
    message = (
        "📜 **Правила та умови лотереї для компанії**\n\n"
        "1. Кількість учасників: від 3 до 50.\n"
        "2. Вибирається рівень ризику (10%, 20%, 33% виграш).\n"
        "3. Вибирається бюджет (5$/10$/20$, 20$/50$/100$, 75$/130$/200$, 200$/350$/500$).\n"
        "4. Організатор створює посилання для учасників.\n"
        "5. Учасники приєднуються через /start у іншому боті та купують квитки.\n"
        "6. Гра починається, коли зібрано потрібну кількість учасників, або організатор запускає її завчасно (/start_game).\n"
        "7. Виграш розподіляється між обраним відсотком переможців."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.message(CompanyLotteryStates.waiting_for_participants)
async def process_company_participants(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Processing company participants for user {user_id}, message: {message.text}")
    
    # Видаляємо попередні повідомлення
    if user_id in user_messages:
        await delete_deposit_messages(user_id, chat_id)
    
    # Видаляємо повідомлення з введеною цифрою
    try:
        await message.delete()
    except TelegramBadRequest as e:
        logger.warning(f"Failed to delete user input message for user {user_id}: {str(e)}")
    
    try:
        participant_count = int(message.text.strip())
        logger.info(f"User {user_id} entered participant_count: {participant_count}")
        if not 5 <= participant_count <= 20:  # Обмеження від 5 до 20
            logger.warning(f"Invalid participant_count {participant_count} for user {user_id}")
            sent_message = await message.answer(
                "❌ Кількість учасників повинна бути від 5 до 20. Введіть коректне число!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
                ])
            )
            await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
            return
        await state.update_data(participant_count=participant_count, creator_id=user_id)
        logger.info(f"Updated state for user {user_id} with participant_count: {participant_count}")
        
        # Запитуємо кількість переможців через кнопки
        winner_options = []
        if participant_count == 5:
            winner_options = [2, 3]
        elif participant_count == 6:
            winner_options = [2, 3, 4]
        elif participant_count == 7:
            winner_options = [2, 3, 4, 5]
        elif participant_count == 8:
            winner_options = [2, 3, 4, 5]
        elif participant_count == 9:
            winner_options = [2, 3, 4, 5, 6]
        elif participant_count == 10:
            winner_options = [2, 3, 4, 5, 6, 7]
        elif participant_count == 11:
            winner_options = [3, 4, 5, 6, 7]
        elif participant_count == 12:
            winner_options = [3, 4, 5, 6, 7, 8]
        elif participant_count == 13:
            winner_options = [3, 4, 5, 6, 7, 8]
        elif participant_count == 14:
            winner_options = [3, 4, 5, 6, 7, 8, 9]
        elif participant_count == 15:
            winner_options = [3, 4, 5, 6, 7, 8, 9, 10]
        elif participant_count == 16:
            winner_options = [3, 4, 5, 6, 7, 8, 9, 10]
        elif participant_count == 17:
            winner_options = [3, 4, 5, 6, 7, 8, 9, 10, 11]
        elif participant_count == 18:
            winner_options = [4, 5, 6, 7, 8, 9, 10, 11, 12]
        elif participant_count == 19:
            winner_options = [4, 5, 6, 7, 8, 9, 10, 11, 12]
        elif participant_count == 20:
            winner_options = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13]

        # Формуємо кнопки для вибору кількості переможців
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        row = []
        for count in winner_options:
            row.append(InlineKeyboardButton(text=str(count), callback_data=f"company_winners_{count}"))
            if len(row) == 3:  # По 3 кнопки в рядку
                markup.inline_keyboard.append(row)
                row = []
        if row:
            markup.inline_keyboard.append(row)
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")])
        
        logger.info(f"Displaying winner options for user {user_id}: {winner_options}")
        await state.set_state(CompanyLotteryStates.waiting_for_winners)
        sent_message = await message.answer(f"Оберіть кількість переможців для лотереї з {participant_count} учасників:", reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except ValueError:
        logger.warning(f"Invalid input for participant_count by user {user_id}: {message.text}")
        sent_message = await message.answer(
            "❌ Введено некоректне значення. Вкажіть число від 5 до 20!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
            ])
        )
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

@router.callback_query(lambda c: c.data.startswith("company_winners_"))
async def process_company_winners(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Processing company winners for user {user_id}, callback data: {callback.data}")
    
    # Видаляємо попередні повідомлення
    if user_id in user_messages:
        await delete_deposit_messages(user_id, chat_id)
    
    winner_count = int(callback.data.split("_")[-1])
    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    logger.info(f"User {user_id} selected winner_count: {winner_count}, participant_count: {participant_count}")
    
    # Перевіряємо, чи обрана кількість переможців відповідає діапазону
    valid_winner_count = False
    if participant_count == 5 and 2 <= winner_count <= 3:
        valid_winner_count = True
    elif participant_count == 6 and 2 <= winner_count <= 4:
        valid_winner_count = True
    elif participant_count == 7 and 2 <= winner_count <= 5:
        valid_winner_count = True
    elif participant_count == 8 and 2 <= winner_count <= 5:
        valid_winner_count = True
    elif participant_count == 9 and 2 <= winner_count <= 6:
        valid_winner_count = True
    elif participant_count == 10 and 2 <= winner_count <= 7:
        valid_winner_count = True
    elif participant_count == 11 and 3 <= winner_count <= 7:
        valid_winner_count = True
    elif participant_count == 12 and 3 <= winner_count <= 8:
        valid_winner_count = True
    elif participant_count == 13 and 3 <= winner_count <= 8:
        valid_winner_count = True
    elif participant_count == 14 and 3 <= winner_count <= 9:
        valid_winner_count = True
    elif participant_count == 15 and 3 <= winner_count <= 10:
        valid_winner_count = True
    elif participant_count == 16 and 3 <= winner_count <= 10:
        valid_winner_count = True
    elif participant_count == 17 and 3 <= winner_count <= 11:
        valid_winner_count = True
    elif participant_count == 18 and 4 <= winner_count <= 12:
        valid_winner_count = True
    elif participant_count == 19 and 4 <= winner_count <= 12:
        valid_winner_count = True
    elif participant_count == 20 and 4 <= winner_count <= 13:
        valid_winner_count = True

    if not valid_winner_count:
        logger.warning(f"Invalid winner_count {winner_count} for participant_count {participant_count} by user {user_id}")
        sent_message = await callback.message.answer(
            "❌ Обрана кількість переможців не відповідає діапазону. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
            ])
        )
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        await callback.answer()
        return

    await state.update_data(winner_count=winner_count)
    logger.info(f"Updated state for user {user_id} with winner_count: {winner_count}")
    await state.set_state(CompanyLotteryStates.waiting_for_risk)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5$, 10$, 20$", callback_data="company_budget_5_10_20")],
        [InlineKeyboardButton(text="20$, 50$, 100$", callback_data="company_budget_20_50_100")],
        [InlineKeyboardButton(text="75$, 130$, 200$", callback_data="company_budget_75_130_200")],
        [InlineKeyboardButton(text="200$, 350$, 500$", callback_data="company_budget_200_350_500")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
    ])
    sent_message = await callback.message.answer("Оберіть рівень бюджету для лотереї:", reply_markup=markup)
    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("company_risk_"))
async def process_company_risk(callback: CallbackQuery, state: FSMContext):
    risk_level = callback.data.split("_")[-1]
    await state.update_data(risk_level=risk_level)
    await state.set_state(CompanyLotteryStates.waiting_for_budget)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5$, 10$, 20$", callback_data="company_budget_5_10_20")],
        [InlineKeyboardButton(text="20$, 50$, 100$", callback_data="company_budget_20_50_100")],
        [InlineKeyboardButton(text="75$, 130$, 200$", callback_data="company_budget_75_130_200")],
        [InlineKeyboardButton(text="200$, 350$, 500$", callback_data="company_budget_200_350_500")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")]
    ])
    await callback.message.edit_text("Оберіть рівень бюджету для лотереї:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("company_budget_"))
async def process_company_budget(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    budget_level = callback.data.split("_")[-3] + "_" + callback.data.split("_")[-2] + "_" + callback.data.split("_")[-1]
    user_data = await state.get_data()
    participant_count = user_data.get("participant_count")
    winner_count = user_data.get("winner_count")
    creator_id = user_data.get("creator_id")
    
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("INSERT INTO company_lottery (creator_id, participant_count, budget_level, status, timestamp, winner_count) VALUES (?, ?, ?, ?, ?, ?)",
              (creator_id, participant_count, budget_level, "pending", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), winner_count))
    conn.commit()
    c.execute("SELECT last_insert_rowid()")
    lottery_id = c.fetchone()[0]
    conn.close()

    link = generate_lottery_link(lottery_id)
    logger.info(f"Generated lottery link for lottery_id {lottery_id}: {link}")
    await state.update_data(lottery_id=lottery_id)
    
    # Видаляємо попередні повідомлення через 5 секунд
    if user_id in user_messages:
        await delete_deposit_messages(user_id, chat_id, delay=5)

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main_with_lottery_message")]
    ])
    sent_message = await callback.message.answer(
        f"Лотерея створена!\nПосилання для учасників: {link}\n\nНадішліть це посилання своїй компанії. "
        f"Учасники повинні перейти за посиланням, натиснути /start, погодитися з умовами та обрати суму квитка. "
        f"Гра розпочнеться, коли збереться {participant_count} учасників, або ви можете запустити її завчасно командою /start_game.",
        reply_markup=markup
    )
    await state.set_state(CompanyLotteryStates.waiting_for_confirmation)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("back_to_main_with_lottery_message"))
async def back_to_main_with_lottery_message(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    logger.info(f"Starting back_to_main_with_lottery_message for user {user_id}, chat_id {chat_id}")

    # Видаляємо повідомлення з посиланням
    try:
        await callback.message.delete()
        logger.info(f"Deleted lottery link message for user {user_id}, message_id: {callback.message.message_id}")
    except Exception as e:
        logger.warning(f"Failed to delete lottery link message for callback {callback.id}: {str(e)}")

    # Видаляємо всі попередні повідомлення
    if user_messages[user_id]:
        await delete_deposit_messages(user_id, chat_id)
    else:
        logger.info(f"No messages to delete for user {user_id}")

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📥 Депозит", callback_data="deposit")],
        [InlineKeyboardButton(text="📜 Історія", callback_data="history")],
        [InlineKeyboardButton(text="🎮 Грати", callback_data="play")],
        [InlineKeyboardButton(text="💸 Вивести", callback_data="withdraw")],
        [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
        [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="settings")],
        [InlineKeyboardButton(text="💬 Чат", callback_data="chat")]
    ])
    await bot.send_message(
        chat_id,
        "Ваше посилання і деталі створеної вами гри знаходиться в 'Грати - Лотерея для компанії - Активні лотереї'\n\nВітаємо на головній сторінці бота!",
        reply_markup=markup
    )
    logger.info(f"Finished back_to_main_with_lottery_message for user {user_id}")
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("active_company_lotteries_"))
async def active_company_lotteries(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data
    logger.info(f"Received callback.data in active_company_lotteries: {data}")

    try:
        # Коментуємо видалення повідомлень, щоб уникнути видалення поточного повідомлення
        # if user_id in user_messages:
        #     await delete_deposit_messages(user_id, chat_id)

        if data == "active_company_lotteries_1":
            # Показуємо список дат
            logger.info(f"Processing active_company_lotteries_1 for user {user_id}")
            conn = sqlite3.connect("lottery.db")
            c = conn.cursor()
            c.execute("SELECT timestamp FROM company_lottery WHERE creator_id = ? AND status = 'pending'", (user_id,))
            timestamps = [row[0] for row in c.fetchall()]
            logger.info(f"All timestamps from company_lottery for user {user_id}: {timestamps}")

            # Логуємо всі записи для перевірки
            c.execute("SELECT timestamp, status FROM company_lottery WHERE creator_id = ?", (user_id,))
            all_records = c.fetchall()
            logger.info(f"All records in company_lottery for user {user_id}: {all_records}")

            # Витягуємо дати вручну з timestamp
            dates = []
            for timestamp in timestamps:
                try:
                    date_part = timestamp.split(" ")[0]  # Беремо лише дату (YYYY-MM-DD)
                    dates.append(date_part)
                except Exception as e:
                    logger.error(f"Failed to parse timestamp {timestamp}: {str(e)}")
                    continue

            # Видаляємо дублікати і сортуємо
            dates = sorted(list(set(dates)), reverse=True)
            logger.info(f"Raw dates from company_lottery for user {user_id}: {dates}")
            # Конвертуємо формат дати для відображення в DD.MM.YYYY
            formatted_dates = []
            for date in dates:
                try:
                    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
                    formatted_dates.append(formatted_date)
                except ValueError as e:
                    logger.error(f"Failed to format date {date}: {str(e)}")
                    continue
            logger.info(f"Formatted dates for user {user_id}: {formatted_dates}")

            if not formatted_dates:
                message = "📜 Активні лотереї\n\nЗаписів не знайдено."
            else:
                message = "📜 Активні лотереї\n\nОберіть дату:"
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            for date in formatted_dates:
                date_callback = date.replace(".", "_")
                markup.inline_keyboard.append([InlineKeyboardButton(text=date, callback_data=f"active_company_lotteries_date_{date_callback}_1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")])

            try:
                logger.info(f"Editing message for user {user_id} to show active company lotteries dates")
                await callback.message.edit_text(message, reply_markup=markup)
                # Оновлюємо user_messages з тим самим message_id
                await manage_deposit_messages(user_id, chat_id, callback.message.message_id)
            except Exception as e:
                logger.warning(f"Failed to edit message for user {user_id}: {str(e)}. Sending new message instead.")
                sent_message = await callback.message.answer(message, reply_markup=markup)
                await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

            conn.close()
        else:
            # Показуємо записи за обрану дату
            logger.info(f"Processing active_company_lotteries for specific date, data: {data}")
            parts = data.split("_")
            date = f"{parts[4]}.{parts[5]}.{parts[6]}"  # Конвертуємо назад у DD.MM.YYYY
            page = int(parts[7])  # Сторінка
            logger.info(f"Parsed date: {date}, page: {page}")

            conn = sqlite3.connect("lottery.db")
            c = conn.cursor()
            date_sql = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
            c.execute("SELECT lottery_id, participant_count, winner_count, budget_level, timestamp FROM company_lottery WHERE creator_id = ? AND SUBSTR(timestamp, 1, 10) = ? AND status = 'pending' ORDER BY timestamp DESC",
                      (user_id, date_sql))
            lotteries = c.fetchall()
            logger.info(f"Lotteries for user {user_id} on date {date}: {lotteries}")

            records_per_page = 5
            total_records = len(lotteries)
            total_pages = (total_records + records_per_page - 1) // records_per_page
            page = max(1, min(page, total_pages))

            start_idx = (page - 1) * records_per_page
            end_idx = start_idx + records_per_page
            page_lotteries = lotteries[start_idx:end_idx]

            if not lotteries:
                message = f"📜 Активні лотереї за {date}\n\nЗаписів не знайдено."
            else:
                message = f"📜 Активні лотереї за {date} (Сторінка {page}/{total_pages})\n\n"
                for lottery in page_lotteries:
                    lottery_id, participant_count, winner_count, budget_level, timestamp = lottery
                    formatted_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
                    link = generate_lottery_link(lottery_id)
                    c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
                    current_participants = c.fetchone()[0]
                    message += (
                        f"ID: {lottery_id} | Учасники: {current_participants}/{participant_count} | Переможці: {winner_count} | "
                        f"Бюджет: {budget_level.replace('_', '/')}$ | Дата: {formatted_timestamp}\n"
                        f"Посилання: {link}\n\n"
                    )

            markup = InlineKeyboardMarkup(inline_keyboard=[])
            date_callback = date.replace(".", "_")
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"active_company_lotteries_date_{date_callback}_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"active_company_lotteries_date_{date_callback}_{page+1}"))
            if nav_buttons:
                markup.inline_keyboard.append(nav_buttons)
            for lottery in page_lotteries:
                lottery_id = lottery[0]
                markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Видалити гру", callback_data=f"delete_company_lottery_{lottery_id}")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery")])

            try:
                logger.info(f"Editing message for user {user_id} to show active company lotteries for date {date}, page {page}")
                await callback.message.edit_text(message, reply_markup=markup)
                # Оновлюємо user_messages з тим самим message_id
                await manage_deposit_messages(user_id, chat_id, callback.message.message_id)
            except Exception as e:
                logger.warning(f"Failed to edit message for user {user_id}: {str(e)}. Sending new message instead.")
                sent_message = await callback.message.answer(message, reply_markup=markup)
                await manage_deposit_messages(user_id, chat_id, sent_message.message_id)

            conn.close()
    except Exception as e:
        logger.error(f"Error in active_company_lotteries for user {user_id}: {str(e)}")
        try:
            await callback.message.edit_text(
                "❌ Виникла помилка. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                ])
            )
        except Exception as edit_error:
            logger.warning(f"Failed to edit error message for user {user_id}: {str(edit_error)}. Sending new message instead.")
            sent_message = await callback.message.answer(
                "❌ Виникла помилка. Спробуйте ще раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", callback_data="back_to_main")]
                ])
            )
            await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("delete_company_lottery_"))
async def delete_company_lottery(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data
    lottery_id = int(data.split("_")[-1])

    # Видаляємо попередні повідомлення
    if user_id in user_messages:
        await delete_deposit_messages(user_id, chat_id)

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT participant_count, winner_count, budget_level, timestamp FROM company_lottery WHERE lottery_id = ? AND creator_id = ? AND status = 'pending'",
              (lottery_id, user_id))
    lottery = c.fetchone()
    if not lottery:
        message = "❌ Лотерея не знайдена або вже завершена."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="active_company_lotteries_1")]
        ])
        sent_message = await callback.message.answer(message, reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        conn.close()
        await callback.answer()
        return

    participant_count, winner_count, budget_level, timestamp = lottery
    formatted_timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
    message = (
        f"Ви впевнені, що хочете видалити цю лотерею?\n\n"
        f"ID: {lottery_id} | Учасники: {participant_count} | Переможці: {winner_count} | "
        f"Бюджет: {budget_level.replace('_', '/')}$ | Дата: {formatted_timestamp}\n\n"
        f"Усі кошти учасників будуть повернуті."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"confirm_delete_lottery_{lottery_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="active_company_lotteries_1")]
    ])
    sent_message = await callback.message.answer(message, reply_markup=markup)
    await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("confirm_delete_lottery_"))
async def confirm_delete_lottery(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data
    lottery_id = int(data.split("_")[-1])

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT creator_id FROM company_lottery WHERE lottery_id = ? AND status = 'pending'", (lottery_id,))
    lottery = c.fetchone()
    if not lottery or lottery[0] != user_id:
        message = "❌ Лотерея не знайдена або вже завершена."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="active_company_lotteries_1")]
        ])
        sent_message = await callback.message.answer(message, reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
        conn.close()
        await callback.answer()
        return

    try:
        # Повертаємо кошти учасникам
        c.execute("SELECT user_id, ticket_price FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
        participants = c.fetchall()
        for participant in participants:
            participant_id, ticket_price = participant
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ticket_price, participant_id))
            if participant_id != BOT_ADDRESS:
                send_transaction(BOT_ADDRESS, w3.to_checksum_address(participant_id), ticket_price, PRIVATE_KEY)
            try:
                await bot.send_message(
                    participant_id,
                    f"❌ Лотерея для компанії (ID: {lottery_id}) була скасована.\n"
                    f"Ваші кошти ({ticket_price} USDC) повернуто на баланс."
                )
            except Exception as e:
                logger.error(f"Failed to send refund notification to user {participant_id}: {str(e)}")
        # Видаляємо лотерею та учасників
        c.execute("UPDATE company_lottery SET status = 'cancelled' WHERE lottery_id = ?", (lottery_id,))
        c.execute("UPDATE company_lottery_participants SET status = 'cancelled' WHERE lottery_id = ?", (lottery_id,))
        conn.commit()

        message = "✅ Лотерея успішно видалена. Кошти повернуті учасникам."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="active_company_lotteries_1")]
        ])
        sent_message = await callback.message.answer(message, reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during lottery deletion: {str(e)}")
        message = f"❌ Помилка при видаленні лотереї: {str(e)}"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="active_company_lotteries_1")]
        ])
        sent_message = await callback.message.answer(message, reply_markup=markup)
        await manage_deposit_messages(user_id, chat_id, sent_message.message_id)
    finally:
        conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("join_lottery_"))
async def join_lottery(callback: CallbackQuery, state: FSMContext):
    lottery_id = int(callback.data.replace("join_lottery_", ""))
    user_id = callback.from_user.id
    user_data = await state.get_data()
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT budget_level FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
    budget_level = c.fetchone()[0]
    sums = {
        "5_10_20": (5, 10, 20),
        "20_50_100": (20, 50, 100),
        "75_130_200": (75, 130, 200),
        "200_350_500": (200, 350, 500)
    }
    level_sums = sums[budget_level]
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{level_sums[0]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[0]}")],
        [InlineKeyboardButton(text=f"{level_sums[1]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[1]}")],
        [InlineKeyboardButton(text=f"{level_sums[2]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[2]}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_join_{lottery_id}")]
    ])
    await callback.message.edit_text(f"Оберіть суму квитка (Рівень {budget_level.replace('_', '/')}$):", reply_markup=markup)
    await state.set_state(CompanyLotteryStates.waiting_for_confirmation)

@router.callback_query(lambda c: c.data.startswith("lottery_ticket_"))
async def purchase_company_ticket(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")
    lottery_id = int(data[2])
    ticket_price = float(data[3])
    user_id = callback.from_user.id
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    if balance < ticket_price:
        await callback.message.edit_text(
            f"❌ Недостатньо коштів для покупки квитка!\nВаш баланс: {balance} USDC, ціна квитка: {ticket_price} USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_join_{lottery_id}")]]
        ))
        await callback.answer()
        conn.close()
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"confirm_company_ticket_{lottery_id}_{ticket_price}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_join_{lottery_id}")]
    ])
    await callback.message.edit_text(f"Ви обрали суму {ticket_price} USDC. Підтвердити транзакцію?", reply_markup=markup)
    await state.update_data(ticket_price=ticket_price)

@router.callback_query(lambda c: c.data.startswith("confirm_company_ticket_"))
async def confirm_company_ticket(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data.split("_")
    lottery_id = int(data[3])
    ticket_price = float(data[4])
    
    # Отримуємо юзернейм зі стану
    user_data = await state.get_data()
    username = user_data.get("username")
    if not username:
        await callback.message.edit_text(
            "❌ Помилка: юзернейм не вказано. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        await callback.answer()
        return

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    active_tickets = count_active_tickets(user_id)
    if active_tickets >= 3:
        await callback.message.edit_text(
            "❌ Ви досягли ліміту в 3 активних квитки. Зачекайте, поки один із квитків завершиться (виграш/програш), щоб придбати новий.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Перейти в кабінет", callback_data="back_to_main")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        await callback.answer()
        conn.close()
        return
    if balance < ticket_price:
        await callback.message.edit_text(
            f"❌ Недостатньо коштів для покупки квитка!\nВаш баланс: {balance} USDC, ціна квитка: {ticket_price} USDC.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Поповнити баланс", url=DEPOSIT_URL)],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_join_{lottery_id}")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        await callback.answer()
        conn.close()
        return
    try:
        # Списуємо суму з балансу
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (ticket_price, user_id))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO company_lottery_participants (lottery_id, user_id, ticket_price, status, timestamp, username) VALUES (?, ?, ?, ?, ?, ?)",
                  (lottery_id, user_id, ticket_price, "active", timestamp, username))
        c.execute("SELECT last_insert_rowid()")
        participation_id = c.fetchone()[0]
        conn.commit()

        # Отримуємо кількість учасників
        c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
        current_participants = c.fetchone()[0]
        c.execute("SELECT participant_count, winner_count, risk_level, budget_level FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
        lottery_data = c.fetchone()
        participant_count, winner_count, risk_level, budget_level = lottery_data

        if current_participants >= participant_count:
            # Зібрано потрібну кількість учасників, розпочинаємо розіграш
            c.execute("SELECT user_id, ticket_price FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
            all_participants = c.fetchall()
            random.shuffle(all_participants)
            total_pool = sum(participant[1] for participant in all_participants)
            winners = all_participants[:winner_count]
            prize_per_winner = total_pool / winner_count if winner_count > 0 else 0

            for winner in winners:
                winner_id = winner[0]
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize_per_winner, winner_id))
                if winner_id != BOT_ADDRESS:
                    send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize_per_winner, PRIVATE_KEY)
                c.execute("UPDATE company_lottery_participants SET status = 'won' WHERE lottery_id = ? AND user_id = ?", (lottery_id, winner_id))
                try:
                    message = (
                        f"🎉 Вітаємо! Ви виграли в лотереї для компанії (ID: {lottery_id})!\n"
                        f"Ваш виграш: {prize_per_winner:.2f} USDC"
                    )
                    await bot.send_message(winner_id, message)
                except Exception as e:
                    logger.error(f"Failed to send win notification to user {winner_id}: {str(e)}")

            # Оновлюємо статус учасників, які програли
            losers = all_participants[winner_count:]
            for loser in losers:
                loser_id = loser[0]
                c.execute("UPDATE company_lottery_participants SET status = 'lost' WHERE lottery_id = ? AND user_id = ?", (lottery_id, loser_id))

            c.execute("UPDATE company_lottery SET status = 'completed' WHERE lottery_id = ?", (lottery_id,))
            conn.commit()

            await callback.message.edit_text(
                f"🎉 Лотерея для компанії (ID: {lottery_id}) завершена!\n"
                f"Пул розподілений між {winner_count} переможцями.\n"
                f"Сума виграшу на людину: {prize_per_winner:.2f} USDC",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📜 Історія", callback_data=f"company_lottery_history_{lottery_id}")],
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
                ])
            )
        else:
            # Показуємо повідомлення про успішну оплату
            await callback.message.edit_text(
                f"Вітаємо! Ви стали учасником лотереї для компанії з {participant_count} людей.\n"
                f"Наразі зібрано: {current_participants}/{participant_count} учасників.\n"
                f"Дочекайтеся, поки збереться потрібна кількість учасників.\n\n"
                f"Деталі гри доступні в 'Історія - Лотерея для компанії'.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Оновити статус", callback_data=f"update_lottery_status_{lottery_id}")],
                    [InlineKeyboardButton(text="📜 Історія", callback_data=f"company_lottery_history_{lottery_id}")],
                    [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
                ])
            )
    except Exception as e:
        conn.rollback()
        conn.close()
        await callback.message.edit_text(
            f"❌ Помилка при покупці квитка: {str(e)}. Спробуйте ще раз пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data=f"back_to_join_{lottery_id}")],
                [InlineKeyboardButton(text="⬅️ Перейти в кабінет", callback_data="back_to_main")],
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
    await state.clear()
    await callback.answer()

# ... (кінець confirm_company_ticket)

@router.callback_query(lambda c: c.data.startswith("company_lottery_history_"))
async def company_lottery_history(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    lottery_id = int(callback.data.split("_")[-1])

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT participant_count, budget_level, status, winner_count FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
    lottery = c.fetchone()
    if not lottery:
        await callback.message.edit_text(
            "❌ Лотерея не знайдена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ На головну сторінку", url=MAIN_BOT_URL)]
            ])
        )
        conn.close()
        await callback.answer()
        return

    participant_count, budget_level, status, winner_count = lottery
    c.execute("SELECT user_id, ticket_price, status, username FROM company_lottery_participants WHERE lottery_id = ?", (lottery_id,))
    participants = c.fetchall()

    message = f"📜 Історія лотереї для компанії (ID: {lottery_id})\n\n"
    message += f"Кількість учасників: {participant_count}\n"
    message += f"Кількість переможців: {winner_count}\n"
    message += f"Бюджет: {budget_level.replace('_', '/')} USDC\n"
    message += f"Статус: {status}\n\n"
    message += "Учасники:\n"
    for participant in participants:
        participant_id, ticket_price, participant_status, username = participant
        message += f"Юзернейм: {username if username else 'Невідомий'} | Квиток: {ticket_price} USDC | Статус: {participant_status}\n"

    markup = InlineKeyboardMarkup(inline_keyboard=[])
    if status == "pending":
        c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND user_id = ? AND status = 'active'", (lottery_id, user_id))
        if c.fetchone()[0] > 0:
            markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Відмовитись", callback_data=f"cancel_participation_{lottery_id}")])
    
    # Додаємо кнопку "📅 Переглянути за датами", яка веде до history_company_lottery_dates
    markup.inline_keyboard.append([InlineKeyboardButton(text="📅 Переглянути за датами", callback_data="history_company_lottery_dates")])
    
    # Змінюємо "⬅️ Назад", щоб вела до company_lottery_menu
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="company_lottery_menu")])

    await callback.message.edit_text(message, reply_markup=markup)
    conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("cancel_participation_"))
async def cancel_participation(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    lottery_id = int(callback.data.split("_")[-1])

    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT ticket_price FROM company_lottery_participants WHERE lottery_id = ? AND user_id = ? AND status = 'active'", (lottery_id, user_id))
    ticket = c.fetchone()
    if not ticket:
        await callback.message.edit_text(
            "❌ Ви не берете участі в цій лотереї або вона вже завершена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery_dates")]
            ])
        )
        conn.close()
        await callback.answer()
        return

    ticket_price = ticket[0]
    try:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ticket_price, user_id))
        if user_id != BOT_ADDRESS:
            send_transaction(BOT_ADDRESS, w3.to_checksum_address(user_id), ticket_price, PRIVATE_KEY)
        c.execute("UPDATE company_lottery_participants SET status = 'cancelled' WHERE lottery_id = ? AND user_id = ?", (lottery_id, user_id))
        conn.commit()
        message = (
            f"✅ Ви відмовилися від участі в лотереї (ID: {lottery_id}).\n"
            f"Ваші кошти ({ticket_price} USDC) повернуто на баланс."
        )
        await callback.message.edit_text(
            message,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery_dates")]
            ])
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Error cancelling participation for user {user_id}: {str(e)}")
        await callback.message.edit_text(
            f"❌ Помилка при відмові від участі: {str(e)}. Спробуйте ще раз пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="history_company_lottery_dates")]
            ])
        )
    finally:
        conn.close()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("back_to_join_"))
async def back_to_join(callback: CallbackQuery, state: FSMContext):
    lottery_id = int(callback.data.replace("back_to_join_", ""))
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT budget_level FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
    budget_level = c.fetchone()[0]
    sums = {
        "5_10_20": (5, 10, 20),
        "20_50_100": (20, 50, 100),
        "75_130_200": (75, 130, 200),
        "200_350_500": (200, 350, 500)
    }
    level_sums = sums[budget_level]
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{level_sums[0]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[0]}")],
        [InlineKeyboardButton(text=f"{level_sums[1]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[1]}")],
        [InlineKeyboardButton(text=f"{level_sums[2]}$", callback_data=f"lottery_ticket_{lottery_id}_{level_sums[2]}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_main")]
    ])
    await callback.message.edit_text(f"Оберіть суму квитка (Рівень {budget_level.replace('_', '/')}$):", reply_markup=markup)
    await callback.answer()

@router.message(Command(commands=["start_game"]))
async def start_game_early(message: Message, state: FSMContext):
    user_id = message.from_user.id
    conn = sqlite3.connect("lottery.db")
    c = conn.cursor()
    c.execute("SELECT lottery_id, participant_count FROM company_lottery WHERE creator_id = ? AND status = 'pending'", (user_id,))
    lottery = c.fetchone()
    if lottery:
        lottery_id, participant_count = lottery
        c.execute("SELECT COUNT(*) FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
        current_participants = c.fetchone()[0]
        if participant_count - current_participants <= 3:
            c.execute("UPDATE company_lottery SET status = 'active' WHERE lottery_id = ?", (lottery_id,))
            c.execute("SELECT risk_level FROM company_lottery WHERE lottery_id = ?", (lottery_id,))
            risk_level = c.fetchone()[0]
            winners_percentage = float(risk_level) / 100
            c.execute("SELECT user_id, ticket_price FROM company_lottery_participants WHERE lottery_id = ? AND status = 'active'", (lottery_id,))
            all_participants = c.fetchall()
            random.shuffle(all_participants)
            total_pool = sum(participant[1] for participant in all_participants)
            winners_count = max(1, int(len(all_participants) * winners_percentage))
            winners = all_participants[:winners_count]
            prize_per_winner = total_pool / winners_count if winners_count > 0 else 0
            for winner in winners:
                winner_id = winner[0]
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize_per_winner, winner_id))
                if winner_id != BOT_ADDRESS:  # Виключаємо бота з виграшу
                    send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize_per_winner, PRIVATE_KEY)
            c.execute("UPDATE company_lottery_participants SET status = 'completed' WHERE lottery_id = ?", (lottery_id,))
            conn.commit()
            conn.close()
            await message.answer(
                f"🎉 Лотерея розпочата завчасно! Виграш розподілено між {winners_count} переможцями.\n"
                f"Сума виграшу на людину: {prize_per_winner:.2f} USDC"
            )
        else:
            await message.answer("❌ Можна запустити гру завчасно лише якщо не вистачає 1-3 учасників.")
    else:
        await message.answer("❌ Ви не є організатором жодної активної лотереї.")
    conn.close()

@router.callback_query(lambda c: c.data == "help")
async def help_menu(callback: CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Правила та умови гри", callback_data="help_rules")],
        [InlineKeyboardButton(text="❓ Як грати", callback_data="help_how_to_play")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="help_faq")],
        [InlineKeyboardButton(text="ℹ️ Хто ми", callback_data="help_about")],
        [InlineKeyboardButton(text="💬 Підтримка", callback_data="help_support")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("❓ Оберіть розділ довідки:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "help_rules")
async def help_rules(callback: CallbackQuery):
    message = (
        "📜 **Правила та умови гри**\n\n"
        "1. Використовуй лише мережу Arbitrum для транзакцій.\n"
        "2. Усі операції проводяться в USDC.\n"
        "3. Ми не несемо відповідальності за помилки при введення адреси.\n"
        "4. У разі порушення правил твій акаунт може бути заблоковано.\n"
        "5. Усі виграші автоматично зараховуються на твій баланс."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "help_how_to_play")
async def help_how_to_play(callback: CallbackQuery):
    message = (
        "❓ **Як грати**\n\n"
        "1. Поповни баланс через 'Депозит'.\n"
        "2. Перейди в 'Грати' і обери тип гри (Велика гра, Турніри, Лотерея компанією).\n"
        "3. Придбай квиток і чекай на результати.\n"
        "4. Перевіряй виграші в 'Баланс' або 'Історія'."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "help_faq")
async def help_faq(callback: CallbackQuery):
    message = "❓ **FAQ**\n\nПитання будуть додані пізніше."
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "help_about")
async def help_about(callback: CallbackQuery):
    message = (
        "ℹ️ **Хто ми**\n\n"
        "Ми — команда ентузіастів, які створили цю платформу для любителів лотерей та криптовалют.\n"
        "Наша мета — зробити процес гри максимально простим, прозорим та безпечним."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "help_support")
async def help_support(callback: CallbackQuery):
    message = "💬 **Підтримка**\n\nЗвертайтесь до нас: @SupportBot"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help")]
    ])
    await callback.message.edit_text(message, reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "settings")
async def process_settings(callback: CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Мови", callback_data="settings_languages")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("⚙️ Налаштування:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "settings_languages")
async def settings_languages(callback: CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Українська", callback_data="language_uk")],
        [InlineKeyboardButton(text="English", callback_data="language_en")],
        [InlineKeyboardButton(text="Polski", callback_data="language_pl")],
        [InlineKeyboardButton(text="Deutsch", callback_data="language_de")],
        [InlineKeyboardButton(text="Español", callback_data="language_es")],
        [InlineKeyboardButton(text="Italiano", callback_data="language_it")],
        [InlineKeyboardButton(text="Français", callback_data="language_fr")],
        [InlineKeyboardButton(text="العربية", callback_data="language_ar")],
        [InlineKeyboardButton(text="Bahasa Indonesia", callback_data="language_id")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings")]
    ])
    await callback.message.edit_text("🌐 Оберіть мову:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("language_"))
async def set_language(callback: CallbackQuery):
    await callback.message.edit_text("🌐 Мова обрана (логіка ще не реалізована).", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings")]
    ]))
    await callback.answer()

async def check_pending_deposits():
    while True:
        try:
            conn = sqlite3.connect("lottery.db")
            c = conn.cursor()

            # Додаємо перевірку незавершених депозитів
            logger.info("Starting check_pending_deposits iteration for deposits")
            start_time = datetime.now()
            c.execute("SELECT deposit_id, user_id, amount, from_address, tx_hash, chat_id FROM deposits WHERE status = 'pending'", ())
            pending_deposits = c.fetchall()
            logger.info(f"Found {len(pending_deposits)} pending deposits")

            for deposit in pending_deposits:
                deposit_id, user_id, amount, from_address, tx_hash, chat_id = deposit
                logger.info(f"Checking deposit {deposit_id} for user {user_id}, tx_hash: {tx_hash}")
                try:
                    # Перевіряємо транзакцію з тайм-аутом
                    transaction_start = datetime.now()
                    try:
                        transaction_status = await asyncio.wait_for(
                            asyncio.to_thread(check_transaction_status, tx_hash),
                            timeout=5.0  # Тайм-аут 5 секунд
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout checking transaction {tx_hash} for deposit {deposit_id}")
                        continue  # Пропускаємо депозит, якщо перевірка займає надто багато часу
                    transaction_duration = (datetime.now() - transaction_start).total_seconds()
                    logger.info(f"Checked transaction {tx_hash} for deposit {deposit_id}, status: {transaction_status}, duration: {transaction_duration}s")

                    if transaction_status == "confirmed":
                        c.execute("UPDATE deposits SET status = 'completed', received_amount = ? WHERE deposit_id = ?", (amount, deposit_id))
                        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                        conn.commit()
                        logger.info(f"Deposit {deposit_id} confirmed for user {user_id}, amount: {amount}")
                        try:
                            await bot.send_message(chat_id, f"✅ Депозит на суму {amount} USDC успішно зараховано!")
                            logger.info(f"Sent confirmation message to user {user_id} for deposit {deposit_id}")
                        except Exception as e:
                            logger.error(f"Failed to send confirmation message to user {user_id}: {str(e)}")
                    elif transaction_status == "failed":
                        c.execute("UPDATE deposits SET status = 'failed' WHERE deposit_id = ?", (deposit_id,))
                        conn.commit()
                        logger.info(f"Deposit {deposit_id} failed for user {user_id}")
                        try:
                            await bot.send_message(chat_id, "❌ Депозит не вдалося обробити. Спробуйте ще раз.")
                            logger.info(f"Sent failure message to user {user_id} for deposit {deposit_id}")
                        except Exception as e:
                            logger.error(f"Failed to send failure message to user {user_id}: {str(e)}")
                except Exception as e:
                    logger.error(f"Error processing deposit {deposit_id} for user {user_id}: {str(e)}")

            # Зберігаємо існуючу логіку для "Big Game"
            logger.info("Checking Big Game status")
            is_active, time_status = get_big_game_status()
            if not is_active:
                budget_levels = ["5_10_20", "20_50_100", "70_150_300"]
                for budget_level in budget_levels:
                    participants = count_big_game_participants(budget_level)
                    if participants < 20:
                        c.execute("SELECT user_id, ticket_price FROM big_game_participants WHERE budget_level = ? AND status = 'active'", (budget_level,))
                        participants_to_refund = c.fetchall()
                        for user_id, ticket_price in participants_to_refund:
                            refund_amount = ticket_price
                            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
                            c.execute("UPDATE big_game_participants SET status = 'cancelled' WHERE user_id = ? AND budget_level = ? AND status = 'active'", (user_id, budget_level))
                            logger.info(f"Refunded {refund_amount} USDC to user {user_id} for big_game (budget_level: {budget_level}) due to insufficient participants")
                        conn.commit()
                    else:
                        winners_count = participants // 2 if participants <= 100 else participants // 5
                        c.execute("SELECT user_id, ticket_price FROM big_game_participants WHERE budget_level = ? AND status = 'active'", (budget_level,))
                        all_participants = c.fetchall()
                        random.shuffle(all_participants)
                        winners = all_participants[:winners_count]
                        total_pool = sum(participant[1] for participant in all_participants)
                        prize_per_winner = total_pool / winners_count if winners_count > 0 else 0
                        for winner in winners:
                            winner_id = winner[0]
                            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize_per_winner, winner_id))
                            if winner_id != BOT_ADDRESS:
                                send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize_per_winner, PRIVATE_KEY)
                        c.execute("UPDATE big_game_participants SET status = 'completed' WHERE budget_level = ? AND status = 'active'", (budget_level,))
                        conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error in check_pending_deposits: {e}")
            if 'conn' in locals():
                conn.close()
        finally:
            iteration_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Finished check_pending_deposits iteration, duration: {iteration_duration}s")
            await asyncio.sleep(60)

@router.message()
async def catch_all_messages(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Catch-all message handler triggered for user {user_id}, chat_id {chat_id}, message: {message.text}")
    
    # Отримуємо поточний стан
    try:
        current_state = await state.get_state()
        logger.info(f"Current state in catch_all_messages for user {user_id}: {current_state}")
    except Exception as e:
        logger.error(f"Error getting state in catch_all_messages for user {user_id}: {str(e)}")
        current_state = None

    # Пропускаємо обробку, якщо користувач у стані WithdrawalStates.waiting_for_address або CompanyLotteryCreation
    expected_states = [
        "WithdrawalStates:waiting_for_address",
        "CompanyLotteryCreation:waiting_for_participants",
        "CompanyLotteryCreation:waiting_for_budget",
        "CompanyLotteryCreation:waiting_for_winners",
        "CompanyLotteryCreation:waiting_for_risk",
        "CompanyLotteryCreation:waiting_for_confirmation",
        "CompanyLotteryStates:waiting_for_username"  # Додаємо новий стан
    ]
    logger.info(f"Comparing current_state '{current_state}' with expected states {expected_states}")
    if current_state in expected_states:
        logger.info(f"Skipping catch-all handler for user {user_id} in state {current_state}")
        return
    
    logger.info(f"Ignoring unexpected input from user {user_id}: {message.text}")
    try:
        await message.delete()
        logger.info(f"Deleted unexpected message from user {user_id}: {message.text}")
    except Exception as e:
        logger.error(f"Failed to delete unexpected message from user {user_id}: {str(e)}")

async def check_big_game_completion():
    while True:
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        is_active, time_status = get_big_game_status()
        if not is_active:
            # Перевіряємо всі бюджетні рівні
            budget_levels = ["5_10_20", "20_50_100", "70_150_300"]
            for budget_level in budget_levels:
                participants = count_big_game_participants(budget_level)
                if participants < 20:
                    # Повертаємо кошти всім учасникам
                    c.execute("SELECT user_id, ticket_price FROM big_game_participants WHERE budget_level = ? AND status = 'active'", (budget_level,))
                    participants_to_refund = c.fetchall()
                    for user_id, ticket_price in participants_to_refund:
                        refund_amount = ticket_price  # Повернення без комісії
                        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund_amount, user_id))
                        c.execute("UPDATE big_game_history SET status = 'cancelled', winnings = 0 WHERE user_id = ? AND budget_level = ? AND status = 'active'", (user_id, budget_level))
                        c.execute("UPDATE big_game_participants SET status = 'cancelled' WHERE user_id = ? AND budget_level = ? AND status = 'active'", (user_id, budget_level))
                        logger.info(f"Refunded {refund_amount} USDC to user {user_id} for big_game (budget_level: {budget_level}) due to insufficient participants")
                        # Надсилаємо сповіщення про повернення коштів
                        try:
                            c.execute("SELECT chat_id FROM deposits WHERE user_id = ? AND chat_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (user_id,))
                            chat_id = c.fetchone()
                            if chat_id:
                                chat_id = chat_id[0]
                                message = await bot.send_message(
                                    chat_id,
                                    f"❌ Набір учасників для 'Великої гри' (рівень: {budget_level.replace('_', '/')} USDC) завершено. Зібрано менше 20 учасників. Ваші кошти ({refund_amount} USDC) повернуто на баланс."
                                )
                                refund_notifications[user_id].append({
                                    'chat_id': chat_id,
                                    'message_id': message.message_id
                                })
                                asyncio.create_task(delete_refund_notification(user_id, chat_id))
                        except Exception as e:
                            logger.error(f"Failed to send refund notification to user {user_id}: {str(e)}")
                    conn.commit()
                else:
                    # Розподіл пулу
                    c.execute("SELECT user_id, ticket_price FROM big_game_participants WHERE budget_level = ? AND status = 'active'", (budget_level,))
                    all_participants = c.fetchall()
                    random.shuffle(all_participants)
                    total_pool = sum(participant[1] for participant in all_participants)

                    if participants < 100:
                        # Від 20 до 99 учасників: 50% переможців
                        winners_count = math.ceil(participants * 0.5)  # Заокруглення до більшого
                        winners = all_participants[:winners_count]
                        total_winner_tickets = sum(winner[1] for winner in winners)
                        coefficient = total_pool / total_winner_tickets if total_winner_tickets > 0 else 0

                        for winner in winners:
                            winner_id, winner_ticket_price = winner
                            prize = winner_ticket_price * coefficient
                            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                            if winner_id != BOT_ADDRESS:
                                send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize, PRIVATE_KEY)
                            c.execute("UPDATE big_game_history SET status = 'won', winnings = ? WHERE user_id = ? AND budget_level = ? AND status = 'active'",
                                      (prize, winner_id, budget_level))
                            # Надсилаємо сповіщення переможцю
                            try:
                                c.execute("SELECT chat_id FROM deposits WHERE user_id = ? AND chat_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (winner_id,))
                                chat_id = c.fetchone()
                                if chat_id:
                                    chat_id = chat_id[0]
                                    await bot.send_message(
                                        chat_id,
                                        f"🎉 Вітаємо! Ви виграли у 'Великій грі' (рівень: {budget_level.replace('_', '/')} USDC)!\nВаш виграш: {prize} USDC\nВаш квиток: {winner_ticket_price} USDC"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to send win notification to user {winner_id}: {str(e)}")

                        # Оновлюємо статус учасників, які програли
                        losers = all_participants[winners_count:]
                        for loser in losers:
                            loser_id = loser[0]
                            c.execute("UPDATE big_game_history SET status = 'lost', winnings = 0 WHERE user_id = ? AND budget_level = ? AND status = 'active'",
                                      (loser_id, budget_level))
                    else:
                        # 100+ учасників: залежно від ризику (10%, 20%, 33%)
                        risk_percentages = {"5_10_20": 10, "20_50_100": 20, "70_150_300": 33}
                        risk_percentage = risk_percentages[budget_level] / 100
                        winners_count = math.ceil(participants * risk_percentage)  # Заокруглення до більшого
                        winners = all_participants[:winners_count]

                        # Великий виграш: 20% переможців
                        big_winners_count = math.ceil(winners_count * 0.2)  # Заокруглення до більшого
                        big_winners = winners[:big_winners_count]
                        regular_winners = winners[big_winners_count:]

                        # Розподіл пулу
                        big_winners_pool = total_pool * 0.2  # 20% пулу для великого виграшу
                        regular_winners_pool = total_pool * 0.8  # 80% пулу для решти переможців

                        # Великий виграш
                        total_big_winner_tickets = sum(winner[1] for winner in big_winners)
                        big_coefficient = big_winners_pool / total_big_winner_tickets if total_big_winner_tickets > 0 else 0
                        for winner in big_winners:
                            winner_id, winner_ticket_price = winner
                            prize = winner_ticket_price * big_coefficient
                            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                            if winner_id != BOT_ADDRESS:
                                send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize, PRIVATE_KEY)
                            c.execute("UPDATE big_game_history SET status = 'won', winnings = ? WHERE user_id = ? AND budget_level = ? AND status = 'active'",
                                      (prize, winner_id, budget_level))
                            # Надсилаємо сповіщення про великий виграш
                            try:
                                c.execute("SELECT chat_id FROM deposits WHERE user_id = ? AND chat_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (winner_id,))
                                chat_id = c.fetchone()
                                if chat_id:
                                    chat_id = chat_id[0]
                                    await bot.send_message(
                                        chat_id,
                                        f"🎉 Вітаємо! Ви виграли ВЕЛИКИЙ ВИГРАШ у 'Великій грі' (рівень: {budget_level.replace('_', '/')} USDC)!\nВаш виграш: {prize} USDC\nВаш квиток: {winner_ticket_price} USDC"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to send big win notification to user {winner_id}: {str(e)}")

                        # Звичайний виграш
                        total_regular_winner_tickets = sum(winner[1] for winner in regular_winners)
                        regular_coefficient = regular_winners_pool / total_regular_winner_tickets if total_regular_winner_tickets > 0 else 0
                        for winner in regular_winners:
                            winner_id, winner_ticket_price = winner
                            prize = winner_ticket_price * regular_coefficient
                            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                            if winner_id != BOT_ADDRESS:
                                send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize, PRIVATE_KEY)
                            c.execute("UPDATE big_game_history SET status = 'won', winnings = ? WHERE user_id = ? AND budget_level = ? AND status = 'active'",
                                      (prize, winner_id, budget_level))
                            # Надсилаємо сповіщення про звичайний виграш
                            try:
                                c.execute("SELECT chat_id FROM deposits WHERE user_id = ? AND chat_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (winner_id,))
                                chat_id = c.fetchone()
                                if chat_id:
                                    chat_id = chat_id[0]
                                    await bot.send_message(
                                        chat_id,
                                        f"🎉 Вітаємо! Ви виграли у 'Великій грі' (рівень: {budget_level.replace('_', '/')} USDC)!\nВаш виграш: {prize} USDC\nВаш квиток: {winner_ticket_price} USDC"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to send win notification to user {winner_id}: {str(e)}")

                        # Оновлюємо статус учасників, які програли
                        losers = all_participants[winners_count:]
                        for loser in losers:
                            loser_id = loser[0]
                            c.execute("UPDATE big_game_history SET status = 'lost', winnings = 0 WHERE user_id = ? AND budget_level = ? AND status = 'active'",
                                      (loser_id, budget_level))

                    # Оновлюємо статус усіх учасників
                    c.execute("UPDATE big_game_participants SET status = 'completed' WHERE budget_level = ? AND status = 'active'", (budget_level,))
                    conn.commit()
        conn.close()
        await asyncio.sleep(60)  # Перевіряємо кожні 60 секунд

async def debug_all_updates(update):
    logger.info(f"Received update: {update}")

async def check_tournament_completion():
    while True:
        conn = sqlite3.connect("lottery.db")
        c = conn.cursor()
        c.execute("SELECT tournament_id, participant_count, risk_level FROM tournaments WHERE status = 'pending'", ())
        tournaments = c.fetchall()
        for tournament in tournaments:
            tournament_id, participant_count, risk_level = tournament
            current_participants = count_tournament_participants(tournament_id)
            if current_participants >= participant_count:
                # Турнір завершений, розподіляємо пул
                c.execute("SELECT user_id, ticket_price FROM tournament_participants WHERE tournament_id = ? AND status = 'active'", (tournament_id,))
                all_participants = c.fetchall()
                random.shuffle(all_participants)

                # Визначаємо кількість переможців
                winners_percentage = float(risk_level) / 100
                winners_count = max(1, int(participant_count * winners_percentage))
                winners = all_participants[:winners_count]

                # Розподіл пулу пропорційно вартості квитків
                total_pool = sum(participant[1] for participant in all_participants)
                total_winner_tickets = sum(winner[1] for winner in winners)
                coefficient = total_pool / total_winner_tickets if total_winner_tickets > 0 else 0

                for winner in winners:
                    winner_id, winner_ticket_price = winner
                    prize = winner_ticket_price * coefficient
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                    if winner_id != BOT_ADDRESS:
                        send_transaction(BOT_ADDRESS, w3.to_checksum_address(winner_id), prize, PRIVATE_KEY)
                    c.execute("UPDATE tournament_participants SET status = 'completed' WHERE tournament_id = ? AND user_id = ?", (tournament_id, winner_id))
                    c.execute("UPDATE tournament_history SET status = 'won', winnings = ? WHERE tournament_id = ? AND user_id = ? AND status = 'active'",
                              (prize, tournament_id, winner_id))
                    # Надсилаємо сповіщення переможцю
                    try:
                        await bot.send_message(
                            winner_id,
                            f"🎉 Вітаємо! Ви виграли в турнірі {tournament_id}!\nВаш виграш: {prize} USDC\nВаш квиток: {winner_ticket_price} USDC"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send win notification to user {winner_id}: {str(e)}")

                # Оновлюємо статус турніру та учасників, які програли
                c.execute("UPDATE tournaments SET status = 'completed' WHERE tournament_id = ?", (tournament_id,))
                c.execute("UPDATE tournament_participants SET status = 'lost' WHERE tournament_id = ? AND status = 'active'", (tournament_id,))
                c.execute("UPDATE tournament_history SET status = 'lost' WHERE tournament_id = ? AND status = 'active'", (tournament_id,))

        conn.commit()
        conn.close()
        await asyncio.sleep(60)  # Перевіряємо кожні 60 секунд

async def main():
    print("Starting main function...")
    init_db()
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(check_pending_deposits())
    asyncio.create_task(check_big_game_completion())
    asyncio.create_task(check_tournament_completion())  # Додаємо нову задачу
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())