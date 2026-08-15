import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)


# =========================================================
# BYBIT SETTINGS
# =========================================================

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# Для тестовой сети: BYBIT_TESTNET=true
# Для реального Bybit: BYBIT_TESTNET=false
TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"


if not API_KEY or not API_SECRET:
    print("WARNING: BYBIT_API_KEY или BYBIT_API_SECRET не заданы")


session = HTTP(
    testnet=TESTNET,
    api_key=API_KEY,
    api_secret=API_SECRET
)


# =========================================================
# MAIN PAGE
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "Bybit Webhook Server is running", 200


# =========================================================
# SYMBOL NORMALIZATION
# =========================================================

def normalize_symbol(raw_symbol):
    """
    TradingView может прислать:
        AKEUSDT.P
        BYBIT:AKEUSDT.P
        AKEUSDT

    Bybit для linear использует:
        AKEUSDT
    """

    symbol = str(raw_symbol or "").strip().upper()

    # Убираем название биржи
    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    # Убираем .P от TradingView
    if symbol.endswith(".P"):
        symbol = symbol[:-2]

    return symbol


# =========================================================
# GET CURRENT LONG POSITION
# =========================================================

def get_long_position(symbol):
    """
    Получаем текущую позицию по символу.
    Возвращаем размер Long.
    """

    response = session.get_positions(
        category="linear",
        symbol=symbol
    )

    print("POSITION RESPONSE:", response)

    positions = response.get("result", {}).get("list", [])

    for position in positions:
        side = position.get("side", "")
        size = float(position.get("size", 0) or 0)

        if side == "Buy" and size > 0:
            return size

    return 0.0


# =========================================================
# WEBHOOK ENDPOINT
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        # -------------------------------------------------
        # RECEIVE JSON (force=True спасает от ошибок формата)
        # -------------------------------------------------

        data = request.get_json(force=True, silent=True) or {}

        print("==============================================")
        print("WEBHOOK RECEIVED:")
        print(data)
        print("==============================================")

        if not data:
            return jsonify({
                "status": "error",
                "message": "JSON body is empty or invalid"
            }), 400


        # -------------------------------------------------
        # READ DATA
        # -------------------------------------------------

        raw_symbol = data.get("symbol", "")
        action = str(data.get("action", "")).lower().strip()
        qty_raw = data.get("qty", 0)


        # -------------------------------------------------
        # NORMALIZE SYMBOL
        # -------------------------------------------------

        symbol = normalize_symbol(raw_symbol)


        # -------------------------------------------------
        # QTY
        # -------------------------------------------------

        try:
            qty = float(qty_raw)
        except Exception:
            qty = 0.0


        print("SYMBOL:", symbol)
        print("ACTION:", action)
        print("QTY:", qty)


        # =================================================
        # TEST SIGNAL
        # =================================================

        if action == "test":

            print("==============================================")
            print("TEST SIGNAL OK")
            print("NO ORDER WILL BE SENT TO BYBIT")
            print("==============================================")

            return jsonify({
                "status": "success",
                "message": "test signal received",
                "symbol": symbol,
                "qty": qty
            }), 200


        # =================================================
        # BUY / OPEN LONG
        # =================================================

        if action == "buy":

            if qty <= 0:
                return jsonify({
                    "status": "error",
                    "message": "Invalid quantity",
                    "symbol": symbol,
                    "qty": qty
                }), 400


            print("==============================================")
            print("OPENING LONG")
            print("SYMBOL:", symbol)
            print("QTY:", qty)
            print("==============================================")


            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=str(qty)
            )


            print("BUY RESPONSE:")
            print(response)


            return jsonify({
                "status": "success",
                "action": "buy",
                "symbol": symbol,
                "qty": qty,
                "response": response
            }), 200


        # =================================================
        # CLOSE LONG
        # =================================================

        if action == "close":

            print("==============================================")
            print("CLOSING LONG")
            print("SYMBOL:", symbol)
            print("==============================================")


            current_qty = get_long_position(symbol)


            if current_qty <= 0:

                print("NO LONG POSITION FOUND")

                return jsonify({
                    "status": "ignored",
                    "message": "No open long position",
                    "symbol": symbol
                }), 200


            print("CURRENT LONG SIZE:", current_qty)


            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=str(current_qty),
                reduceOnly=True
            )


            print("CLOSE RESPONSE:")
            print(response)


            return jsonify({
                "status": "success",
                "action": "close",
                "symbol": symbol,
                "qty": current_qty,
                "response": response
            }), 200


        # =================================================
        # SELL
        # =================================================

        if action == "sell":

            if qty <= 0:
                return jsonify({
                    "status": "error",
                    "message": "Invalid quantity",
                    "symbol": symbol,
                    "qty": qty
                }), 400


            print("==============================================")
            print("OPENING SHORT")
            print("SYMBOL:", symbol)
            print("QTY:", qty)
            print("==============================================")


            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=str(qty)
            )


            print("SELL RESPONSE:")
            print(response)


            return jsonify({
                "status": "success",
                "action": "sell",
                "symbol": symbol,
                "qty": qty,
                "response": response
            }), 200


        # =================================================
        # UNKNOWN ACTION
        # =================================================

        print("UNKNOWN ACTION:", action)

        return jsonify({
            "status": "error",
            "message": f"Unknown action: {action}",
            "symbol": symbol,
            "received_data": data
        }), 400


    # =====================================================
    # GENERAL ERROR
    # =====================================================

    except Exception as e:

        print("==============================================")
        print("WEBHOOK ERROR:")
        print(str(e))
        print("==============================================")


        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    print("==============================================")
    print("BYBIT WEBHOOK SERVER STARTING")
    print("PORT:", port)
    print("TESTNET:", TESTNET)
    print("==============================================")


    app.run(
        host="0.0.0.0",
        port=port
    )
