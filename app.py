import os
import json
import math
import threading

from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP


app = Flask(__name__)

# =========================================================
# BYBIT API
# =========================================================

API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

print("==================================================", flush=True)
print("BYBIT BOT STARTING...", flush=True)

if API_KEY:
    print("--> BYBIT_API_KEY: найден", flush=True)
else:
    print("--> BYBIT_API_KEY: НЕ НАЙДЕН", flush=True)

if API_SECRET:
    print("--> BYBIT_API_SECRET: найден", flush=True)
else:
    print("--> BYBIT_API_SECRET: НЕ НАЙДЕН", flush=True)

print("==================================================", flush=True)

session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)


# =========================================================
# НАСТРОЙКИ
# =========================================================

MARGIN_PERCENT = 0.20     # 20% текущего equity
LEVERAGE = 10             # 10x
ACCOUNT_COIN = "USDT"

# Только одна позиция на весь Unified Account
trade_lock = threading.Lock()


# =========================================================
# ЛОГ
# =========================================================

def log(message):
    print(message, flush=True)


# =========================================================
# НОРМАЛИЗАЦИЯ СИМВОЛА
# =========================================================

def normalize_symbol(symbol):
    if not symbol:
        return ""

    symbol = str(symbol).strip().upper()

    # BYBIT:BTCUSDT.P -> BTCUSDT.P
    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    # BTCUSDT.P -> BTCUSDT
    if symbol.endswith(".P"):
        symbol = symbol[:-2]

    return symbol


# =========================================================
# ПОЛУЧЕНИЕ EQUITY
# =========================================================

def get_current_equity():

    log("--> ЗАПРАШИВАЕМ БАЛАНС BYBIT...")

    response = session.get_wallet_balance(
        accountType="UNIFIED",
        coin=ACCOUNT_COIN
    )

    log(f"--> ОТВЕТ BALANCE: {response}")

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                "Не удалось получить баланс Bybit"
            )
        )

    account_list = (
        response
        .get("result", {})
        .get("list", [])
    )

    if not account_list:
        raise Exception(
            "Bybit не вернул данные Unified Account"
        )

    account = account_list[0]

    total_equity = float(
        account.get("totalEquity", "0") or 0
    )

    if total_equity <= 0:
        raise Exception(
            f"Некорректный баланс Bybit: {total_equity}"
        )

    log(f"--> CURRENT EQUITY: ${total_equity:.4f}")

    return total_equity


# =========================================================
# ПОИСК ЛЮБОЙ ОТКРЫТОЙ ПОЗИЦИИ
# =========================================================

def get_any_open_position():

    log("--> ПРОВЕРЯЕМ ВСЕ ОТКРЫТЫЕ ПОЗИЦИИ...")

    response = session.get_positions(
        category="linear",
        settleCoin=ACCOUNT_COIN
    )

    log(f"--> ОТВЕТ POSITIONS: {response}")

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                "Не удалось получить позиции Bybit"
            )
        )

    positions = (
        response
        .get("result", {})
        .get("list", [])
    )

    for position in positions:

        symbol = position.get(
            "symbol",
            ""
        )

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

            log(
                f"--> НАЙДЕНА ПОЗИЦИЯ: "
                f"{symbol} {side} qty={size}"
            )

            return position

    log("--> ОТКРЫТЫХ ПОЗИЦИЙ НЕТ")

    return None


# =========================================================
# ПОЗИЦИЯ КОНКРЕТНОЙ МОНЕТЫ
# =========================================================

