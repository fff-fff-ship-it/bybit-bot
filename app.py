import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)

# Получаем ключи из переменных окружения Render
API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

# Инициализируем клиент Bybit (True означает демо/тестнет, False — реальный счет. По умолчанию ставим False для реала, или True, если тестируете на демо)
session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)

@app.route("/", methods=["GET", "HEAD", "POST"])
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            data = request.form.to_dict()
        if not data and request.data:
            data = {"raw_data": request.data.decode('utf-8')}
        
        print(f"--> ПОЛУЧЕН СИГНАЛ ОТ TRADINGVIEW: {data}")
        
        # Извлекаем данные из алерта TradingView
        symbol = data.get("symbol")
        action = data.get("action")  # 'buy' или 'sell'
        
        if symbol and action:
            # Превращаем 'buy'/'sell' в формат Bybit ('Buy'/'Sell')
            side = "Buy" if action.lower() == "buy" else "Sell"
            
            # Отправляем рыночный ордер на Bybit
            # Количество контрактов или размер позиции можно настроить под себя
            response = session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty="1",  # Укажите нужное количество контрактов или лотов
                timeInForce="GoodTillCancel"
            )
            print(f"--> ОРДЕР УСПЕШНО ОТПРАВЛЕН НА BYBIT: {response}")
        
        return jsonify({"status": "success", "received_data": data}), 200
        
    except Exception as e:
        print(f"--> ОШИБКА ОПЕРАЦИИ: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
