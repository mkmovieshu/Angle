# app/telegram/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional

def free_video_nav(next_payload: str = "next_free"):
    """
    Inline keyboard shown under a FREE video while user still has free quota.
    next_payload - callback_data payload for next free video.
    """
    kb = [
        [InlineKeyboardButton("Next Free Video ▶", callback_data=next_payload)]
    ]
    return InlineKeyboardMarkup(kb)

def ad_prompt_buttons(token: Optional[str] = None, domain: str = ""):
    """
    Buttons shown after user exhausted FREE_LIMIT.
    - Watch Ad -> URL button (short link or ad provider link). If token provided and domain configured,
      we provide a redirect through our domain so we can detect returns: domain/ad/complete/<token>
    - Get Premium -> opens admin/contact or shows plan buttons (here open admin)
    """
    watch_url = None
    if token and domain:
        watch_url = f"{domain}/ad/redirect/{token}"
    elif token:
        watch_url = f"ad://{token}"

    kb = []
    row = []
    if watch_url:
        row.append(InlineKeyboardButton("▶ Watch Ad (Get next 5)", url=watch_url))
    else:
        # fallback: if no url possible, provide callback to create ad session
        row.append(InlineKeyboardButton("▶ Watch Ad (Get next 5)", callback_data=f"create_ad"))

    row.append(InlineKeyboardButton("💎 Get Premium", callback_data="get_premium"))
    kb.append(row)

    # small helper row to contact admin if needed (uses URL if admin is a t.me link or username)
    kb.append([InlineKeyboardButton("Contact Admin", url="https://t.me/" + (domain if domain.startswith("http") else "") )])  # placeholder; handlers will replace if needed
    return InlineKeyboardMarkup(kb)

def premium_plan_buttons(admin_contact: str = "@admin"):
    kb = [
        [InlineKeyboardButton("10 days - Buy", callback_data="buy_10")],
        [InlineKeyboardButton("20 days - Buy", callback_data="buy_20")],
        [InlineKeyboardButton("30 days - Buy", callback_data="buy_30")],
        [InlineKeyboardButton("Contact Admin", url=f"https://t.me/{admin_contact.lstrip('@')}")]
    ]
    return InlineKeyboardMarkup(kb)
