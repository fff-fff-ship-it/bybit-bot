import os
import time
import math
import threading
from flask import Flask, jsonify
from pybit.unified_trading import HTTP


# ============================================================
# APP
# ============================================================

app = Flask(__name__)


# ============================================================
# BYBIT API
# ============================================================

API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

if not API_KEY or not API_SECRET:
    raise Exception("BYBIT_API_KEY / BYBIT_API_SECRET не заданы")


TESTNET = os.environ.get("BYBIT_TESTNET", "false").lower() == "true"

session = HTTP(
    testnet=TESTNET,
    api_key=API_KEY,
    api_secret=API_SECRET
)


# ============================================================
# НАСТРОЙКИ СТРАТЕГИИ
# ============================================================

RSI_LENGTH = 14
RSI_ENTRY = 33

TIMEFRAME = os.environ.get("TIMEFRAME", "5")

# 5% текущего equity
EQUITY_PERCENT = 0.05

# Плечо 3x
LEVERAGE = 3


# ============================================================
# НАСТРОЙКИ БОТА
# ============================================================

POLL_SECONDS = int(
    os.environ.get("POLL_SECONDS", "10")
)

# Например:
# BTCUSDT,ETHUSDT,SOLUSDT
SYMBOLS = [
    symbol.strip().upper()
    for symbol in os.environ.get(
        "SYMBOLS",
        "BTCUSDT"
    ).split(",")
    if symbol.strip()
]


# ============================================================
# ЗАЩИТА ОТ ОДНОВРЕМЕННЫХ ОПЕРАЦИЙ
# ============================================================

trade_lock = threading.Lock()


# ============================================================
# ПОСЛЕДНЯЯ ОБРАБОТАННАЯ СВЕЧА
# ============================================================

last_processed_candle = {}


# ============================================================
# НОРМАЛИЗАЦИЯ SYMBOL
# ============================================================

def normalize_symbol(symbol):

    if not symbol:
        return ""

    symbol = str(symbol).strip().upper()

    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    if symbol.endswith(".P"):
        symbol = symbol[:-2]

    return symbol


# ============================================================
# ПОЛУЧЕНИЕ CURRENT EQUITY
# ============================================================

def get_current_equity():

    response = session.get_wallet_balance(
        accountType="UNIFIED",
        coin="USDT"
    )

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                "Ошибка получения баланса"
            )
        )

    result = response.get(
        "result",
        {}
    )

    accounts = result.get(
        "list",
        []
    )

    if not accounts:
        raise Exception(
            "Bybit не вернул данные Unified Account"
        )

    account = accounts[0]

    equity = float(
        account.get(
            "totalEquity",
            "0"
        ) or 0
    )

    if equity <= 0:

        # Запасной вариант
        coin_list = account.get(
            "coin",
            []
        )

        for coin in coin_list:

            if coin.get("coin") == "USDT":

                equity = float(
                    coin.get(
                        "equity",
                        "0"
                    ) or 0
                )

                break

    if equity <= 0:
        raise Exception(
            "Current equity <= 0"
        )

    return equity


# ============================================================
# ПОЛУЧЕНИЕ ТЕКУЩЕЙ ЦЕНЫ
# ============================================================

def get_price(symbol):

    response = session.get_tickers(
        category="linear",
        symbol=symbol
    )

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                f"Ошибка цены {symbol}"
            )
        )

    items = response.get(
        "result",
        {}
    ).get(
        "list",
        []
    )

    if not items:
        raise Exception(
            f"Цена {symbol} не найдена"
        )

    return float(
        items[0]["lastPrice"]
    )


# ============================================================
# ПОЛУЧЕНИЕ ВСЕХ ОТКРЫТЫХ ПОЗИЦИЙ
# ============================================================

def get_account_position():

    response = session.get_positions(
        category="linear",
        settleCoin="USDT"
    )

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                "Ошибка получения позиций"
            )
        )

    positions = response.get(
        "result",
        {}
    ).get(
        "list",
        []
    )

    for position in positions:

        side = position.get(
            "side",
            ""
        )

        size = float(
            position.get(
                "size",
                "0"
            ) or 0
        )

        if size > 0 and side in ["Buy", "Sell"]:

            return {
                "symbol": normalize_symbol(
                    position.get("symbol")
                ),
                "side": side,
                "size": size,
                "positionIdx": position.get(
                    "positionIdx",
                    0
                )
            }

    return None


# ============================================================
# ПОЛУЧЕНИЕ ИНФОРМАЦИИ ОБ ИНСТРУМЕНТЕ
# ============================================================