def get_position(symbol):

    log(f"--> ПРОВЕРЯЕМ ПОЗИЦИЮ {symbol}...")

    response = session.get_positions(
        category="linear",
        symbol=symbol
    )

    log(f"--> ОТВЕТ POSITION {symbol}: {response}")

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                f"Ошибка получения позиции {symbol}"
            )
        )

    positions = (
        response
        .get("result", {})
        .get("list", [])
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
            return position

    return None


# =========================================================
# ПОЛУЧЕНИЕ ЦЕНЫ
# =========================================================

def get_price(symbol):

    log(f"--> ЗАПРАШИВАЕМ ЦЕНУ {symbol}...")

    response = session.get_tickers(
        category="linear",
        symbol=symbol
    )

    log(f"--> ОТВЕТ TICKER {symbol}: {response}")

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                f"Не удалось получить цену {symbol}"
            )
        )

    items = (
        response
        .get("result", {})
        .get("list", [])
    )

    if not items:
        raise Exception(
            f"Не удалось получить цену {symbol}"
        )

    price = float(
        items[0]["lastPrice"]
    )

    log(f"--> PRICE {symbol}: {price}")

    return price


# =========================================================
# РАСЧЁТ РАЗМЕРА ПОЗИЦИИ
# =========================================================

def calculate_quantity(symbol, price):

    log("--> НАЧИНАЕМ РАСЧЁТ РАЗМЕРА ПОЗИЦИИ...")

    # Equity
    equity = get_current_equity()

    # 20% equity как маржа
    margin_amount = equity * MARGIN_PERCENT

    # 10x плечо
    position_usdt = margin_amount * LEVERAGE

    # Количество монет
    raw_qty = position_usdt / price

    log(f"--> EQUITY: ${equity:.4f}")
    log(f"--> MARGIN 20%: ${margin_amount:.4f}")
    log(f"--> POSITION 10x: ${position_usdt:.4f}")
    log(f"--> RAW QTY: {raw_qty}")

    # Получаем правила инструмента
    log(f"--> ПОЛУЧАЕМ ПРАВИЛА ИНСТРУМЕНТА {symbol}...")

    response = session.get_instruments_info(
        category="linear",
        symbol=symbol
    )

    log(f"--> ОТВЕТ INSTRUMENT {symbol}: {response}")

    if response.get("retCode") != 0:
        raise Exception(
            response.get(
                "retMsg",
                f"Ошибка получения настроек {symbol}"
            )
        )

    instruments = (
        response
        .get("result", {})
        .get("list", [])
    )

    if not instruments:
        raise Exception(
            f"Bybit не нашёл инструмент {symbol}"
        )

    lot_filter = instruments[0].get(
        "lotSizeFilter",
        {}
    )

    min_qty = float(
        lot_filter.get(
            "minOrderQty",
            "0"
        )
    )

    qty_step = float(
        lot_filter.get(
            "qtyStep",
            "1"
        )
    )

    if qty_step <= 0:
        qty_step = 1

    log(f"--> MIN QTY: {min_qty}")
    log(f"--> QTY STEP: {qty_step}")

    # Округление вниз
    qty = math.floor(
        raw_qty / qty_step
    ) * qty_step

    # Минимальное количество
    if qty < min_qty:
        qty = min_qty

    if qty <= 0:
        raise Exception(
            f"Получилось некорректное количество: {qty}"
        )

    qty_string = format(
        qty,
        ".12f"
    ).rstrip("0").rstrip(".")

    log(f"--> FINAL QTY: {qty_string}")

    return {
        "equity": equity,
        "margin": margin_amount,
        "position_usdt": position_usdt,
        "qty": qty_string
    }


# =========================================================
# ОТКРЫТИЕ LONG
# =========================================================

