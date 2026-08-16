import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)

API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

@app.route("/", methods=["GET", "HEAD", "POST"])
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
   try:
        # Пытаемся получить данные как JSON или принудительно парсим текст
        data = request.get_json(silent=True)
        if not data:
            if request.data:
                import json
                try:
                    data = json.loads(request.data.decode('utf-8'))
                except:
                    data = {"raw": request.data.decode('utf-8')}
            else:
                data = request.form.to_dict()

        print(f"--> ПОЛУЧЕН СИГНАЛ ОТ TRADINGVIEW: {data}")

        symbol = data.get("symbol")
        action = data.get("action")
        action = data.get("action")
        
        if symbol and action:
            side = "Buy" if action.lower() == "buy" else "Sell"
            response = session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty="1",
                timeInForce="GoodTillCancel"
            )
            print(f"--> ОРДЕР УСПЕШНО ОТПРАВЛЕН НА BYBIT: {response}")
        
        return jsonify({"status": "success", "received_data": data}), 200
        
    except Exception as e:
        print(f"--> ОШИБКА ОПЕРАЦИИ: {e}")
        # Возвращаем 200 даже при ошибке ордера, чтобы TradingView больше никогда не писал 404/400
        return jsonify({"status": "error", "message": str(e)}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
