from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def next_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Next ▶️", callback_data="next")]])

def ad_btn(short_url, token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Watch Ad", url=short_url)],
        [InlineKeyboardButton("I Watched", callback_data=f"ad_check:{token}")]
    ])