def get_instrument_info(symbol):

    response = session.get_instruments_info(
        category="linear",
        symbol=symbol
    )

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                f"Ошибка информации {symbol}"
            )
        )

    instruments = response.get(
        "result",
        {}
    ).get(
        "list",
        []
    )

    if not instruments:
        raise Exception(
            f"Bybit не нашёл инструмент {symbol}"
        )

    return instruments[0]


# ============================================================
# ОКРУГЛЕНИЕ QTY
# ============================================================

def calculate_quantity(symbol, price):

    # --------------------------------------------------------
    # CURRENT EQUITY
    # --------------------------------------------------------

    equity = get_current_equity()

    # --------------------------------------------------------
    # 5% EQUITY
    # --------------------------------------------------------

    margin_amount = equity * EQUITY_PERCENT

    # --------------------------------------------------------
    # 5% × 3x
    # --------------------------------------------------------

    position_usdt = margin_amount * LEVERAGE

    # --------------------------------------------------------
    # QTY COIN
    # --------------------------------------------------------

    raw_qty = position_usdt / price

    # --------------------------------------------------------
    # ПАРАМЕТРЫ ИНСТРУМЕНТА
    # --------------------------------------------------------

    instrument = get_instrument_info(
        symbol
    )

    lot_filter = instrument.get(
        "lotSizeFilter",
        {}
    )

    min_qty = float(
        lot_filter.get(
            "minOrderQty",
            "0"
        ) or 0
    )

    qty_step = float(
        lot_filter.get(
            "qtyStep",
            "1"
        ) or 1
    )

    max_qty = float(
        lot_filter.get(
            "maxOrderQty",
            "0"
        ) or 0
    )

    # --------------------------------------------------------
    # ОКРУГЛЕНИЕ ВНИЗ
    # --------------------------------------------------------

    if qty_step <= 0:
        qty_step = 1

    qty = math.floor(
        raw_qty / qty_step
    ) * qty_step

    # --------------------------------------------------------
    # MIN QTY
    # --------------------------------------------------------

    if qty < min_qty:
        qty = min_qty

    # --------------------------------------------------------
    # MAX QTY
    # --------------------------------------------------------

    if max_qty > 0 and qty > max_qty:
        qty = max_qty

    if qty <= 0:
        raise Exception(
            f"Некорректный qty для {symbol}"
        )

    qty_string = format(
        qty,
        ".12f"
    ).rstrip("0").rstrip(".")

    print(
        f"--> EQUITY: ${equity:.2f}"
    )

    print(
        f"--> 5% MARGIN: ${margin_amount:.2f}"
    )

    print(
        f"--> POSITION 3x: ${position_usdt:.2f}"
    )

    print(
        f"--> PRICE: {price}"
    )

    print(
        f"--> QTY: {qty_string}"
    )

    return qty_string


# ============================================================
# УСТАНОВКА ПЛЕЧА 3x
# ============================================================

def set_leverage(symbol):

    try:

        response = session.set_leverage(
            category="linear",
            symbol=symbol,
            buyLeverage=str(LEVERAGE),
            sellLeverage=str(LEVERAGE)
        )

        if response.get("retCode") == 0:

            print(
                f"--> LEVERAGE {symbol}: {LEVERAGE}x"
            )

        else:

            print(
                f"--> LEVERAGE {symbol}: "
                f"{response.get('retMsg')}"
            )

    except Exception as e:

        print(
            f"--> LEVERAGE ERROR {symbol}: {e}"
        )


# ============================================================
# ПОЛУЧЕНИЕ 5M CANDLES
# ============================================================

def get_closed_candles(symbol, limit=100):

    response = session.get_kline(
        category="linear",
        symbol=symbol,
        interval=TIMEFRAME,
        limit=limit
    )

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                f"Ошибка свечей {symbol}"
            )
        )

    candles = response.get(
        "result",
        {}
    ).get(
        "list",
        []
    )

    if not candles:
        raise Exception(
            f"Нет свечей {symbol}"
        )

    # Bybit возвращает от новых к старым
    candles = list(reversed(candles))

    # Последняя свеча может быть текущей,
    # поэтому её не используем.
    if len(candles) > 1:
        candles = candles[:-1]

    result = []

    for candle in candles:

        result.append({
            "time": int(candle[0]),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4])
        })

    return result


# ============================================================
# RSI — WILDER / TV STYLE
# ============================================================

