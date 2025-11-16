# app/telegram/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def video_control_buttons(token_for_ad: str = None, ad_short_url: str = None):
    """
    Buttons shown under each video:
    - Next Video (callback -> next_video)
    - Show Free Count (callback -> show_free)
    - Buy Premium (callback -> premium_menu)
    If token_for_ad & ad_short_url provided, we will also include ad buttons instead of Next.
    """
    buttons = []

    # Row 1: Next Video / Show Free Count
    buttons.append([
        InlineKeyboardButton("⏭️ Next Video", callback_data="next_video"),
        InlineKeyboardButton("📊 Free Count", callback_data="show_free")
    ])

    # Row 2: Buy Premium
    buttons.append([
        InlineKeyboardButton("⭐ Buy Premium", callback_data="premium_menu")
    ])

    # If ad info provided return watch-ad block
    if ad_short_url and token_for_ad:
        # place watch ad url and I Watched (callback)
        ad_row1 = [InlineKeyboardButton("🎥 Watch Ad", url=ad_short_url)]
        ad_row2 = [InlineKeyboardButton("✔️ I Watched", callback_data=f"ad_check:{token_for_ad}")]
        # merge: ad rows then premium
        return InlineKeyboardMarkup([ad_row1, ad_row2, [InlineKeyboardButton("⭐ Buy Premium", callback_data="premium_menu")]])

    return InlineKeyboardMarkup(buttons)
