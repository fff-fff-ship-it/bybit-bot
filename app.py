import os
import json
import math
import threading

from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP


app = Flask(__name__)

API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)


# =========================
# НАСТРОЙКИ СТРАТЕГИИ
# =========================

MARGIN_PERCENT = 0.05       # 5% текущего equity
LEVERAGE = 3                # x3 плечо
ACCOUNT_COIN = "USDT"

trade_lock = threading.Lock()


# =========================
# НОРМАЛИЗАЦИЯ СИМВОЛА
# =========================

def normalize_symbol(symbol):
    if not symbol:
        return ""
    symbol = str(symbol).strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    if symbol.endswith(".P"):
        symbol = symbol[:-2]
    return symbol


# =========================
# ПОЛУЧЕНИЕ EQUITY
# =========================

def get_current_equity():
    response = session.get_wallet_balance(
        accountType="UNIFIED",
        coin=ACCOUNT_COIN
    )
    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", "Не удалось получить баланс Bybit"))

    account_list = response.get("result", {}).get("list", [])
    if not account_list:
        raise Exception("Bybit не вернул данные Unified Account")

    total_equity = float(account_list[0].get("totalEquity", "0") or 0)
    if total_equity <= 0:
        raise Exception(f"Некорректный equity Bybit: {total_equity}")
    return total_equity


# =========================
# РАБОТА С ПОЗИЦИЯМИ
# =========================

def get_position(symbol):
    response = session.get_positions(
        category="linear",
        symbol=symbol
    )
    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", f"Ошибка получения позиции {symbol}"))

    positions = response.get("result", {}).get("list", [])
    for position in positions:
        side = position.get("side", "")
        size = float(position.get("size", "0") or 0)
        if size > 0 and side in ["Buy", "Sell"]:
            return position
    return None


def get_price(symbol):
    response = session.get_tickers(
        category="linear",
        symbol=symbol
    )
    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", f"Не удалось получить цену {symbol}"))

    items = response.get("result", {}).get("list", [])
    if not items:
        raise Exception(f"Не удалось получить цену {symbol}")
    return float(items[0]["lastPrice"])


def calculate_quantity(symbol, price):
    equity = get_current_equity()
    margin_amount = equity * MARGIN_PERCENT
    position_usdt = margin_amount * LEVERAGE
    raw_qty = position_usdt / price

    response = session.get_instruments_info(
        category="linear",
        symbol=symbol
    )
    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", f"Ошибка получения настроек {symbol}"))

    instruments = response.get("result", {}).get("list", [])
    if not instruments:
        raise Exception(f"Bybit не нашёл инструмент {symbol}")

    lot_filter = instruments[0].get("lotSizeFilter", {})
    min_qty = float(lot_filter.get("minOrderQty", "0"))
    qty_step = float(lot_filter.get("qtyStep", "1"))
    if qty_step <= 0:
        qty_step = 1

    qty = math.floor(raw_qty / qty_step) * qty_step
    if qty < min_qty:
        qty = min_qty
    if qty <= 0:
        raise Exception(f"Получилось некорректное количество: {qty}")

    return format(qty, ".12f").rstrip("0").rstrip(".")


# =========================
# ИСПОЛНЕНИЕ ОРДЕРОВ
# =========================

def execute_signal(symbol, target_side):
    """
    Универсальная логика: открывает позицию нужного направления 
    или переворачивает существующую с учетом reduceOnly.
    """
    with trade_lock:
        position = get_position(symbol)
        
        if position:
            current_side = position.get("side") # "Buy" или "Sell"
            current_size = position.get("size")
            
            # Если уже стоим в нужном направлении — ничего не делаем
            if current_side == target_side:
                print(f"--> Позиция {symbol} уже в {target_side}, игнорируем.")
                return {"status": "ignored", "message": "Already in position"}

            # Если направление противоположное — закрываем текущую перед открытием новой
            closing_side = "Sell" if current_side == "Buy" else "Buy"
            print(f"--> Переворот позиции по {symbol}: закрываем {current_side}, открываем {target_side}")
            
            session.place_order(
                category="linear",
                symbol=symbol,
                side=closing_side,
                orderType="Market",
                qty=str(current_size),
                reduceOnly=True,
                positionIdx=0
            )

        # Открываем новую позицию (или входим с нуля)
        price = get_price(symbol)
        qty = calculate_quantity(symbol, price)

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side=target_side,
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            positionIdx=0
        )

        print(f"--> Успешно открыт {target_side} по {symbol}, qty: {qty}, ответ: {response}")
        return {"status": "success", "symbol": symbol, "side": target_side, "qty": qty}


def close_position(symbol):
    with trade_lock:
        position = get_position(symbol)
        if not position:
            return {"status": "ignored", "message": "No position to close"}

        current_side = position.get("side")
        current_size = position.get("size")
        closing_side = "Sell" if current_side == "Buy" else "Buy"

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side=closing_side,
            orderType="Market",
            qty=str(current_size),
            reduceOnly=True,
            positionIdx=0
        )
        print(f"--> Позиция {symbol} закрыта: {response}")
        return {"status": "closed", "symbol": symbol}


# =========================
# WEBHOOK
# =========================

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    try:
        data = request.get_json(silent=True) or (
            json.loads(request.data.decode("utf-8")) if request.data else request.form.to_dict()
        )
        print(f"--> СИГНАЛ ОТ TRADINGVIEW: {data}")

        symbol = normalize_symbol(data.get("symbol", ""))
        action = str(data.get("action", data.get("действие", ""))).strip().lower()

        if not symbol:
            return jsonify({"status": "error", "message": "Не указан symbol"}), 400

        # Обработка Лонга
        if action in ["buy", "купить", "long"]:
            result = execute_signal(symbol, "Buy")
            return jsonify(result), 200

        # Обработка Шорта
        if action in ["sell", "продать", "short"]:
            result = execute_signal(symbol, "Sell")
            return jsonify(result), 200

        # Обработка закрытия
        if action in ["exit", "close", "закрыть"]:
            result = close_position(symbol)
            return jsonify(result), 200

        return jsonify({"status": "error", "message": f"Неизвестное действие: {action}"}), 400

    except Exception as e:
        print(f"--> ОШИБКА: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200


@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "ok", "message": "Bot is running"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
