# app/telegram/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def video_control_buttons(token_for_ad: str = None, ad_short_url: str = None):
    """
    Buttons shown under each video:
    - Next Video (callback -> next_video)
    - Show Free Count (callback -> show_free)
    - Buy Premium (callback -> premium_menu)
    If token_for_ad & ad_short_url provided, replace Next with Ad-Watch Buttons.
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
