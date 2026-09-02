import os
import json
import math
import threading

from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP


app = Flask(__name__)

API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

session = HTTP(
 testnet= False, 
api_key=API_KEY, 
api_secret=API_SECRET 
)


# =========================
# НАСТРОЙКИ
# =========================

MARGIN_PERCENT = 0.20 # 20% текущего equity
LEVERAGE = 10 # 10x плечо
ACCOUNT_COIN = "USDT"


# Защита от двух одновременных BUY-сигналов
trade_lock = threading.Lock()


# =========================
# НОРМАЛИЗАЦИЯ СИМВОЛА
# =========================

def normalize_symbol(symbol):

 if not symbol:
 return ""

 symbol = str(symbol).strip().upper()

 # BYBIT:BTCUSDT.P -> BTCUSDT.P
 if ":" in symbol:
 symbol = symbol.split(":")[-1]

 # BTCUSDT.P -> BTCUSDT 
 если symbol.endswith(".P"):
 symbol = symbol[:-2]

 символ возврата


# =========================
# ПОЛУЧЕНИЕ EQUITY
# =========================

определение get_current_equity():

 response = session.get_wallet_balance(
 accountType="UNIFIED",
 coin=ACCOUNT_COIN
 )

 if response.get("retCode") != 0:
 raise Exception(
 response.get(
 "retMsg",
 "Не удалось получить баланс Bybit"
 )
 )

 account_list = response.get(
 "result", {}
 ).get(
 "list", []
 )

 if not account_list:
 raise Exception(
 "Bybit не вернул данные Unified Account"
 )

 account = account_list[0]

 total_equity = float(
 account.get("totalEquity", "0") or 0
 )

 if total_equity <= 0:
 raise Exception(
 f"Некорректный баланс Bybit: {total_equity}"
 )

 возвращает total_equity


# =========================
# ПОИСК ЛЮБОЙ ОТКРЫТОЙ ПОЗИЦИИ
# =========================

определение get_any_open_position():

 ответ = session.get_positions( 
категория="линейный", 
 settleCoin=ACCOUNT_COIN)
 )

 если ответ.get("Повторный код") != 0:
 raise Exception(
 response.get(
 "retMsg",
 "Не удалось получить позиции Bybit"
 )
 )

 positions = response.get(
 "result", {}
 ).get(
 "list", []
 )

 for position in positions:

 symbol = position.get(
 "symbol",
 ""
 )

 side = position.get(
 "side",
 ""
 )

 size = float(
 position.get(
 "size",
 "0"
 ) or 0
 )

 если размер > 0 и сторона в ["Купить", "Продать"]:

 позиция возврата

 возврата нет


# =========================
# ПОЗИЦИЯ КОНКРЕТНОЙ МОНЕТЫ
# =========================

