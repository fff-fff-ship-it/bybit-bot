import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)

# Чтение ключей из настроек сервера Render
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# Подключение к Bybit (unified account API)
session = HTTP(
    testnet=False, # Установите True, если хотите сначала протестировать на тестнете
    api_key=API_KEY,
    api_secret=API_SECRET,
)

@app.route('/', methods=['GET'])
def home():
    return "Bybit Webhook Server is Running!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload provided"}), 400

    try:
        # Извлекаем данные из вебхука TradingView
        symbol = data.get("symbol", "BTCUSDT")
        side = data.get("side", "Buy").capitalize()  # Buy или Sell
        qty = str(data.get("qty", "0.001"))

        # Отправка рыночного ордера на Bybit
        response = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
        )
        return jsonify({"status": "success", "response": response}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)