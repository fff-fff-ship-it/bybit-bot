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

RISK_USD = 2.0
STOP_LOSS_PERCENT = 0.8


@app.route("/", methods=["GET", "HEAD", "POST"])
def home():
    return jsonify({"status": "ok", "message": "Bybit bot is running"}), 200


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    try:
        # Получаем данные от TradingView
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

        # Символ
        symbol = str(data.get("symbol", "")).strip().upper()

        # Убираем только суффикс TradingView .P
        if symbol.endswith(".P"):
            symbol = symbol[:-2]

        # Действие
        action = str(
            data.get("action", data.get("действие", ""))
        ).strip().lower()

        if not symbol or not action:
            return jsonify({
                "status": "error",
                "message": "Отсутствует symbol или action"
            }), 400

        # Нормализуем BUY / SELL
        if action in ["buy", "купить", "long"]:
            side = "Buy"
        elif action in ["sell", "продать", "short"]:
            side = "Sell"
        else:
            return jsonify({
                "status": "error",
                "message": f"Неизвестное действие: {action}"
            }), 400

        print(f"--> МОНЕТА: {symbol}")
        print(f"--> СТОРОНА: {side}")

        # Получаем информацию о торговом инструменте
        info = session.get_instruments_info(
            category="linear",
            symbol=symbol
        )

        instruments = info.get("result", {}).get("list", [])

        if not instruments:
            return jsonify({
                "status": "error",
                "message": f"Монета {symbol} не найдена на Bybit Linear"
            }), 400

        instrument = instruments[0]

        lot_filter = instrument.get("lotSizeFilter", {})

        qty_step = float(lot_filter.get("qtyStep", "1"))
        min_qty = float(lot_filter.get("minOrderQty", "0"))

        # Получаем текущую цену
        ticker = session.get_tickers(
            category="linear",
            symbol=symbol
        )

        ticker_list = ticker.get("result", {}).get("list", [])

        if not ticker_list:
            return jsonify({
                "status": "error",
                "message": f"Не удалось получить цену {symbol}"
            }), 400

        price = float(ticker_list[0]["lastPrice"])

        # Риск $2 при стопе 0.8%
        stop_distance = price * (STOP_LOSS_PERCENT / 100)

        qty = RISK_USD / stop_distance

        # Округление количества по шагу монеты
        qty = math.floor(qty / qty_step) * qty_step

        # Если количество получилось меньше минимального
        if qty < min_qty:
            qty = min_qty

        # Нормальное форматирование количества
        qty = format(qty, ".12f").rstrip("0").rstrip(".")

        print(f"--> ЦЕНА: {price}")
        print(f"--> РИСК: ${RISK_USD}")
        print(f"--> СТОП: {STOP_LOSS_PERCENT}%")
        print(f"--> КОЛИЧЕСТВО: {qty}")

        # Отправляем ордер на Bybit
        response = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )

        print(f"--> ОТВЕТ BYBIT: {response}")

        ret_code = response.get("retCode", -1)

        if ret_code == 0:
            print("--> ОРДЕР УСПЕШНО ОТПРАВЛЕН НА BYBIT")

            return jsonify({
                "status": "success",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "risk_usd": RISK_USD,
                "response": response
            }), 200

        return jsonify({
            "status": "error",
            "message": response.get("retMsg", "Ошибка Bybit"),
            "response": response
        }), 400

    except Exception as e:
        print(f"--> ОШИБКА ОПЕРАЦИИ: {e}")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
