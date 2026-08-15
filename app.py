import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)

# Инициализация клиента Bybit
session = HTTP(
    testnet=False,
    api_key=os.environ.get("BYBIT_API_KEY"),
    api_secret=os.environ.get("BYBIT_API_SECRET")
)

# Этот маршрут нужен для UptimeRobot, он понимает и GET, и HEAD
@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No data received"}), 400

    secret_key = os.environ.get("WEBHOOK_SECRET")
    if secret_key and data.get("secret") != secret_key:
        return jsonify({"status": "error", "message": "Invalid secret key"}), 403

    symbol = data.get("symbol")
    action = data.get("action")
    position_size = data.get("position_size")
    stop_loss = data.get("stop_loss")
    take_profit = data.get("take_profit")

    if not symbol or not action:
        return jsonify({"status": "error", "message": "Missing symbol or action"}), 400

    side = "Buy" if "buy" in action.lower() or "long" in action.lower() else "Sell"

    try:
        # Для закрытия позиции (exit)
        if "exit" in action.lower() or "close" in action.lower():
            session.cancel_all_orders(category="linear", symbol=symbol)
            side_to_close = "Sell" if "long" in action.lower() else "Buy"
            response = session.place_order(
                category="linear",
                symbol=symbol,
                side=side_to_close,
                orderType="Market",
                qty=position_size,
                reduceOnly=True
            )
            return jsonify({"status": "success", "response": response}), 200

        # Для открытия позиции
        order_params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": str(position_size)
        }

        if stop_loss:
            order_params["stopLoss"] = str(stop_loss)
        if take_profit:
            order_params["takeProfit"] = str(take_profit)

        response = session.place_order(**order_params)
        return jsonify({"status": "success", "response": response}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
