"""
Heikin Ashi RSI 33 — Bybit Bot

Strategy logic:
    1. No position:
       RSI(14) < 33 + new green Heikin-Ashi candle -> LONG

    2. LONG:
       new red Heikin-Ashi candle -> reverse to SHORT

    3. SHORT:
       new green Heikin-Ashi candle -> CLOSE SHORT

Position sizing:
    5% of current Bybit Unified Account equity × 3 leverage

Important:
    - One position maximum for the entire account.
    - No Take Profit.
    - No Stop Loss.
    - No TradingView webhook required.
    - Strategy logic runs directly in Python.
"""

import os
import time
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any, List

from pybit.unified_trading import HTTP


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# Real Bybit account by default.
# Set BYBIT_TESTNET=true in Render if you want testnet.
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

# Symbols separated by commas:
# BTCUSDT,ETHUSDT,SOLUSDT
SYMBOLS = [
    symbol.strip().upper()
    for symbol in os.getenv(
        "SYMBOLS",
        "BTCUSDT"
    ).split(",")
    if symbol.strip()
]

# Trading timeframe.
# Bybit interval "5" = 5 minutes.
INTERVAL = os.getenv("INTERVAL", "5")

# How often the bot checks the market.
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "10"))

# Strategy parameters.
RSI_LENGTH = 14
RSI_ENTRY = 33

# Position sizing.
MARGIN_PERCENT = Decimal("0.05")
LEVERAGE = Decimal("3")

# Number of candles used for calculations.
KLINE_LIMIT = 200

# Bybit Unified Account.
CATEGORY = "linear"
ACCOUNT_TYPE = "UNIFIED"
SETTLE_COIN = "USDT"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("heikin-ashi-bot")


# ============================================================
# BYBIT SESSION
# ============================================================

if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "BYBIT_API_KEY and BYBIT_API_SECRET must be set "
        "in environment variables."
    )

session = HTTP(
    testnet=BYBIT_TESTNET,
    api_key=API_KEY,
    api_secret=API_SECRET,
)


# ============================================================
# INTERNAL STATE
# ============================================================

# Last closed candle processed for each symbol.
last_processed_candle: Dict[str, int] = {}

# Instrument information cache.
instrument_cache: Dict[str, Dict[str, Decimal]] = {}


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_symbol(symbol: str) -> str:
    """
    Converts symbols to Bybit format.
    """
    symbol = symbol.upper().strip()

    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    if symbol.endswith(".P"):
        symbol = symbol[:-2]

    return symbol


def decimal_places(step: Decimal) -> int:
    """
    Returns number of decimal places required by a quantity step.
    """
    exponent = step.as_tuple().exponent
    return max(0, -exponent)


