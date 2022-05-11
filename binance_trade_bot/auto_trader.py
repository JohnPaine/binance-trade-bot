from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from .binance_api_manager import BinanceAPIManager
from .config import Config
from .database import Database
from .logger import Logger
from .models import Coin, CoinValue, Pair
from dataclasses import dataclass
from sortedcontainers import SortedDict
import sys


@dataclass
class TradeStats:
    trade_idx: int
    dt: datetime
    from_coin: str = ""
    to_coin: str = ""
    from_coin_price: float = 0
    to_coin_price: float = 0
    prev_trade: str = ""
    trades_str: str = ""
    diff_usdt: float = 0
    diff_perc: float = 0
    quantity: float = 0
    balance: str = ""
    perc_from_init_balance: float = 0
    manager: BinanceAPIManager = None
    multiplier: float = 0

    def __str__(self):
        # m = f"x{self.multiplier}, {self.dt.strftime('%d/%m/%Y, %H:%M:%S')}, {self.from_coin}->{self.to_coin} " \
        #     f"[{self.from_coin_price}*{self.quantity} -> {self.to_coin_price}], " \
        #     f"prev_trade: {self.prev_trade}, " \
        #     f"profit: ${self.diff_usdt} ({self.diff_perc}%), " \
        #     f"balance: {self.balance}, result: {self.perc_from_init_balance}% from init balance: " \
        #     f"{self.manager.init_balance}\n"
        m = f"{self.trade_idx}. x{self.multiplier}, {self.dt.strftime('%d/%m/%Y, %H:%M:%S')}, {self.trades_str}, " \
            f"PNL: ${self.diff_usdt} ({self.diff_perc}%), " \
            f"result: {self.perc_from_init_balance}% from init balance - " \
            f"{self.manager.init_balance['USDT']}$"
        return m


