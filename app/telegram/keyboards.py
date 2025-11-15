from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def ad_buttons(short_url, token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 Watch Ad", url=short_url)],
        [InlineKeyboardButton("✔️ I Watched", callback_data=f"ad_check:{token}")]
    ])

def free_or_premium():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Buy Premium", callback_data="premium_menu")]
    ])
