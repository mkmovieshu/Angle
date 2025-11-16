# app/telegram/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional

def video_control_buttons(token_for_ad: Optional[str] = None, ad_short_url: Optional[str] = None):
    """
    Inline keyboard shown under each video message.
    - Normal: Next Video | Free Count
              Buy Premium
    - If ad info provided: Watch Ad (url) | I Watched (callback)
                           Buy Premium
    """
    if token_for_ad and ad_short_url:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎥 Watch Ad", url=ad_short_url)],
            [InlineKeyboardButton("✔️ I Watched", callback_data=f"ad_check:{token_for_ad}")],
            [InlineKeyboardButton("⭐ Buy Premium", callback_data="premium_menu")]
        ])

    kb = [
        [
            InlineKeyboardButton("⏭️ Next Video", callback_data="next_video"),
            InlineKeyboardButton("📊 Free Count", callback_data="show_free"),
        ],
        [
            InlineKeyboardButton("⭐ Buy Premium", callback_data="premium_menu")
        ]
    ]
    return InlineKeyboardMarkup(kb)


def join_group_buttons(invite_url: Optional[str] = None, group_username: Optional[str] = None):
    """
    Inline keyboard to prompt the user to join the required group.
    - If invite_url given: shows a URL button "➡️ Join Group"
    - Else if group_username given: opens t.me/<group_username>
    - Always shows "✔️ I Joined" callback button to re-check membership
    """
    buttons = []

    if invite_url:
        buttons.append([InlineKeyboardButton("➡️ Join Group", url=invite_url)])
    elif group_username:
        # best-effort open via username
        buttons.append([InlineKeyboardButton("➡️ Open Group", url=f"https://t.me/{group_username}")])
    else:
        # fallback instructive button (callback) — will tell user to get invite from admin
        buttons.append([InlineKeyboardButton("➡️ Get Invite", callback_data="open_group")])

    buttons.append([InlineKeyboardButton("✔️ I Joined", callback_data="check_join")])
    return InlineKeyboardMarkup(buttons)


def premium_contact_buttons(admin_tg_username: Optional[str] = None, admin_contact_link: Optional[str] = None):
    """
    Inline keyboard shown on premium menu or payment instructions.
    """
    buttons = []
    if admin_contact_link:
        buttons.append([InlineKeyboardButton("📞 Contact Admin", url=admin_contact_link)])
    elif admin_tg_username:
        buttons.append([InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{admin_tg_username}")])
    else:
        buttons.append([InlineKeyboardButton("📞 Contact Admin", callback_data="contact_admin")])

    # quick buy placeholders (could be web-pay links)
    buttons.append([
        InlineKeyboardButton("🕐 10 days - Buy", callback_data="buy_10"),
        InlineKeyboardButton("🕘 20 days - Buy", callback_data="buy_20")
    ])
    buttons.append([InlineKeyboardButton("📅 30 days - Buy", callback_data="buy_30")])

    return InlineKeyboardMarkup(buttons)


def admin_broadcast_buttons():
    """
    Small helper keyboard for admin broadcast actions (if you use via admin panel).
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Broadcast Now", callback_data="broadcast_now")],
        [InlineKeyboardButton("📝 Preview", callback_data="broadcast_preview")]
    ])
