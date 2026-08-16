import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "online"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    # Принимаем любые данные от TradingView, даже если заголовки не идеальные
    data = request.get_json(silent=True)
    
    if not data:
        # Если пришел чистый текст или нестандартный формат
        data = request.form.to_dict()
    
    print(f"ПОЛУЧЕН СИГНАЛ ОТ TRADINGVIEW: {data}")

    # Здесь в будущем будет вызов Bybit API
    
    return jsonify({
        "status": "success",
        "received_data": data
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
