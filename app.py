import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP


app = Flask(__name__)


# ============================================================
# BYBIT
# ============================================================

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# Для реального Bybit:
# BYBIT_TESTNET=false
#
# Для тестовой сети:
# BYBIT_TESTNET=true
TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"


if not API_KEY or not API_SECRET:
    print("WARNING: BYBIT_API_KEY или BYBIT_API_SECRET не заданы")


session = HTTP(
    testnet=TESTNET,
    api_key=API_KEY,
    api_secret=API_SECRET,
)


# ============================================================
# ГЛАВНАЯ
# ============================================================

@app.route("/", methods=["GET"])
def home():
    return "Сервер Bybit Webhook запущен", 200


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def normalize_symbol(raw_symbol):
    """
    TradingView может прислать, например:
    AKEUSDT.P

    Bybit для linear использует:
    AKEUSDT
    """

    if not raw_symbol:
        return ""

    symbol = str(raw_symbol).strip().upper()

    # Убираем суффикс perpetual от TradingView
    symbol = symbol.replace(".P", "")

    return symbol


def normalize_action(raw_action):
    """
    Приводим действие TradingView к:
    buy / sell / close
    """

    if raw_action is None:
        return ""

    return str(raw_action).strip().lower()


def normalize_qty(raw_qty):
    """
    Количество должно быть положительным.
    Возвращаем строку — Bybit API принимает qty как string.
    """

    if raw_qty is None:
        return ""

    try:
        qty = float(raw_qty)
    except (ValueError, TypeError):
        return ""

    if qty <= 0:
        return ""

    # Не используем научную запись
    return format(qty, "f").rstrip("0").rstrip(".")


def bybit_error_response(response):
    """
    Проверяем настоящий ответ Bybit.
    retCode == 0 означает успешное принятие запроса.
    """

    if not isinstance(response, dict):
        return {
            "ok": False,
            "retCode": -1,
            "retMsg": "Bybit вернул ответ неизвестного формата",
        }

    ret_code = response.get("retCode", -1)
    ret_msg = response.get("retMsg", "")

    if ret_code != 0:
        return {
            "ok": False,
            "retCode": ret_code,
            "retMsg": ret_msg,
        }

    return {
        "ok": True,
        "retCode": 0,
        "retMsg": ret_msg or "OK",
    }


def get_position(symbol):
    """
    Получаем текущую позицию по символу.
    """

    response = session.get_positions(
        category="linear",
        symbol=symbol
    )

    check = bybit_error_response(response)

    if not check["ok"]:
        raise RuntimeError(
            f"Bybit get_positions error "
            f"{check['retCode']}: {check['retMsg']}"
        )

    positions = (
        response
        .get("result", {})
        .get("list", [])
    )

    # Ищем реально открытую позицию
    for position in positions:
        try:
            size = float(position.get("size", 0) or 0)
        except (ValueError, TypeError):
            size = 0

        if size > 0:
            return position

    return None