def round_qty(qty: Decimal, step: Decimal) -> Decimal:
    """
    Rounds quantity DOWN to Bybit qtyStep.
    """
    if step <= 0:
        return qty

    units = (qty / step).to_integral_value(
        rounding=ROUND_DOWN
    )

    result = units * step

    places = decimal_places(step)

    return result.quantize(
        Decimal("1").scaleb(-places)
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_current_equity() -> Decimal:
    """
    Gets current total equity from Bybit Unified Account.

    Bybit's totalEquity includes account equity and
    unrealized PnL.
    """

    response = session.get_wallet_balance(
        accountType=ACCOUNT_TYPE,
        coin=SETTLE_COIN,
    )

    result = response["result"]["list"]

    if not result:
        raise RuntimeError("Unable to read Bybit account equity.")

    equity = Decimal(result[0]["totalEquity"])

    if equity <= 0:
        raise RuntimeError(
            f"Invalid account equity: {equity}"
        )

    return equity


# ============================================================
# POSITION
# ============================================================

def get_open_position() -> Optional[Dict[str, Any]]:
    """
    Returns the first open linear position on the entire account.

    IMPORTANT:
    We intentionally do NOT check only one symbol.

    This implements:
        ONE POSITION MAXIMUM FOR THE WHOLE ACCOUNT.
    """

    response = session.get_positions(
        category=CATEGORY,
        settleCoin=SETTLE_COIN,
    )

    positions = response["result"]["list"]

    for position in positions:

        size = Decimal(position.get("size", "0"))

        if size > 0:
            return position

    return None


# ============================================================
# INSTRUMENT INFORMATION
# ============================================================

def get_instrument_info(symbol: str) -> Dict[str, Decimal]:
    """
    Gets Bybit quantity rules for a symbol.
    """

    symbol = normalize_symbol(symbol)

    if symbol in instrument_cache:
        return instrument_cache[symbol]

    response = session.get_instruments_info(
        category=CATEGORY,
        symbol=symbol,
    )

    instruments = response["result"]["list"]

    if not instruments:
        raise RuntimeError(
            f"Instrument not found on Bybit: {symbol}"
        )

    instrument = instruments[0]
    lot = instrument["lotSizeFilter"]

    info = {
        "qty_step": Decimal(lot["qtyStep"]),
        "min_qty": Decimal(lot["minOrderQty"]),
        "min_notional": Decimal(
            lot.get("minNotionalValue", "0")
        ),
        "max_market_qty": Decimal(
            lot.get(
                "maxMktOrderQty",
                "999999999"
            )
        ),
    }

    instrument_cache[symbol] = info

    return info


# ============================================================
# QUANTITY CALCULATION
# ============================================================

def calculate_position_quantity(
    symbol: str,
    price: Decimal,
) -> Decimal:
    """
    Strategy sizing:

        5% equity = margin
        margin × 3 = position value
        position value / price = coin quantity
    """

    equity = get_current_equity()

    margin_amount = equity * MARGIN_PERCENT

    position_value = margin_amount * LEVERAGE

    raw_qty = position_value / price

    info = get_instrument_info(symbol)

    qty = round_qty(
        raw_qty,
        info["qty_step"],
    )

    if qty < info["min_qty"]:
        raise RuntimeError(
            f"{symbol}: calculated quantity {qty} "
            f"is below Bybit minimum {info['min_qty']}"
        )

    if qty > info["max_market_qty"]:
        qty = round_qty(
            info["max_market_qty"],
            info["qty_step"],
        )

    notional = qty * price

    if notional < info["min_notional"]:
        raise RuntimeError(
            f"{symbol}: order value {notional} "
            f"is below minimum notional "
            f"{info['min_notional']}"
        )

    return qty


# ============================================================
# MARKET DATA
# ============================================================

def get_closed_klines(
    symbol: str,
) -> List[List[str]]:
    """
    Returns recent closed candles.

    Bybit returns candles newest first.
    We reverse them so calculations run oldest -> newest.
    """

    response = session.get_kline(
        category=CATEGORY,
        symbol=symbol,
        interval=INTERVAL,
        limit=KLINE_LIMIT,
    )

    candles = response["result"]["list"]

    if not candles:
        raise RuntimeError(
            f"No candles returned for {symbol}"
        )

    candles = list(reversed(candles))

    # Last candle may still be forming.
    # We remove it and work only with closed candles.
    candles = candles[:-1]

    return candles


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes: List[float],
    length: int,
) -> List[Optional[float]]:
    """
    Wilder RSI calculation.

    Equivalent to TradingView ta.rsi()
    for the strategy logic.
    """

    if len(closes) < length + 1:
        return [None] * len(closes)

    rsi_values: List[Optional[float]] = [
        None
    ] * len(closes)

    gains = []
    losses = []

    for i in range(1, length + 1):

        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length

    if avg_loss == 0:
        rsi_values[length] = 100.0

    else:
        rs = avg_gain / avg_loss

        rsi_values[length] = (
            100.0 - (100.0 / (1.0 + rs))
        )

    for i in range(length + 1, len(closes)):

        change = closes[i] - closes[i - 1]

        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        avg_gain = (
            (avg_gain * (length - 1)) + gain
        ) / length

        avg_loss = (
            (avg_loss * (length - 1)) + loss
        ) / length

        if avg_loss == 0:
            rsi_values[i] = 100.0

        else:
            rs = avg_gain / avg_loss

            rsi_values[i] = (
                100.0 - (100.0 / (1.0 + rs))
            )

    return rsi_values


# ============================================================
# HEIKIN ASHI
# ============================================================