def open_long(symbol):

    log("==================================================")
    log(f"--> OPEN LONG: {symbol}")
    log("==================================================")

    with trade_lock:

        log("--> TRADE LOCK: получен")

        # Проверяем весь аккаунт
        existing_position = get_any_open_position()

        if existing_position:

            existing_symbol = existing_position.get(
                "symbol",
                ""
            )

            existing_side = existing_position.get(
                "side",
                ""
            )

            existing_size = existing_position.get(
                "size",
                "0"
            )

            log("--> BUY ИГНОРИРУЕТСЯ")
            log(
                f"--> УЖЕ ЕСТЬ ПОЗИЦИЯ: "
                f"{existing_symbol} "
                f"{existing_side} "
                f"qty={existing_size}"
            )

            return {
                "status": "ignored",
                "reason": "position_already_open",
                "existing_symbol": existing_symbol,
                "existing_side": existing_side,
                "existing_qty": existing_size
            }

        # Цена
        price = get_price(symbol)

        # Размер позиции
        sizing = calculate_quantity(
            symbol,
            price
        )

        equity = sizing["equity"]
        margin = sizing["margin"]
        position_usdt = sizing["position_usdt"]
        qty = sizing["qty"]

        log(f"--> EQUITY: ${equity:.2f}")
        log(f"--> MARGIN 20%: ${margin:.2f}")
        log(f"--> POSITION 10x: ${position_usdt:.2f}")
        log(f"--> PRICE: {price}")
        log(f"--> LONG QTY: {qty}")

        # Отправляем ордер
        log("==================================================")
        log("--> ОТПРАВЛЯЕМ MARKET BUY В BYBIT...")
        log("==================================================")

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            positionIdx=0
        )

        log(f"--> ОТВЕТ BYBIT PLACE ORDER: {response}")

        if response.get("retCode") != 0:
            raise Exception(
                response.get(
                    "retMsg",
                    "Ошибка при открытии Bybit"
                )
            )

        log("==================================================")
        log("--> LONG УСПЕШНО ОТПРАВЛЕН В BYBIT")
        log("==================================================")

        return {
            "status": "opened",
            "symbol": symbol,
            "side": "Buy",
            "qty": qty,
            "price": price,
            "equity": equity,
            "margin": margin,
            "position_usdt": position_usdt,
            "leverage": LEVERAGE
        }


# =========================================================
# ЗАКРЫТИЕ LONG
# =========================================================

def close_long(symbol):

    log("==================================================")
    log(f"--> CLOSE LONG: {symbol}")
    log("==================================================")

    with trade_lock:

        position = get_position(symbol)

        if not position:

            log(
                f"--> CLOSE ПОЛУЧЕН, НО LONG НЕ ОТКРЫТ: {symbol}"
            )

            return {
                "status": "nothing_to_close",
                "symbol": symbol,
                "message": "Long отсутствует"
            }

        current_side = position.get(
            "side"
        )

        current_size = position.get(
            "size"
        )

        if current_side != "Buy":

            log(
                f"--> НАЙДЕНА НЕ LONG-ПОЗИЦИЯ: "
                f"{current_side} {symbol}"
            )

            return {
                "status": "ignored",
                "symbol": symbol,
                "message": "Обнаружена не Long-позиция"
            }

        log(
            f"--> ЗАКРЫВАЕМ LONG: "
            f"{symbol}, qty={current_size}"
        )

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=str(current_size),
            reduceOnly=True,
            positionIdx=0
        )

        log(
            f"--> ОТВЕТ BYBIT CLOSE ORDER: {response}"
        )

        if response.get("retCode") != 0:
            raise Exception(
                response.get(
                    "retMsg",
                    "Ошибка закрытия Bybit"
                )
            )

        log("==================================================")
        log("--> LONG УСПЕШНО ЗАКРЫТ")
        log("==================================================")

        return {
            "status": "closed",
            "symbol": symbol,
            "side": "Sell",
            "qty": current_size
        }


# =========================================================
# WEBHOOK
# =========================================================

