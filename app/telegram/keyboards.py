# app/telegram/keyboards.py
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def free_video_nav(next_payload: str = "next_free") -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("Next Free Video ▶", callback_data=next_payload)]
    ]
    return InlineKeyboardMarkup(kb)

def ad_prompt_buttons(token: Optional[str] = None, domain: str = "") -> InlineKeyboardMarkup:
    """
    Returns InlineKeyboardMarkup with a Watch Ad button (either URL redirect through domain
    or callback to create an ad session), + purchase/contact buttons.
    """
    watch_url = None
    if token and domain:
        watch_url = f"{domain.rstrip('/')}/ad/redirect/{token}"
    elif token:
        watch_url = f"ad://{token}"

    kb = []
    row = []
    if watch_url:
        row.append(InlineKeyboardButton("▶ Watch Ad (Get next 5)", url=watch_url))
    else:
        # fallback to a callback that creates an ad session server-side
        row.append(InlineKeyboardButton("▶ Watch Ad (Get next 5)", callback_data="create_ad"))

    row.append(InlineKeyboardButton("💎 Get Premium", callback_data="get_premium"))
    kb.append(row)

    # Contact admin row — leave a sensible default placeholder
    kb.append([InlineKeyboardButton("Contact Admin", url="https://t.me/YourAdminUsername")])
    return InlineKeyboardMarkup(kb)

def premium_plan_buttons(admin_contact: str = "@admin") -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("10 days - Buy", callback_data="buy_10")],
        [InlineKeyboardButton("20 days - Buy", callback_data="buy_20")],
        [InlineKeyboardButton("30 days - Buy", callback_data="buy_30")],
        [InlineKeyboardButton("Contact Admin", url=f"https://t.me/{admin_contact.lstrip('@')}")]
    ]
    return InlineKeyboardMarkup(kb)

def video_control_buttons(next_payload: str = "next_free", token_for_ad: Optional[str] = None, ad_short_url: Optional[str] = None):
    """
    Buttons shown under a sent video: next, watch ad, premium, contact.
    """
    kb = []
    row = [InlineKeyboardButton("Next ▶", callback_data=next_payload)]
    if token_for_ad:
        if ad_short_url:
            row.append(InlineKeyboardButton("Watch Ad", url=ad_short_url))
        else:
            row.append(InlineKeyboardButton("Watch Ad", callback_data=f"ad_check:{token_for_ad}"))
    kb.append(row)
    kb.append([InlineKeyboardButton("Get Premium", callback_data="get_premium")])
    return InlineKeyboardMarkup(kb)
