"""Callback data constants."""

# Navigation
CB_MAIN = "nav:main"
CB_BUNDLES = "nav:bundles"

# Bundles section
CB_SELECT_BUNDLE = "bundles:select"
CB_ACTIVE_BUNDLES = "bundles:active"

# Wallet section
CB_WALLET = "nav:wallet"
CB_DEPOSIT = "wallet:deposit"
CB_DEPOSIT_CANCEL = "wallet:deposit_cancel"
CB_WITHDRAW = "wallet:withdraw"
CB_TX_HISTORY = "wallet:tx_history"
CB_QUANTUM_PLUS = "wallet:plus"

# Main menu items
CB_OPEN_APP = "main:open_app"
CB_HISTORY = "main:history"
CB_INFO = "main:info"
CB_SUPPORT = "main:support"
CB_SUPPORT_WRITE = "main:support_write"
CB_REFERRALS = "main:referrals"

# Info section
CB_TUTORIAL_1 = "info:tut1"
CB_TUTORIAL_2 = "info:tut2"
CB_TUTORIAL_3 = "info:tut3"
CB_TUTORIAL_4 = "info:tut4"
CB_ABOUT = "info:about"
CB_TOS_1 = "info:tos1"
CB_TOS_2 = "info:tos2"
CB_TOS_3 = "info:tos3"
CB_TOS_4 = "info:tos4"

# Conversation states
DEPOSIT_AMOUNT   = 0
BUNDLE_AMOUNT    = 1
SUPPORT_MESSAGE  = 2
ADMIN_REPLY_TEXT = 3
WITHDRAW_AMOUNT  = 4
WITHDRAW_ADDRESS = 5
ADMIN_WITHDRAW_REJECT_REASON = 6

# Admin panel
CB_ADMIN_PANEL = "admin:panel"
CB_ADMIN_REPLY_PREFIX = "admin:reply:"            # + ticket_id
CB_ADMIN_WITHDRAW_PREFIX = "admin:wd:"            # + withdraw_id (show)
CB_ADMIN_WITHDRAW_APPROVE = "admin:wd:approve:"   # + withdraw_id
CB_ADMIN_WITHDRAW_REJECT  = "admin:wd:reject:"    # + withdraw_id

# Quantum+ section
CB_PLUS_ABOUT = "plus:about"
CB_PLUS_BUY = "plus:buy"

# Coin selection prefix
CB_COIN_PREFIX = "coin:"

# Default coin list with spread labels
COINS: list[tuple[str, str]] = [
    ("BTC", "1.81%–1.83%"),
    ("AAVE", "0.37%–0.39%"),
    ("BR", "0.21%"),
    ("MNT", "0.12%–0.14%"),
    ("HYPE", "0.18%–0.21%"),
    ("DOGE", "0.41%–0.42%"),
    ("LTC", "0.28%"),
    ("AVAX", "0.16%–0.19%"),
    ("SOL", "1.09%"),
]

# Bundle configuration
# "Coin": ("Exchange 1", "Exchange 2", "Spread", min_usdt, max_usdt, min_profit, max_profit, min_time, max_time)
BUNDLE_CONFIG = {
    "BTC": ("Binance", "Bybit", "1.81%–1.83%", 100, 200, 1.81, 1.83, 20, 120),
    "AAVE": ("OKX", "Huobi", "0.37%–0.39%", 50, 100, 0.37, 0.39, 20, 120),
    "BR": ("KuCoin", "Gate.io", "0.21%", 10, 30, 0.21, 0.21, 20, 120),
    "MNT": ("Bybit", "Mexc", "0.12%–0.14%", 10, 30, 0.12, 0.14, 20, 120),
    "HYPE": ("Binance", "OKX", "0.18%–0.21%", 10, 30, 0.18, 0.21, 20, 120),
    "DOGE": ("Huobi", "KuCoin", "0.41%–0.42%", 50, 100, 0.41, 0.42, 20, 120),
    "LTC": ("Gate.io", "Mexc", "0.28%", 50, 100, 0.28, 0.28, 20, 120),
    "AVAX": ("Binance", "Bybit", "0.16%–0.19%", 100, 200, 0.16, 0.19, 20, 120),
    "SOL": ("OKX", "Huobi", "1.09%", 100, 200, 1.09, 1.09, 20, 120),
}

OPERATIONS_LIMIT = 100
PLUS_OPERATIONS_LIMIT = 300
PLUS_SUBSCRIPTION_PRICE = 40.0
DEPOSIT_COMMISSION = 0.07        # 7% для обычных пользователей
DEPOSIT_COMMISSION_PLUS = 0.03   # 3% для Quantum+
WITHDRAW_COMMISSION = 0.08       # 8% комиссия на вывод
REFERRAL_COMMISSION = 0.30