@app.route(
    "/webhook",
    methods=["POST", "GET"]
)
def webhook():

    log("")
    log("==================================================")
    log("========== НОВЫЙ WEBHOOK ==========")
    log("==================================================")

    try:

        # -------------------------------------------------
        # Показываем HTTP данные
        # -------------------------------------------------

        log(
            f"--> METHOD: {request.method}"
        )

        log(
            f"--> CONTENT TYPE: {request.content_type}"
        )

        log(
            f"--> RAW DATA: {request.get_data(as_text=True)}"
        )

        # -------------------------------------------------
        # Получаем JSON
        # -------------------------------------------------

        data = request.get_json(
            silent=True
        )

        if not data:

            if request.data:

                try:

                    data = json.loads(
                        request.data.decode("utf-8")
                    )

                except Exception:

                    data = {
                        "raw": request.data.decode(
                            "utf-8",
                            errors="replace"
                        )
                    }

            else:

                data = request.form.to_dict()

        log(
            f"--> ПОЛУЧЕННЫЕ ДАННЫЕ: {data}"
        )

        # -------------------------------------------------
        # Проверяем, что получили словарь
        # -------------------------------------------------

        if not isinstance(data, dict):

            return jsonify({
                "status": "error",
                "message": "Webhook должен содержать JSON object"
            }), 400

        # -------------------------------------------------
        # SYMBOL
        # -------------------------------------------------

        raw_symbol = data.get(
            "symbol",
            data.get(
                "символ",
                ""
            )
        )

        symbol = normalize_symbol(
            raw_symbol
        )

        log(
            f"--> RAW SYMBOL: {raw_symbol}"
        )

        log(
            f"--> NORMALIZED SYMBOL: {symbol}"
        )

        # -------------------------------------------------
        # ACTION
        # -------------------------------------------------

        raw_action = data.get(
            "action",
            data.get(
                "действие",
                ""
            )
        )

        action = str(
            raw_action
        ).strip().lower()

        log(
            f"--> RAW ACTION: {raw_action}"
        )

        log(
            f"--> ACTION: {action}"
        )

        # -------------------------------------------------
        # Проверка SYMBOL
        # -------------------------------------------------

        if not symbol:

            log("--> ОШИБКА: SYMBOL НЕ УКАЗАН")

            return jsonify({
                "status": "error",
                "message": "Не указан symbol"
            }), 400

        # -------------------------------------------------
        # Проверка ACTION
        # -------------------------------------------------

        if not action:

            log("--> ОШИБКА: ACTION НЕ УКАЗАН")

            return jsonify({
                "status": "error",
                "message": "Не указан action"
            }), 400

        # -------------------------------------------------
        # BUY
        # -------------------------------------------------

        if action in [
            "buy",
            "купить",
            "long"
        ]:

            log(
                f"--> ПОЛУЧЕН BUY СИГНАЛ: {symbol}"
            )

            result = open_long(
                symbol
            )

            log(
                f"--> РЕЗУЛЬТАТ BUY: {result}"
            )

            return jsonify(
                result
            ), 200

        # -------------------------------------------------
        # SELL / CLOSE
        # -------------------------------------------------

        if action in [
            "sell",
            "продать",
            "exit",
            "close"
        ]:

            log(
                f"--> ПОЛУЧЕН SELL/CLOSE СИГНАЛ: {symbol}"
            )

            result = close_long(
                symbol
            )

            log(
                f"--> РЕЗУЛЬТАТ CLOSE: {result}"
            )

            return jsonify(
                result
            ), 200

        # -------------------------------------------------
        # НЕИЗВЕСТНАЯ КОМАНДА
        # -------------------------------------------------

        log(
            f"--> НЕИЗВЕСТНОЕ ACTION: {action}"
        )

        return jsonify({
            "status": "error",
            "message": f"Неизвестное действие: {action}"
        }), 400

    # =====================================================
    # ЛЮБАЯ ОШИБКА
    # =====================================================

    except Exception as e:

        log("==================================================")
        log("--> КРИТИЧЕСКАЯ ОШИБКА WEBHOOK")
        log(f"--> {type(e).__name__}: {e}")
        log("==================================================")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route(
    "/",
    methods=["GET", "HEAD"]
)
def health():

    return jsonify({
        "status": "ok",
        "message": "Бот Bybit запущен"
    }), 200


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    log("==================================================")
    log(f"--> START FLASK SERVER ON PORT {port}")
    log("==================================================")

    app.run(
        host="0.0.0.0",
        port=port
    )