# ============================================================
# WEBHOOK TRADINGVIEW
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        # ----------------------------------------------------
        # Получаем JSON
        # ----------------------------------------------------

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "status": "error",
                "message": "Не предоставлена полезная нагрузка JSON"
            }), 400

        print("=" * 60)
        print("WEBHOOK RECEIVED:")
        print(data)
        print("=" * 60)


        # ----------------------------------------------------
        # SYMBOL
        # ----------------------------------------------------

        symbol = normalize_symbol(
            data.get("symbol", "BTCUSDT")
        )


        # ----------------------------------------------------
        # ACTION
        # ----------------------------------------------------

        action = normalize_action(
            data.get("action", "")
        )


        # ----------------------------------------------------
        # QTY
        # ----------------------------------------------------

        qty = normalize_qty(
            data.get("qty", "")
        )


        print("SYMBOL:", symbol)
        print("ACTION:", action)
        print("QTY:", qty)


        # ----------------------------------------------------
        # ПРОВЕРКА SYMBOL
        # ----------------------------------------------------

        if not symbol:
            return jsonify({
                "status": "error",
                "message": "Не указан symbol"
            }), 400


        # ====================================================
        # BUY
        # ====================================================

        if action == "buy":

            if not qty:
                return jsonify({
                    "status": "error",
                    "message": "Quantity is empty or zero",
                    "symbol": symbol
                }), 400


            print("ОТКРЫВАЕМ LONG:", symbol, qty)


            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty,
                positionIdx=0,
                reduceOnly=False
            )


            print("BYBIT BUY RESPONSE:", response)


            check = bybit_error_response(response)


            if not check["ok"]:

                return jsonify({
                    "status": "error",
                    "action": "buy",
                    "symbol": symbol,
                    "qty": qty,
                    "retCode": check["retCode"],
                    "retMsg": check["retMsg"],
                    "response": response
                }), 400


            return jsonify({
                "status": "success",
                "action": "buy",
                "symbol": symbol,
                "qty": qty,
                "response": response
            }), 200


        # ====================================================
        # SELL
        # ====================================================

        elif action == "sell":

            if not qty:
                return jsonify({
                    "status": "error",
                    "message": "Quantity is empty or zero",
                    "symbol": symbol
                }), 400


            print("ОТКРЫВАЕМ SHORT:", symbol, qty)


            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=qty,
                positionIdx=0,
                reduceOnly=False
            )


            print("BYBIT SELL RESPONSE:", response)


            check = bybit_error_response(response)


            if not check["ok"]:

                return jsonify({
                    "status": "error",
                    "action": "sell",
                    "symbol": symbol,
                    "qty": qty,
                    "retCode": check["retCode"],
                    "retMsg": check["retMsg"],
                    "response": response
                }), 400


            return jsonify({
                "status": "success",
                "action": "sell",
                "symbol": symbol,
                "qty": qty,
                "response": response
            }), 200


        # ====================================================
        # CLOSE
        # ====================================================

        elif action == "close":

            print("ЗАПРОС НА ЗАКРЫТИЕ:", symbol)


            # ------------------------------------------------
            # Получаем текущую позицию
            # ------------------------------------------------

            position = get_position(symbol)


            if not position:

                print("ПОЗИЦИЯ НЕ НАЙДЕНА:", symbol)

                return jsonify({
                    "status": "ignored",
                    "message": "Не найдена открытая позиция для закрытия",
                    "symbol": symbol
                }), 200


            position_side = position.get("side", "")
            position_size = position.get("size", "0")
            position_idx = position.get("positionIdx", 0)


            print("POSITION SIDE:", position_side)
            print("POSITION SIZE:", position_size)
            print("POSITION IDX:", position_idx)


            try:
                position_size_float = float(position_size)
            except (ValueError, TypeError):

                return jsonify({
                    "status": "error",
                    "message": "Некорректный размер позиции",
                    "symbol": symbol,
                    "size": position_size
                }), 400


            if position_size_float <= 0:

                return jsonify({
                    "status": "ignored",
                    "message": "Размер позиции равен нулю",
                    "symbol": symbol
                }), 200


            # ------------------------------------------------
            # Для LONG закрытие = SELL
            # Для SHORT закрытие = BUY
            # ------------------------------------------------

            if position_side == "Buy":
                close_side = "Sell"

            elif position_side == "Sell":
                close_side = "Buy"

            else:

                return jsonify({
                    "status": "error",
                    "message": "Неизвестная сторона позиции",
                    "symbol": symbol,
                    "side": position_side
                }), 400


            close_qty = normalize_qty(position_size)


            if not close_qty:

                return jsonify({
                    "status": "error",
                    "message": "Размер позиции для закрытия некорректен",
                    "symbol": symbol,
                    "size": position_size
                }), 400


            print(
                "ЗАКРЫВАЕМ:",
                symbol,
                "SIDE:",
                close_side,
                "QTY:",
                close_qty
            )


            # ------------------------------------------------
            # Закрывающий Market ордер
            # ------------------------------------------------

            response = session.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=close_qty,
                positionIdx=position_idx,
                reduceOnly=True
            )


            print("BYBIT CLOSE RESPONSE:", response)


            check = bybit_error_response(response)


            if not check["ok"]:

                return jsonify({
                    "status": "error",
                    "action": "close",
                    "symbol": symbol,
                    "qty": close_qty,
                    "side": close_side,
                    "retCode": check["retCode"],
                    "retMsg": check["retMsg"],
                    "response": response
                }), 400


            return jsonify({
                "status": "success",
                "action": "close",
                "symbol": symbol,
                "qty": close_qty,
                "side": close_side,
                "response": response
            }), 200


        # ====================================================
        # НЕИЗВЕСТНОЕ ДЕЙСТВИЕ
        # ====================================================

        else:

            return jsonify({
                "status": "error",
                "message": f"Неизвестное действие: {action}",
                "symbol": symbol,
                "received_data": data
            }), 400


    # ========================================================
    # ОШИБКА PYTHON / BYBIT / СЕТИ
    # ========================================================

    except Exception as e:

        print("=" * 60)
        print("ОШИБКА WEBHOOK:")
        print(str(e))
        print("=" * 60)


        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================
# ЗАПУСК СЕРВЕРА
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
