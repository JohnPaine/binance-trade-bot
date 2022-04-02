from datetime import datetime
from binance_trade_bot.logger import Logger
from binance_trade_bot import backtest

if __name__ == "__main__":
    history = []
    # bridge_diffs = []
    # logger = Logger("backtesting", enable_notifications=False)

    # for i in range(1, 5):
    for manager in backtest(datetime(2020, 1, 1), datetime(2022, 3, 25)):
        btc_value = manager.collate_coins("BTC")
        bridge_value = manager.collate_coins(manager.config.BRIDGE.symbol)
        history.append((btc_value, bridge_value))
        btc_diff = round((btc_value - history[0][0]) / history[0][0] * 100, 3)
        bridge_diff = round((bridge_value - history[0][1]) / history[0][1] * 100, 3)
        print("------")
        print("TIME:", manager.datetime)
        print("BALANCES:", manager.balances)
        print("BTC VALUE:", btc_value, f"({btc_diff}%)")
        print(f"{manager.config.BRIDGE.symbol} VALUE:", bridge_value, f"({bridge_diff}%)")
        print("------")

        # logger.info("------")
        # logger.info("TIME:", manager.datetime)
        # logger.info("BALANCES:", manager.balances)
        # logger.info(f"BTC VALUE: ({btc_diff}%)")
        # logger.info(f"{manager.config.BRIDGE.symbol} VALUE: ({bridge_diff}%)")
        # logger.info("------")

        # bridge_diffs.append(bridge_diff)

        # print(f"41414141 FINISHED {i} ITERATION OF BACKTESTING LOOP, last bridge diff: {bridge_diffs[-1]}")