def calculate_heikin_ashi(
    candles: List[List[str]],
) -> Dict[str, Any]:
    """
    Calculates Heikin-Ashi exactly from normal OHLC candles.

    HA close:
        (O + H + L + C) / 4

    HA open:
        first candle:
            (O + C) / 2

        following candles:
            (previous HA open + previous HA close) / 2
    """

    ha_opens = []
    ha_closes = []
    green = []
    red = []

    previous_ha_open = None
    previous_ha_close = None

    for candle in candles:

        open_price = float(candle[1])
        high_price = float(candle[2])
        low_price = float(candle[3])
        close_price = float(candle[4])

        ha_close = (
            open_price
            + high_price
            + low_price
            + close_price
        ) / 4.0

        if previous_ha_open is None:
            ha_open = (
                open_price + close_price
            ) / 2.0

        else:
            ha_open = (
                previous_ha_open
                + previous_ha_close
            ) / 2.0

        ha_opens.append(ha_open)
        ha_closes.append(ha_close)

        green.append(ha_close > ha_open)
        red.append(ha_close < ha_open)

        previous_ha_open = ha_open
        previous_ha_close = ha_close

    return {
        "open": ha_opens,
        "close": ha_closes,
        "green": green,
        "red": red,
    }


# ============================================================
# STRATEGY SIGNAL
# ============================================================

def get_signal(
    symbol: str,
) -> Optional[Dict[str, Any]]:
    """
    Calculates the signal on the latest CLOSED candle.

    Returns:

        LONG
        SHORT
        CLOSE_SHORT
        None
    """

    candles = get_closed_klines(symbol)

    if len(candles) < RSI_LENGTH + 2:
        return None

    closes = [
        float(candle[4])
        for candle in candles
    ]

    rsi_values = calculate_rsi(
        closes,
        RSI_LENGTH,
    )

    ha = calculate_heikin_ashi(candles)

    index = len(candles) - 1
    previous = index - 1

    current_rsi = rsi_values[index]

    if current_rsi is None:
        return None

    current_green = ha["green"][index]
    current_red = ha["red"][index]

    previous_green = ha["green"][previous]
    previous_red = ha["red"][previous]

    # TradingView logic:
    #
    # green trigger:
    # green now AND NOT green previously
    #
    # red trigger:
    # red now AND NOT red previously

    green_trigger = (
        current_green
        and not previous_green
    )

    red_trigger = (
        current_red
        and not previous_red
    )

    candle_timestamp = int(candles[index][0])

    close_price = Decimal(
        candles[index][4]
    )

    return {
        "symbol": symbol,
        "timestamp": candle_timestamp,
        "price": close_price,
        "rsi": current_rsi,
        "green_trigger": green_trigger,
        "red_trigger": red_trigger,
    }


# ============================================================
# ORDERS
# ============================================================

def open_long(
    symbol: str,
    price: Decimal,
) -> None:

    qty = calculate_position_quantity(
        symbol,
        price,
    )

    logger.info(
        "OPEN LONG | %s | qty=%s | price=%s",
        symbol,
        qty,
        price,
    )

    response = session.place_order(
        category=CATEGORY,
        symbol=symbol,
        side="Buy",
        orderType="Market",
        qty=str(qty),
        positionIdx=0,
        reduceOnly=False,
        orderLinkId=f"HA_LONG_{int(time.time())}",
    )

    logger.info(
        "LONG ORDER RESPONSE: %s",
        response,
    )


def open_short(
    symbol: str,
    price: Decimal,
) -> None:

    qty = calculate_position_quantity(
        symbol,
        price,
    )

    logger.info(
        "OPEN SHORT | %s | qty=%s | price=%s",
        symbol,
        qty,
        price,
    )

    response = session.place_order(
        category=CATEGORY,
        symbol=symbol,
        side="Sell",
        orderType="Market",
        qty=str(qty),
        positionIdx=0,
        reduceOnly=False,
        orderLinkId=f"HA_SHORT_{int(time.time())}",
    )

    logger.info(
        "SHORT ORDER RESPONSE: %s",
        response,
    )


