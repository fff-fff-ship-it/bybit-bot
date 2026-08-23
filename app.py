import os
import json

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
# НОРМАЛИЗАЦИЯ СИМВОЛА
# =========================

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


# =========================
# ПОЛУЧЕНИЕ ПОЗИЦИИ
# =========================

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


# =========================
# ОТКРЫТИЕ LONG (ПО ОБЪЕМУ ИЗ TV)
# =========================

def open_long(symbol, qty):
    position = get_position(symbol)

    if position:
        current_side = position.get("side")
        current_size = position.get("size")

        if current_side == "Buy":
            print(f"--> LONG УЖЕ ОТКРЫТ: {symbol}, qty={current_size}")
            return {
                "status": "already_open",
                "symbol": symbol,
                "side": "Buy",
                "qty": current_size
            }

        if current_side == "Sell":
            print(f"--> НАЙДЕН SHORT {symbol}, ЗАКРЫВАЕМ ЕГО ПЕРЕД LONG")
            close_response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=str(current_size),
                reduceOnly=True,
                positionIdx=0
            )
            print(f"--> SHORT ЗАКРЫТ: {close_response}")

    print(f"--> ОТКРЫВАЕМ LONG {symbol}, QTY: {qty}")

    # Отправляем ордер на Bybit с точным количеством из TradingView
    response = session.place_order(
        category="linear",
        symbol=symbol,
        side="Buy",
        orderType="Market",
        qty=str(qty),
        timeInForce="GoodTillCancel",
        positionIdx=0
    )

    print(f"--> LONG ОТПРАВЛЕН: {response}")

    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", "Ошибка Bybit"))

    return {
        "status": "opened",
        "symbol": symbol,
        "side": "Buy",
        "qty": qty
    }


# =========================
# ЗАКРЫТИЕ LONG
# =========================

def close_long(symbol):
    position = get_position(symbol)

    if not position:
        print(f"--> SELL ПОЛУЧЕН, НО LONG НЕ ОТКРЫТ: {symbol}")
        return {
            "status": "nothing_to_close",
            "symbol": symbol,
            "message": "Long отсутствует"
        }

    current_side = position.get("side")
    current_size = position.get("size")

    if current_side != "Buy":
        print(f"--> НАЙДЕН НЕ LONG: {current_side} {symbol}")
        return {
            "status": "ignored",
            "symbol": symbol,
            "message": "Обнаружена не Long-позиция"
        }

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

    print(f"--> LONG ЗАКРЫТ: {response}")

    if response.get("retCode") != 0:
        raise Exception(response.get("retMsg", "Ошибка закрытия Bybit"))

    return {
        "status": "closed",
        "symbol": symbol,
        "side": "Sell",
        "qty": current_size
    }


# =========================
# WEBHOOK
# =========================

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    try:
        data = request.get_json(silent=True)

        if not data:
            if request.data:
                try:
                    data = json.loads(request.data.decode("utf-8"))
                except Exception:
                    data = {"raw": request.data.decode("utf-8")}
            else:
                data = request.form.to_dict()

        print(f"--> ПОЛУЧЕН СИГНАЛ ОТ TRADINGVIEW: {data}")

        symbol = normalize_symbol(data.get("symbol", ""))
        action = str(data.get("action", data.get("действие", ""))).strip().lower()
        
        # Получаем количество монет, переданное из TradingView
        qty = data.get("qty", data.get("contracts", 0))

        print(f"--> SYMBOL: {symbol}")
        print(f"--> ACTION: {action}")
        print(f"--> QTY FROM TV: {qty}")

        if not symbol:
            return jsonify({"status": "error", "message": "Не указан symbol"}), 400

        if not action:
            return jsonify({"status": "error", "message": "Не указан action"}), 400

        # BUY / LONG
        if action in ["buy", "купать", "long"]:
            if not qty or float(qty) <= 0:
                return jsonify({"status": "error", "message": "Не указан или нулевой qty"}), 400
            
            result = open_long(symbol, qty)
            return jsonify(result), 200

        # SELL / CLOSE
        if action in ["sell", "продать", "exit", "close"]:
            result = close_long(symbol)
            return jsonify(result), 200

        return jsonify({"status": "error", "message": f"Неизвестное действие: {action}"}), 400

    except Exception as e:
        print(f"--> ОШИБКА ОПЕРАЦИИ: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200


# =========================
# HEALTH CHECK
# =========================

@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "ok", "message": "Bybit bot is running"}), 200


# =========================
# ЗАПУСК
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
