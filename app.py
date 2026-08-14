import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)

# ============================================================
# BYBIT API KEYS
# ============================================================

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

if not API_KEY or not API_SECRET:
    print("WARNING: BYBIT_API_KEY or BYBIT_API_SECRET is not set")


# ============================================================
# BYBIT CONNECTION
# ============================================================

session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET,
)


# ============================================================
# MAIN PAGE
# ============================================================

@app.route("/", methods=["GET"])
def home():
    return "Bybit Webhook Server is Running!", 200


# ============================================================
# WEBHOOK
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "status": "error",
                "message": "No JSON payload provided"
            }), 400

        print("WEBHOOK RECEIVED:", data)

        # ----------------------------------------------------
        # SYMBOL
        # ----------------------------------------------------

        raw_symbol = str(data.get("symbol", "BTCUSDT"))

        # TradingView может присылать AKEUSDT.P
        symbol = raw_symbol.replace(".P", "").upper()

        # ----------------------------------------------------
        # ACTION
        # ----------------------------------------------------

        action = str(data.get("action", "")).lower().strip()

        # ----------------------------------------------------
        # QTY
        # ----------------------------------------------------

        qty = str(data.get("qty", "")).strip()

        print("SYMBOL:", symbol)
        print("ACTION:", action)
        print("QTY:", qty)

        # ====================================================
        # BUY = OPEN LONG
        # ====================================================

        if action == "buy":

            if not qty or qty == "0":
                return jsonify({
                    "status": "error",
                    "message": "Quantity is empty or zero",
                    "symbol": symbol
                }), 400

            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty
            )

            print("BUY RESPONSE:", response)

            return jsonify({
                "status": "success",
                "action": "buy",
                "symbol": symbol,
                "qty": qty,
                "response": response
            }), 200


        # ====================================================
        # SELL / CLOSE = CLOSE LONG
        # ====================================================

        elif action in ["sell", "close"]:

            # Получаем текущую позицию
            pos_info = session.get_positions(
                category="linear",
                symbol=symbol
            )

            print("POSITION RESPONSE:", pos_info)

            positions = (
                pos_info
                .get("result", {})
                .get("list", [])
            )

            close_qty = "0"

            # Ищем открытую позицию
            for pos in positions:

                position_size = float(
                    pos.get("size", 0) or 0
                )

                if position_size > 0:

                    close_qty = str(
                        pos.get("size")
                    )

                    break


            # ------------------------------------------------
            # Позиции нет
            # ------------------------------------------------

            if float(close_qty) <= 0:

                return jsonify({
                    "status": "ignored",
                    "message": "No open position found to close",
                    "symbol": symbol
                }), 200


            # ------------------------------------------------
            # Закрываем LONG
            # ------------------------------------------------

            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=close_qty,
                reduceOnly=True
            )

            print("CLOSE RESPONSE:", response)

            return jsonify({
                "status": "success",
                "action": "close",
                "symbol": symbol,
                "qty": close_qty,
                "response": response
            }), 200


        # ====================================================
        # UNKNOWN ACTION
        # ====================================================

        else:

            return jsonify({
                "status": "error",
                "message": f"Unknown action: {action}",
                "symbol": symbol,
                "received_data": data
            }), 400


    # ========================================================
    # ERROR
    # ========================================================

    except Exception as e:

        print("WEBHOOK ERROR:", str(e))

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