def close_position(
    position: Dict[str, Any],
) -> None:

    symbol = position["symbol"]
    side = position["side"]
    size = Decimal(position["size"])

    if side == "Buy":
        close_side = "Sell"
    else:
        close_side = "Buy"

    logger.info(
        "CLOSE POSITION | %s | side=%s | size=%s",
        symbol,
        side,
        size,
    )

    response = session.place_order(
        category=CATEGORY,
        symbol=symbol,
        side=close_side,
        orderType="Market",
        qty=str(size),
        positionIdx=0,
        reduceOnly=True,
        orderLinkId=f"HA_CLOSE_{int(time.time())}",
    )

    logger.info(
        "CLOSE ORDER RESPONSE: %s",
        response,
    )


# ============================================================
# STRATEGY ENGINE
# ============================================================

def process_symbol(symbol: str) -> None:

    symbol = normalize_symbol(symbol)

    signal = get_signal(symbol)

    if signal is None:
        return

    candle_timestamp = signal["timestamp"]

    # --------------------------------------------------------
    # Prevent duplicate processing
    # --------------------------------------------------------

    if last_processed_candle.get(symbol) == candle_timestamp:
        return

    # Mark this candle as processed before trading.
    last_processed_candle[symbol] = candle_timestamp

    logger.info(
        "%s | candle=%s | RSI=%.2f | green=%s | red=%s",
        symbol,
        candle_timestamp,
        signal["rsi"],
        signal["green_trigger"],
        signal["red_trigger"],
    )

    # --------------------------------------------------------
    # CRITICAL:
    # Only one position on the entire account.
    # --------------------------------------------------------

    position = get_open_position()

    # ========================================================
    # NO POSITION
    # ========================================================

    if position is None:

        # Original Pine logic:
        #
        # RSI < 33
        # AND
        # new green HA candle
        #
        # -> LONG

        if (
            signal["rsi"] < RSI_ENTRY
            and signal["green_trigger"]
        ):

            open_long(
                symbol,
                signal["price"],
            )

        return

    # ========================================================
    # POSITION EXISTS
    # ========================================================

    position_symbol = normalize_symbol(
        position["symbol"]
    )

    position_side = position["side"]

    # --------------------------------------------------------
    # LONG -> SHORT
    # --------------------------------------------------------

    if position_side == "Buy":

        if signal["symbol"] != position_symbol:
            return

        if signal["red_trigger"]:

            logger.info(
                "RED HA -> REVERSING LONG TO SHORT | %s",
                position_symbol,
            )

            # First close LONG.
            close_position(position)

            # Then open SHORT.
            #
            # We use the same symbol and current signal price.
            open_short(
                position_symbol,
                signal["price"],
            )

        return

    # --------------------------------------------------------
    # SHORT -> CLOSE
    # --------------------------------------------------------

    if position_side == "Sell":

        if signal["symbol"] != position_symbol:
            return

        if signal["green_trigger"]:

            logger.info(
                "GREEN HA -> CLOSE SHORT | %s",
                position_symbol,
            )

            close_position(position)

        return


# ============================================================
# MAIN LOOP
# ============================================================

def main() -> None:

    logger.info("=" * 60)
    logger.info("HEIKIN ASHI RSI 33 — BYBIT BOT")
    logger.info("=" * 60)

    logger.info(
        "Environment: %s",
        "TESTNET" if BYBIT_TESTNET else "LIVE",
    )

    logger.info(
        "Symbols: %s",
        ", ".join(SYMBOLS),
    )

    logger.info(
        "Timeframe: %s",
        INTERVAL,
    )

    logger.info(
        "RSI: %s | Entry: <%s",
        RSI_LENGTH,
        RSI_ENTRY,
    )

    logger.info(
        "Position size: %s%% equity × %sx leverage",
        MARGIN_PERCENT * 100,
        LEVERAGE,
    )

    logger.info(
        "Maximum positions: 1 account-wide"
    )

    logger.info("=" * 60)

    while True:

        try:

            for symbol in SYMBOLS:

                try:
                    process_symbol(symbol)

                except Exception as error:

                    logger.exception(
                        "Error processing %s: %s",
                        symbol,
                        error,
                    )

                # Small pause between symbols.
                time.sleep(0.2)

        except Exception as error:

            logger.exception(
                "Main loop error: %s",
                error,
            )

        time.sleep(POLL_SECONDS)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