class AutoTrader:
    def __init__(self, binance_manager: BinanceAPIManager, database: Database, logger: Logger, config: Config):
        self.manager = binance_manager
        self.db = database
        self.logger = logger
        self.config = config
        self.stats = SortedDict()
        self.worst_profit = sys.maxsize
        self.worst_trade = None
        self.best_profit = -sys.maxsize
        self.best_trade = None
        self.average_profit = 0
        self.last_trade_stats = None

    def initialize(self):
        self.initialize_trade_thresholds()

    def print_trade_stats(self):
        msg = "\n\nTrade stats:\n"
        for s in self.stats.values():
            msg += f"{str(s)}\n"
        self.logger.warning(msg)

    def transaction_through_bridge(self, pair: Pair):
        """
        Jump from the source coin to the destination coin through bridge coin
        """
        can_sell = False
        balance = self.manager.get_currency_balance(pair.from_coin.symbol)
        from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)
        to_coin_price = self.manager.get_ticker_price(pair.to_coin + self.config.BRIDGE)

        s = TradeStats(len(self.stats), self.manager.datetime, pair.from_coin.symbol, pair.to_coin.symbol,
                       from_coin_price, to_coin_price, manager=self.manager,
                       multiplier=round(self.manager.config.SCOUT_MULTIPLIER, 2))
        diff_usdt = 0
        if balance and balance * from_coin_price > self.manager.get_min_notional(
            pair.from_coin.symbol, self.config.BRIDGE.symbol
        ):
            can_sell = True
        else:
            self.logger.info("Skipping sell")

        if can_sell:
            trade = self.manager.sell_alt(pair.from_coin, self.config.BRIDGE)
            # print(f"{trade}\n")
            if trade is None:
                self.logger.info("Couldn't sell, going back to scouting mode...")
                return None
            else:
                if self.last_trade_stats:
                    prev = self.last_trade_stats
                    s.quantity = trade["quantity"]
                    sum1 = round(prev.from_coin_price * prev.quantity, 2)
                    sum2 = round(prev.to_coin_price * s.quantity, 2)
                    sum3 = round(s.from_coin_price * s.quantity, 2)
                    q4 = round(sum3 / s.to_coin_price, 3)
                    sum4 = round(q4 * s.to_coin_price, 2)
                    s.trades_str = f"{prev.from_coin} [{prev.from_coin_price}*{prev.quantity}={sum1}$] -> " \
                                   f"{prev.to_coin} [{prev.to_coin_price}*{s.quantity}={sum2}$] -> " \
                                   f"{s.from_coin} [{s.from_coin_price}*{s.quantity}={sum3}$] -> " \
                                   f"{s.to_coin} [{s.to_coin_price}*{q4}={sum4}$]"
                    # s.prev_trade = f"{prev.from_coin} -> {prev.to_coin} " \
                    #                f"[{prev.from_coin_price}*{prev.quantity}->" \
                    #                f"{prev.to_coin_price}*{s.quantity}]"
                    diff_usdt = s.diff_usdt = round((trade["price"] - prev.to_coin_price) * s.quantity, 3)
                    init_balance = self.manager.init_balance["USDT"]
                    s.diff_perc = round(s.diff_usdt / init_balance * 100.0, 3)
                    s.balance = f"{round(balance, 3)} {pair.to_coin.symbol}"
                    # bridge_value = self.manager.collate_coins(self.manager.config.BRIDGE.symbol)
                    s.perc_from_init_balance = round((sum3 - init_balance) / init_balance * 100, 3)

                    if self.worst_profit > diff_usdt:
                        self.worst_profit = diff_usdt
                        self.worst_trade = s
                    if self.best_profit < diff_usdt:
                        self.best_profit = diff_usdt
                        self.best_trade = s
                    stats_len = len(self.stats)
                    if stats_len > 1:
                        self.average_profit *= stats_len
                        self.average_profit += diff_usdt
                        self.average_profit /= (stats_len + 1)
                        self.average_profit = round(self.average_profit, 3)

                while self.stats.__contains__(diff_usdt):
                    diff_usdt += 1e-12
                self.stats[diff_usdt] = s
                self.last_trade_stats = s
                self.print_trade_stats()

        result = self.manager.buy_alt(pair.to_coin, self.config.BRIDGE)
        if result is not None:
            self.db.set_current_coin(pair.to_coin)
            self.update_trade_threshold(pair.to_coin, result.price)
            if result.price is None:
                print(f"result.price is None ---> pair.to_coin: {pair.to_coin}, pair.from_coin: {pair.from_coin}")
            # elif self.last_trade_stats:
            #     last_trade = self.last_trade_stats
            #     s.trades_str = f"{last_trade.from_coin} [{last_trade.from_coin_price}*{last_trade.quantity}] -> " \
            #                    f"{last_trade.to_coin} [{last_trade.to_coin_price}*{s.quantity}] -> " \
            #                    f"{s.from_coin} [{s.from_coin_price}*{s.quantity}] -> " \
            #                    f"{s.to_coin} [{result.price} * {result.cumulative_quote_qty}]"
            return result

        self.logger.info("Couldn't buy, going back to scouting mode...")
        return None

    def update_trade_threshold(self, coin: Coin, coin_price: float):
        """
        Update all the coins with the threshold of buying the current held coin
        """

        if coin_price is None:
            self.logger.info("Skipping update... current coin {} not found".format(coin + self.config.BRIDGE))
            return

        session: Session
        with self.db.db_session() as session:
            for pair in session.query(Pair).filter(Pair.to_coin == coin):
                from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)

                if from_coin_price is None:
                    self.logger.info(
                        "Skipping update for coin {} not found".format(pair.from_coin + self.config.BRIDGE)
                    )
                    continue

                pair.ratio = from_coin_price / coin_price

    def initialize_trade_thresholds(self):
        """
        Initialize the buying threshold of all the coins for trading between them
        """
        session: Session
        with self.db.db_session() as session:
            for pair in session.query(Pair).filter(Pair.ratio.is_(None)).all():
                if not pair.from_coin.enabled or not pair.to_coin.enabled:
                    continue

                # self.logger.info(f"Initializing {pair.from_coin} vs {pair.to_coin}")

                from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)
                if from_coin_price is None:
                    self.logger.info(
                        "Skipping initializing {}, symbol not found".format(pair.from_coin + self.config.BRIDGE)
                    )
                    continue

                to_coin_price = self.manager.get_ticker_price(pair.to_coin + self.config.BRIDGE)
                if to_coin_price is None:
                    self.logger.info(
                        "Skipping initializing {}, symbol not found".format(pair.to_coin + self.config.BRIDGE)
                    )
                    continue

                pair.ratio = from_coin_price / to_coin_price
                # self.logger.info(f"\nInitialized pair threshold:"
                #                  f"\n{pair}"
                #                  f"\nfrom_coin_price:\t{from_coin_price}"
                #                  f"\nto_coin_price:\t{to_coin_price}"
                #                  f"\n")

    def scout(self):
        """
        Scout for potential jumps from the current coin to another coin
        """
        raise NotImplementedError()

    def _get_ratios(self, coin: Coin, coin_price):
        """
        Given a coin, get the current price ratio for every other enabled coin
        """
        ratio_dict: Dict[Pair, float] = {}

        if coin_price == "no price":
            print(f"\n\tWARNING:       ------>>> SKIP COIN: {coin} <<<------ \n\t!!!!!!!!!!! NO PRICE !!!!!!!!!!!!\n\n")
            return ratio_dict

        for pair in self.db.get_pairs_from(coin):
            optional_coin_price = self.manager.get_ticker_price(pair.to_coin + self.config.BRIDGE)

            if optional_coin_price is None:
                self.logger.info(
                    "Skipping scouting... optional coin {} not found".format(pair.to_coin + self.config.BRIDGE)
                )
                continue

            self.db.log_scout(pair, pair.ratio, coin_price, optional_coin_price)

            if isinstance(coin_price, str) or isinstance(optional_coin_price, str):
                self.logger.warning(f"\n\n\t\t\t\t!!!!!!!!!!! ERROR !!!!!!!!!!!!!\n\n\t\tcoin_price - '{coin_price}', "
                                    f"optional_coin_price - '{optional_coin_price}'"
                                    f"\n\t\t\t/\\/\\/\\!!!!!!!!!<<<------- WRONG PRICE TYPES --------->>>!!!!!!!!!\n\n")
                continue

            # Obtain (current coin)/(optional coin)
            optional_coin_ratio = coin_price / optional_coin_price

            # Fees
            from_fee = self.manager.get_fee(pair.from_coin, self.config.BRIDGE, True)
            to_fee = self.manager.get_fee(pair.to_coin, self.config.BRIDGE, False)
            transaction_fee = from_fee + to_fee - from_fee * to_fee

            if self.config.USE_MARGIN == "yes":
                mult = self.config.SCOUT_MARGIN
                result = optional_coin_ratio / pair.ratio * (1 - transaction_fee) - 1 - mult / 100
            else:
                mult = self.config.SCOUT_MULTIPLIER
                result = optional_coin_ratio * (1 - transaction_fee * mult) - pair.ratio

            ratio_dict[pair] = result
            # self.logger.info(f"\nCalculated ratio for pair: {pair}\n"
            #                  f"coin_price:\t\t\t{coin_price}\n"
            #                  f"optional_coin_price:\t{optional_coin_price}\n"
            #                  f"optional_coin_ratio:\t{optional_coin_ratio}\n"
            #                  f"calc_coin_ratio:\t\t{result}\n"
            #                  )
        return ratio_dict

    def _jump_to_best_coin(self, coin: Coin, coin_price: float):
        """
        Given a coin, search for a coin to jump to
        """
        ratio_dict = self._get_ratios(coin, coin_price)

        # self.logger.info(f"\nratio_dict: {ratio_dict}\n")

        # keep only ratios bigger than zero
        ratio_dict = {k: v for k, v in ratio_dict.items() if v > 0}

        # if we have any viable options, pick the one with the biggest ratio
        if ratio_dict:
            best_pair = max(ratio_dict, key=ratio_dict.get)

            self.logger.info(f"best_pair: {best_pair}")

            self.logger.info(f"Will be jumping from {coin} to {best_pair.to_coin_id}")
            self.transaction_through_bridge(best_pair)

    def bridge_scout(self):
        """
        If we have any bridge coin leftover, buy a coin with it that we won't immediately trade out of
        """
        bridge_balance = self.manager.get_currency_balance(self.config.BRIDGE.symbol)

        for coin in self.db.get_coins():
            current_coin_price = self.manager.get_ticker_price(coin + self.config.BRIDGE)

            if current_coin_price is None:
                continue

            ratio_dict = self._get_ratios(coin, current_coin_price)
            if not any(v > 0 for v in ratio_dict.values()):
                # There will only be one coin where all the ratios are negative. When we find it, buy it if we can
                if bridge_balance > self.manager.get_min_notional(coin.symbol, self.config.BRIDGE.symbol):
                    self.logger.info(f"Will be purchasing {coin} using bridge coin")
                    self.manager.buy_alt(coin, self.config.BRIDGE)
                    return coin
        return None

    def update_values(self):
        """
        Log current value state of all altcoin balances against BTC and USDT in DB.
        """
        now = datetime.now()

        session: Session
        with self.db.db_session() as session:
            coins: List[Coin] = session.query(Coin).all()
            for coin in coins:
                balance = self.manager.get_currency_balance(coin.symbol)
                if balance == 0:
                    continue
                usd_value = self.manager.get_ticker_price(coin + "USDT")
                btc_value = self.manager.get_ticker_price(coin + "BTC")
                cv = CoinValue(coin, balance, usd_value, btc_value, datetime=now)
                session.add(cv)
                self.db.send_update(cv)