def calculate_rsi(closes, length=14):

    if len(closes) <= length:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        change = closes[i] - closes[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0.0)

        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(
        gains[:length]
    ) / length

    avg_loss = sum(
        losses[:length]
    ) / length

    rsi_values = [
        None
    ] * length

    # --------------------------------------------------------
    # Дальше Wilder RMA
    # --------------------------------------------------------

    for i in range(length, len(gains)):

        avg_gain = (
            (avg_gain * (length - 1))
            + gains[i]
        ) / length

        avg_loss = (
            (avg_loss * (length - 1))
            + losses[i]
        ) / length

        if avg_loss == 0:

            rsi = 100.0

        else:

            rs = avg_gain / avg_loss

            rsi = 100.0 - (
                100.0 / (1.0 + rs)
            )

        rsi_values.append(rsi)

    return rsi_values[-1]


# ============================================================
# HEIKIN ASHI
# ============================================================

def calculate_heikin_ashi(candles):

    ha_open = None

    result = []

    for candle in candles:

        o = candle["open"]
        h = candle["high"]
        l = candle["low"]
        c = candle["close"]

        # Pine:
        # ha_close = (open + high + low + close) / 4

        ha_close = (
            o + h + l + c
        ) / 4.0

        # Pine:
        # ha_open := na(ha_open[1])
        # ? (open + close) / 2
        # : (ha_open[1] + ha_close[1]) / 2

        if ha_open is None:

            ha_open = (
                o + c
            ) / 2.0

        else:

            previous_ha_close = result[-1][
                "ha_close"
            ]

            ha_open = (
                ha_open
                + previous_ha_close
            ) / 2.0

        ha_green = (
            ha_close > ha_open
        )

        ha_red = (
            ha_close < ha_open
        )

        result.append({
            "time": candle["time"],
            "ha_open": ha_open,
            "ha_close": ha_close,
            "green": ha_green,
            "red": ha_red
        })

    return result


# ============================================================
# АНАЛИЗ СТРАТЕГИИ
# ============================================================

def analyze_symbol(symbol):

    candles = get_closed_candles(
        symbol,
        limit=100
    )

    if len(candles) < RSI_LENGTH + 5:
        return None

    closes = [
        candle["close"]
        for candle in candles
    ]

    rsi = calculate_rsi(
        closes,
        RSI_LENGTH
    )

    ha = calculate_heikin_ashi(
        candles
    )

    if len(ha) < 2:
        return None

    current = ha[-1]
    previous = ha[-2]

    # --------------------------------------------------------
    # EXACT PINE LOGIC
    # --------------------------------------------------------

    ha_green_trig = (
        current["green"]
        and not previous["green"]
    )

    ha_red_trig = (
        current["red"]
        and not previous["red"]
    )

    long_condition = (
        rsi is not None
        and rsi < RSI_ENTRY
        and ha_green_trig
    )

    return {
        "symbol": symbol,
        "candle_time": current["time"],
        "rsi": rsi,
        "ha_green": current["green"],
        "ha_red": current["red"],
        "ha_green_trig": ha_green_trig,
        "ha_red_trig": ha_red_trig,
        "long_condition": long_condition
    }


# ============================================================
# OPEN LONG
# ============================================================

def open_long(symbol):

    with trade_lock:

        # ----------------------------------------------------
        # ACCOUNT-WIDE POSITION CHECK
        # ----------------------------------------------------

        position = get_account_position()

        if position:

            print(
                f"--> ПОЗИЦИЯ УЖЕ ЕСТЬ: "
                f"{position['symbol']} "
                f"{position['side']} "
                f"qty={position['size']}"
            )

            return

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        price = get_price(
            symbol
        )

        # ----------------------------------------------------
        # LEVERAGE
        # ----------------------------------------------------

        set_leverage(
            symbol
        )

        # ----------------------------------------------------
        # QTY
        # ----------------------------------------------------

        qty = calculate_quantity(
            symbol,
            price
        )

        # ----------------------------------------------------
        # OPEN LONG
        # ----------------------------------------------------

        print(
            f"--> ОТКРЫВАЕМ LONG: "
            f"{symbol}, qty={qty}"
        )

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            positionIdx=0
        )

        print(
            f"--> LONG RESPONSE: {response}"
        )

        if response.get("retCode") != 0:

            raise Exception(
                response.get(
                    "retMsg",
                    "Ошибка открытия LONG"
                )
            )


# ============================================================
# CLOSE LONG
# ============================================================

