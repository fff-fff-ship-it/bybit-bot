import os
import json
import math

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
CAPITAL_PERCENT = 0.2  # 20% от депозита на 1 монету
LEVERAGE = 10          # Плечо 10x


def normalize_symbol(symbol):
    if not symbol:
        return ""
    symbol = str(symbol).strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    if symbol.endswith(".P"):
        symbol = symbol[:-2]
    return symbol


def get_position(symbol):
    response = session.get_positions(
        category="linear",
        symbol=symbol
    )
    positions = response.get("result", {}).get("list", [])
    for position in positions:
        side = position.get("side", "")
        size = float(position.get("size", "0") or 0)
        if size > 0 and side in ["Buy", "Sell"]:
            return position
    return None


def calculate_quantity(symbol, price):
    wallet_balance = 0.0
    try:
        wallet_resp = session.get_wallet_balance(
            accountType="UNIFIED",
            coin="USDT"
        )
        coins = wallet_resp.get("result", {}).get("list", [])
        if coins:
            wallet_balance = float(coins[0].get("equity", 0) or 0)
    except Exception as e:
        print(f"--> Ошибка получения баланса: {e}, используем дефолт")

    if wallet_balance <= 0:
        wallet_balance = 100.0

    target_position_usdt = wallet_balance * CAPITAL_PERCENT * LEVERAGE
    raw_qty = target_position_usdt / price

    response = session.get_instruments_info(
        category="linear",
        symbol=symbol
    )
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

    return format(qty, ".12f").rstrip("0").rstrip(".")


def open_long(symbol):
    position = get_position(symbol)
    if position:
        current_side = position.get("side")
        current_size = position.get("size")
        if current_side == "Buy":
            print(f"--> LONG УЖЕ ОТКРЫТ: {symbol}, qty={current_size}")
            return {"status": "already_open", "symbol": symbol, "qty": current_size}

    tickers = session.get_tickers(category="linear", symbol=symbol)
    items = tickers.get("result", {}).get("list", [])
    if not items:
        raise Exception(f"Не удалось получить цену {symbol}")
    price = float(items[0]["lastPrice"])

    qty = calculate_quantity(symbol, price)
    print(f"--> ОТКРЫТИЕ LONG: {symbol}, Цена: {price}, Qty: {qty}")

    response = session.place_order(
        category="linear",
        symbol=symbol,
        side="Buy",
        orderType="Market",
        qty=qty,
        timeInForce="GoodTillCancel",
        positionIdx=0
    )

    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", "Ошибка Bybit"))

    return {"status": "opened", "symbol": symbol, "qty": qty, "price": price}


def close_long(symbol):
    position = get_position(symbol)
    if not position:
        print(f"--> Сигнал закрытия, но позиция LONG отсутствует: {symbol}")
        return {"status": "nothing_to_close", "symbol": symbol}

    current_size = position.get("size")
    print(f"--> ЗАКРЫВАЕМ LONG: {symbol}, qty={current_size}")

    response = session.place_order(
        category="linear",
        symbol=symbol,
        side="Sell",
        orderType="Market",
        qty=str(current_size),
        reduceOnly=True,
        positionIdx=0
    )

    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", "Ошибка закрытия Bybit"))

    return {"status": "closed", "symbol": symbol, "qty": current_size}


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        if not data and request.data:
            try:
                data = json.loads(request.data.decode("utf-8"))
            except Exception:
                data = {"raw": request.data.decode("utf-8")}

        symbol = normalize_symbol(data.get("symbol", ""))
        action = str(data.get("action", data.get("действие", ""))).strip().lower()

        print(f"--> СИГНАЛ: символ={symbol}, действие={action}")

        if not symbol or not action:
            return jsonify({"status": "error", "message": "Нет symbol или action"}), 400

        if action in ["buy", "купить", "long"]:
            result = open_long(symbol)
            return jsonify(result), 200

        if action in ["sell", "продать", "exit", "close"]:
            result = close_long(symbol)
            return jsonify(result), 200

        return jsonify({"status": "error", "message": f"Неизвестное действие: {action}"}), 400

    except Exception as e:
        print(f"--> ОШИБКА: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200


@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "ok", "message": "RSI Bybit Bot is running"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
