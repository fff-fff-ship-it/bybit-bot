import os
from flask import Flask, request, jsonify

app = Flask(__name__)

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
        
        return jsonify({
            "status": "success",
            "received_data": data
        }), 200
        
    except Exception as e:
        print(f"--> ОШИБКА В ВЕБХУКЕ: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