def close_long(symbol):

    position = get_account_position()

    if not position:
        print(
            "--> LONG НЕ НАЙДЕН"
        )
        return False

    if position["side"] != "Buy":
        return False

    current_symbol = position["symbol"]
    current_size = position["size"]

    print(
        f"--> ЗАКРЫВАЕМ LONG: "
        f"{current_symbol}, "
        f"qty={current_size}"
    )

    response = session.place_order(
        category="linear",
        symbol=current_symbol,
        side="Sell",
        orderType="Market",
        qty=str(current_size),
        reduceOnly=True,
        positionIdx=0
    )

    print(
        f"--> CLOSE LONG RESPONSE: "
        f"{response}"
    )

    if response.get("retCode") != 0:

        raise Exception(
            response.get(
                "retMsg",
                "Ошибка закрытия LONG"
            )
        )

    return True


# ============================================================
# OPEN SHORT
# ============================================================

def open_short(symbol):

    with trade_lock:

        # ----------------------------------------------------
        # ПРОВЕРЯЕМ LONG
        # ----------------------------------------------------

        position = get_account_position()

        if not position:
            print(
                "--> LONG НЕ НАЙДЕН. "
                "SHORT НЕ ОТКРЫВАЕМ."
            )
            return

        if position["side"] != "Buy":

            print(
                "--> ПОЗИЦИЯ НЕ LONG. "
                "SHORT НЕ ОТКРЫВАЕМ."
            )

            return

        current_symbol = position["symbol"]
        current_size = position["size"]

        # ----------------------------------------------------
        # CLOSE LONG
        # ----------------------------------------------------

        print(
            f"--> REVERSAL: "
            f"CLOSE LONG {current_symbol}"
        )

        close_response = session.place_order(
            category="linear",
            symbol=current_symbol,
            side="Sell",
            orderType="Market",
            qty=str(current_size),
            reduceOnly=True,
            positionIdx=0
        )

        print(
            f"--> LONG CLOSED: "
            f"{close_response}"
        )

        if close_response.get("retCode") != 0:

            raise Exception(
                close_response.get(
                    "retMsg",
                    "Ошибка закрытия LONG"
                )
            )

        # ----------------------------------------------------
        # ЖДЁМ ЗАКРЫТИЯ
        # ----------------------------------------------------

        time.sleep(1)

        # ----------------------------------------------------
        # ПРОВЕРКА
        # ----------------------------------------------------

        remaining = get_account_position()

        if remaining:

            print(
                f"--> ПОЗИЦИЯ ЕЩЁ ОТКРЫТА: "
                f"{remaining}"
            )

            return

        # ----------------------------------------------------
        # УСТАНОВКА 3x
        # ----------------------------------------------------

        set_leverage(
            symbol
        )

        # ----------------------------------------------------
        # CURRENT PRICE
        # ----------------------------------------------------

        price = get_price(
            symbol
        )

        # ----------------------------------------------------
        # НОВЫЙ РАЗМЕР
        # ----------------------------------------------------

        qty = calculate_quantity(
            symbol,
            price
        )

        # ----------------------------------------------------
        # OPEN SHORT
        # ----------------------------------------------------

        print(
            f"--> ОТКРЫВАЕМ SHORT: "
            f"{symbol}, qty={qty}"
        )

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            positionIdx=0
        )

        print(
            f"--> SHORT RESPONSE: "
            f"{response}"
        )

        if response.get("retCode") != 0:

            raise Exception(
                response.get(
                    "retMsg",
                    "Ошибка открытия SHORT"
                )
            )


# ============================================================
# CLOSE SHORT
# ============================================================

def close_short(symbol):

    with trade_lock:

        position = get_account_position()

        if not position:

            print(
                "--> SHORT НЕ НАЙДЕН"
            )

            return

        if position["side"] != "Sell":

            print(
                "--> ПОЗИЦИЯ НЕ SHORT"
            )

            return

        current_symbol = position["symbol"]
        current_size = position["size"]

        print(
            f"--> ЗАКРЫВАЕМ SHORT: "
            f"{current_symbol}, "
            f"qty={current_size}"
        )

        response = session.place_order(
            category="linear",
            symbol=current_symbol,
            side="Buy",
            orderType="Market",
            qty=str(current_size),
            reduceOnly=True,
            positionIdx=0
        )

        print(
            f"--> SHORT CLOSED: "
            f"{response}"
        )

        if response.get("retCode") != 0:

            raise Exception(
                response.get(
                    "retMsg",
                    "Ошибка закрытия SHORT"
                )
            )


# ============================================================
# ОБРАБОТКА ОДНОГО SYMBOL
# ============================================================