определение get_position(символ):

 ответ = сессия.get_positions( 
категория="линейный", 
символ=symbol 
 )

 if response.get("retCode") != 0:
 raise Exception(
 response.get(
 "retMsg",
 f"Ошибка получения позиции {symbol}"
 )
 )

 positions = response.get(
 "result", {}
 ).get(
 "list", []
 )

 for position in positions:

 сторона = position.get( 
"сторона", 
""" 
 )

 size = float( 
позиция.get( 
"размер", 
 "0"
 ) или 0
 )

 если размер > 0 и сторона в ["Купить", "Продать"]:
 позиция возврата

 возврата нет


# =========================
# ПОЛУЧЕНИЕ ЦЕНЫ
# =========================

def get_price(symbol):

 response = session.get_tickers(
 category="linear",
 symbol=symbol
 )

 if response.get("retCode") != 0:
 raise Exception(
 response.get(
 "retMsg",
 f"Не удалось получить цену {symbol}"
 )
 )

 items = response.get(
 "result", {}
 ).get(
 "list",
 []
 )

 if not items:
 raise Exception(
 f"Не удалось получить цену {symbol}"
 )

 return float(
 items[0]["lastPrice"]
 )


# =========================
# РАСЧЕТ РАЗМЕРА ПОЗИЦИИ
# =========================

def calculate_quantity(symbol, price):

 # ---------------------------------
 # 1. Получаем текущий эквити
 # ---------------------------------

 equity = get_current_equity()

 # ---------------------------------
 # 2. Берём 20% equity как маржу
 # ---------------------------------

 margin_amount = собственный капитал * MARGIN_PERCENT

 # ---------------------------------
 # 3. Умножаем на 10x
 # ---------------------------------

 position_usdt = количество маржи * КРЕДИТНОЕ ПЛЕЧО

 # ---------------------------------
 # 4. Переводим USDT-позицию
 # в количество монет
 # ---------------------------------

 raw_qty = position_usdt / цена

 # ---------------------------------
 # 5. Получаем правила инструмента
 # ---------------------------------

 response = session.get_instruments_info(
 category="linear",
 symbol=symbol
 )

 if response.get("retCode") != 0:
 raise Exception(
 response.get(
 "retMsg",
 f"Ошибка получения настроек {symbol}"
 )
 )

 instruments = response.get(
 "result", {}
 ).get( "list",
 []
 )

 if not instruments:
 raise Exception(
 f"Bybit не нашёл инструмент {symbol}"
 )

 lot_filter = instruments[0].get(
 "lotSizeFilter",
 {}
 )

 min_qty = float(
 lot_filter.get(
 "minOrderQty",
 "0"
 )
 )

 qty_step = float(
 lot_filter.get(
 "qtyStep",
 "1"
 )
 )

 if qty_step <= 0:
 qty_step = 1

 # Округляем количество в меньшую сторону
 qty = math.floor(
 raw_qty / qty_step
 ) * qty_step

 # Проверяем минимум
 if qty < min_qty:
 qty = min_qty

 if qty <= 0:
 raise Exception(
 f"Получилось некорректное количество: {qty}"
 )

 qty_string = format(
 qty,
 ".12f"
 ).rstrip("0").rstrip(".")

 return {
 "equity": equity,
 "margin": margin_amount,
 "position_usdt": position_usdt,
 "qty": qty_string
 }


# =========================
# ОТКРЫТИЕ LONG
# =========================

def open_long(symbol):

 # =================================
 # ГЛАВНАЯ ЗАЩИТА:
 # только ОДНА позиция на аккаунт
 # =================================

 with trade_lock:

 existing_position = get_any_open_position()

 if existing_position:

 existing_symbol = existing_position.get(
 "symbol",
 ""
 )

 existing_side = existing_position.get(
 "side",
 ""
 )

 existing_size = existing_position.get(
 "size",
 "0"
 )

 print(
 f"--> НОВЫЙ BUY ИГНОРИРУЕТСЯ"
 )

 print(
 f"--> УЖЕ ЕСТЬ ПОЗИЦИЯ: "
 f"{existing_symbol} "
 f"{existing_side} "
 f"qty={existing_size}"
 )

 return {
 "status": "ignored",
 "reason": "position_already_open",
 "existing_symbol": existing_symbol,
 "existing_side": existing_side,
 "existing_qty": existing_size
 }

 # =================================
 # ПОЛУЧАЕМ ЦЕНУ
 # =================================

 price = get_price(symbol)

 # =================================
 # РАСЧИТЫВАЕМ ПОЗИЦИЮ
 # =================================

 sizing = calculate_quantity(
 symbol,
 price
 )

 equity = sizing["equity"]
 margin = sizing["margin"]
 position_usdt = sizing["position_usdt"]
 qty = sizing["qty"]

 print(
 f"--> ТЕКУЩИЕ АКТИВЫ: ${equity:.2f}"
 )

 print(
 f"--> МАРЖА 20%: ${margin:.2f}"
 )

 print(
 f"--> ПОЗИЦИЯ 10x: "
 f"${position_usdt:.2f}"
 )

 print(
 f"--> ЦЕНА: {price}"
 )

 print(
 f"--> КОЛИЧЕСТВО В LONG: {qty}"
 )

 # =================================
 # ОТКРЫВАЕМ LONG
 # =================================

 response = session.place_order(
 category="linear",
 symbol=symbol,
 side="Buy",
 orderType="Market",
 qty=qty,
 timeInForce="GoodTillCancel",
 positionIdx=0
 )

 print(
 f"--> LONG ОТПРАВЛЕН: {response}"
 )

 if response.get("retCode") != 0:

 raise Exception(
 response.get(
 "retMsg",
 "Ошибка при открытии Bybit"
 )
 )

 return {
 "status": "opened",
 "symbol": symbol,
 "side": "Buy",
 "qty": qty,
 "price": price,
 "equity": equity,
 "margin": margin,
 "position_usdt": position_usdt,
 "leverage": рычаг
 }


# =========================
# ЗАКРЫТИЕ LONG
# =========================

def close_long(symbol):

 position = get_position(symbol)

 # НЕТ ПОЗИЦИИ
 if not position:

 print(
 f"--> CLOSE ПОЛУЧЕН, "
 f"НО LONG НЕ ОТКРЫТ: {symbol}"
 )

 return {
 "status": "nothing_to_close",
 "symbol": symbol,
 "message": "Long отсутствует"
 }

 current_side = position.get(
 "side"
 )

 current_size = position.get(
 "size"
 )

 # Не трогаем Short
 if current_side != "Buy":

 print(
 f"--> НАЙДЕН НЕ LONG: "
 f"{current_side} {symbol}"
 )

 return {
 "status": "ignored",
 "symbol": symbol,
 "message": "Обнаружена не Long-позиция"
 }

 print(
 f"--> ЗАКРЫВАЕМ LONG: "
 f"{symbol}, qty={current_size}"
 )

 response = session.place_order(
 category="linear",
 symbol=symbol,
 side="Sell",
 orderType="Market",
 qty=str(current_size),
 reduceOnly=True,
 positionIdx=0
 )

 print(
 f"--> LONG ЗАКРЫТ: {response}"
 )

 if response.get("retCode") != 0:

 raise Exception(
 response.get(
 "retMsg",
 "Ошибка закрытия Bybit"
 )
 )

 return {
 "status": "closed",
 "symbol": symbol,
 "side": "Sell",
 "qty": current_size
 }


# =========================
# WEBHOOK
# =========================

@app.route(
 "/webhook",
 methods=["POST", "GET"]
)
def webhook():

 Пытаться:

 data = request.get_json(
 silent=True
 )

 if not data:

 if request.data:

 Пытаться:

 data = json.loads(
 request.data.decode(
 "utf-8"
 )
 )

 except Exception:

 data = {
 "raw":
 request.data.decode(
 "utf-8"
 )
 }

 else:

 data = request.form.to_dict()

 print(
 f"--> ПОЛУЧЕН СИГНАЛ "
 f"ОТ TRADINGVIEW: {data}"
 )

 symbol = normalize_symbol(
 data.get(
 "символ",
 ""
 )
 )

 action = str(
 data.get(
 "action",
 data.get(
 "действие",
 ""
 )
 )
 ).strip().lower()

 print(
 f"--> СИМВОЛ: {символ}"
 )

 print( 
 f"--> ACTION: {действие}"
 )

 если не символ:

 верните jsonify({
 "status": "error",
 "message": "Не указан symbol"
 }), 400

 если нет действия:

 верните jsonify({
 "status": "error",
 "message": "Не указан action"
 }), 400

 # =========================
 # КУПИТЬ
 # =========================

 if action in [
 "buy",
 "купить",
 "long"
 ]:

 результат = open_long( 
символ 
 )

 возвращает jsonify( 
 результат
 ), 200

 # =========================
 # ЗАКРЫТЬ
 # =========================

 if action in [
 "sell",
 "продать",
 "exit", 
 "close"
 ]:

 результат = close_long( 
 символ
 )

 возвращает jsonify( 
 результат
 ), 200

 возвращает jsonify({
 "статус": "ошибка", 
 "сообщение":
 f"Неизвестное действие: {action}"
 }), 400

 за Исключением Исключения в виде e:

 print(
 f"--> ОШИБКА ОПЕРАЦИИ: {e}"
 )

 возвращает jsonify({
 "статус": "ошибка", 
 "сообщение": str(e)
 }), 200


# =========================
# ПРОВЕРКА СОСТОЯНИЯ ЗДОРОВЬЯ
# =========================

@app.route(
 "/", 
 методы=["ПОЛУЧИТЬ", "HEAD"]
)
определить работоспособность():

 вернуть jsonify({
 "статус": "ок", 
 "сообщение": "Бот Bybit запущен"
 }), 200


# =========================
# ЗАПУСК
# =========================

if __name__ == "__main__":

 port = int(
 os.environ.get(
 "PORT",
 10000
 )
 )

 app.run(
 host="0.0.0.0",
 port=port
 )
