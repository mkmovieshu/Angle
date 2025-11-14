# app/telegram/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from ..config import ADMIN_CONTACT_URL, PREMIUM_PLANS

def start_keyboard():
    kb = [
        [InlineKeyboardButton("Free Video 🎁", callback_data="free_video")],
        [InlineKeyboardButton("Subscribe (premium)", callback_data="subscribe")],
        [InlineKeyboardButton("Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

def ad_keyboard(redirect_url: str, token: str):
    kb = [
        [InlineKeyboardButton("Open Short Ad 🔗", url=redirect_url)],
        [InlineKeyboardButton("I watched the ad ✅", callback_data=f"ad_check:{token}")],
        [InlineKeyboardButton("Subscribe (no ads)", callback_data="subscribe")]
    ]
    return InlineKeyboardMarkup(kb)

def subscribe_menu():
    kb = []
    for key, info in PREMIUM_PLANS.items():
        kb.append([InlineKeyboardButton(f"{info['label']} — {info['price_label']}", callback_data=f"show_plans:{key}")])
    kb.append([InlineKeyboardButton("Contact Admin", url=ADMIN_CONTACT_URL)])
    return InlineKeyboardMarkup(kb)

def plan_contact_keyboard(plan_key: str):
    contact = ADMIN_CONTACT_URL or "https://t.me/your_admin"
    url = f"{contact}?plan={plan_key}"
    kb = [
        [InlineKeyboardButton("Contact Admin to Subscribe", url=url)],
        [InlineKeyboardButton("Back", callback_data="subscribe_back")]
    ]
    return InlineKeyboardMarkup(kb)