def process_symbol(symbol):

    symbol = normalize_symbol(
        symbol
    )

    try:

        analysis = analyze_symbol(
            symbol
        )

        if not analysis:
            return

        candle_time = analysis[
            "candle_time"
        ]

        # ----------------------------------------------------
        # НЕ ОБРАБАТЫВАЕМ ОДНУ СВЕЧУ ДВАЖДЫ
        # ----------------------------------------------------

        if last_processed_candle.get(symbol) == candle_time:
            return

        last_processed_candle[
            symbol
        ] = candle_time

        # ----------------------------------------------------
        # LOG
        # ----------------------------------------------------

        print(
            f"{symbol} | "
            f"candle={candle_time} | "
            f"RSI={analysis['rsi']:.2f} | "
            f"green={analysis['ha_green']} | "
            f"red={analysis['ha_red']} | "
            f"greenTrig={analysis['ha_green_trig']} | "
            f"redTrig={analysis['ha_red_trig']}"
        )

        # ----------------------------------------------------
        # ACCOUNT POSITION
        # ----------------------------------------------------

        position = get_account_position()

        # ====================================================
        # НЕТ ПОЗИЦИИ
        # ====================================================

        if not position:

            # EXACT PINE:
            # RSI < 33 AND red -> green

            if analysis["long_condition"]:

                print(
                    f"--> LONG SIGNAL: {symbol}"
                )

                open_long(
                    symbol
                )

            return

        # ====================================================
        # ЕСТЬ LONG
        # ====================================================

        if position["side"] == "Buy":

            # ------------------------------------------------
            # Только новый красный HA
            # ------------------------------------------------

            if (
                position["symbol"] == symbol
                and analysis["ha_red_trig"]
            ):

                print(
                    f"--> SHORT SIGNAL: {symbol}"
                )

                open_short(
                    symbol
                )

            return

        # ====================================================
        # ЕСТЬ SHORT
        # ====================================================

        if position["side"] == "Sell":

            # ------------------------------------------------
            # Только новый зелёный HA
            # ------------------------------------------------

            if (
                position["symbol"] == symbol
                and analysis["ha_green_trig"]
            ):

                print(
                    f"--> CLOSE SHORT SIGNAL: "
                    f"{symbol}"
                )

                close_short(
                    symbol
                )

            return

    except Exception as e:

        print(
            f"--> ERROR {symbol}: {e}"
        )


# ============================================================
# ОСНОВНОЙ ЦИКЛ СТРАТЕГИИ
# ============================================================

def strategy_loop():

    print("")
    print("=" * 60)
    print("HEIKIN ASHI RSI 33 — BYBIT BOT")
    print("=" * 60)
    print(
        f"Environment: "
        f"{'TESTNET' if TESTNET else 'LIVE'}"
    )
    print(
        f"Symbols: {', '.join(SYMBOLS)}"
    )
    print(
        f"Timeframe: {TIMEFRAME}"
    )
    print(
        f"RSI: {RSI_LENGTH} | "
        f"Entry: <{RSI_ENTRY}"
    )
    print(
        f"Position size: "
        f"{EQUITY_PERCENT * 100:.0f}% "
        f"equity × {LEVERAGE}x leverage"
    )
    print(
        "Maximum positions: "
        "1 account-wide"
    )
    print("=" * 60)
    print("")

    while True:

        try:

            for symbol in SYMBOLS:

                process_symbol(
                    symbol
                )

        except Exception as e:

            print(
                f"--> MAIN LOOP ERROR: {e}"
            )

        time.sleep(
            POLL_SECONDS
        )


# ============================================================
# RENDER HEALTH CHECK
# ============================================================

@app.route(
    "/",
    methods=["GET", "HEAD"]
)
def health():

    return jsonify({
        "status": "ok",
        "bot": "HEIKIN ASHI RSI 33",
        "environment": (
            "TESTNET"
            if TESTNET
            else "LIVE"
        ),
        "symbols": SYMBOLS,
        "timeframe": TIMEFRAME,
        "rsi_length": RSI_LENGTH,
        "rsi_entry": RSI_ENTRY,
        "equity_percent": EQUITY_PERCENT,
        "leverage": LEVERAGE,
        "max_positions": 1
    }), 200


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    # Запускаем торговую стратегию
    # в отдельном потоке
    strategy_thread = threading.Thread(
        target=strategy_loop,
        daemon=True
    )

    strategy_thread.start()

    # Render должен видеть открытый PORT
    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
