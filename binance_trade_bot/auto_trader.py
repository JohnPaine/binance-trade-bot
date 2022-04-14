from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from .binance_api_manager import BinanceAPIManager
from .config import Config
from .database import Database
from .logger import Logger
from .models import Coin, CoinValue, Pair
from dataclasses import dataclass


@dataclass
class TradeStats:
    dt: datetime
    from_coin: str = ""
    to_coin: str = ""
    from_coin_price: float = 0
    to_coin_price: float = 0
    diff_usdt: float = 0
    diff_perc: float = 0
    quantity: float = 0
    balance: str = ""
    perc_from_init_balance: float = 0


class AutoTrader:
    def __init__(self, binance_manager: BinanceAPIManager, database: Database, logger: Logger, config: Config):
        self.manager = binance_manager
        self.db = database
        self.logger = logger
        self.config = config
        self.stats = []
        self.worst_profit = 0
        self.worst_trade = None
        self.best_profit = 0
        self.best_trade = None
        self.average_profit = 0

    def initialize(self):
        self.initialize_trade_thresholds()

    def print_trade_stats(self):
        msg = "\n\nTrade stats:\n"
        for s in self.stats:
            m = f"{s.dt}, {s.from_coin}->{s.to_coin} [{round(s.from_coin_price, 3)}->{round(s.to_coin_price, 3)}] * " \
                f"{s.quantity}, {round(s.diff_usdt, 3)}, {round(s.diff_perc, 3)}%, " \
                f"balance: {s.balance}, result: {s.perc_from_init_balance}% from init balance: " \
                f"{self.manager.init_balance}\n"
            msg += m
        self.logger.warning(msg)

    def transaction_through_bridge(self, pair: Pair):
        """
        Jump from the source coin to the destination coin through bridge coin
        """
        can_sell = False
        balance = self.manager.get_currency_balance(pair.from_coin.symbol)
        from_coin_price = self.manager.get_ticker_price(pair.from_coin + self.config.BRIDGE)
        to_coin_price = self.manager.get_ticker_price(pair.to_coin + self.config.BRIDGE)

        s = TradeStats(self.manager.datetime, pair.from_coin.symbol, pair.to_coin.symbol,
                       from_coin_price, to_coin_price)
        if balance and balance * from_coin_price > self.manager.get_min_notional(
            pair.from_coin.symbol, self.config.BRIDGE.symbol
        ):
            can_sell = True
        else:
            self.logger.info("Skipping sell")

        if can_sell:
            trade = self.manager.sell_alt(pair.from_coin, self.config.BRIDGE)
            print(f"{trade}\n")
            if trade is None:
                self.logger.info("Couldn't sell, going back to scouting mode...")
                return None
            else:
                if len(self.stats) > 0:
                    last_trade = self.stats[-1]
                    s.quantity = trade["quantity"]
                    s.diff_usdt = (trade["price"] - last_trade.to_coin_price) * s.quantity
                    s.diff_perc = s.diff_usdt / self.manager.balances["USDT"] * 100.0
                    s.balance = f"{round(balance, 3)} {pair.to_coin.symbol}"
                    bridge_value = self.manager.collate_coins(self.manager.config.BRIDGE.symbol)
                    init_balance = self.manager.init_balance["USDT"]
                    print(f"init_balance = {init_balance}")
                    s.perc_from_init_balance = round((bridge_value - init_balance) / init_balance * 100, 3)

                    if self.worst_profit > s.diff_usdt:
                        self.worst_profit = s.diff_usdt
                        self.worst_trade = s
                    if self.best_profit < s.diff_usdt:
                        self.best_profit = s.diff_usdt
                        self.best_trade = s
                    stats_len = len(self.stats)
                    if stats_len > 1:
                        self.average_profit *= stats_len
                        self.average_profit += s.diff_usdt
                        self.average_profit /= (stats_len + 1)
                self.stats.append(s)
                self.print_trade_stats()

        result = self.manager.buy_alt(pair.to_coin, self.config.BRIDGE)
        if result is not None:
            self.db.set_current_coin(pair.to_coin)
            self.update_trade_threshold(pair.to_coin, result.price)
            if result.price is None:
                print(f"result.price is None ---> pair.to_coin: {pair.to_coin}, pair.from_coin: {pair.from_coin}")
                # self.manager.cache[]
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
                self.logger.info(f"Initializing {pair.from_coin} vs {pair.to_coin}")

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
                self.logger.info(f"\nInitialized pair threshold:"
                                 f"\n{pair}"
                                 f"\nfrom_coin_price:\t{from_coin_price}"
                                 f"\nto_coin_price:\t{to_coin_price}"
                                 f"\n")

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
            print(f"--->>> SKIP COIN: {coin} ------ NO PRICE!!!!!!!!!!!!!!")
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
                self.logger.warning(f"coin_price - '{coin_price}', optional_coin_price - '{optional_coin_price}'"
                                    f" ------- wrong price type!!!!")
                continue

            # Obtain (current coin)/(optional coin)
            coin_opt_coin_ratio = coin_price / optional_coin_price

            # self.logger.info(f"\npair: {pair}\n"
            #                  f"price_1: {coin_price}\n"
            #                  f"price_2: {optional_coin_price}\n"
            #                  f"ratio: {coin_opt_coin_ratio}\n"
            #                  )

            # Fees
            from_fee = self.manager.get_fee(pair.from_coin, self.config.BRIDGE, True)
            to_fee = self.manager.get_fee(pair.to_coin, self.config.BRIDGE, False)
            transaction_fee = from_fee + to_fee - from_fee * to_fee

            if self.config.USE_MARGIN == "yes":
                ratio_dict[pair] = (
                    (1 - transaction_fee) * coin_opt_coin_ratio / pair.ratio - 1 - self.config.SCOUT_MARGIN / 100
                )
            else:
                r1 = coin_opt_coin_ratio
                r2 = transaction_fee * self.config.SCOUT_MULTIPLIER * coin_opt_coin_ratio
                pr = pair.ratio
                result = (r1 - r2) - pr

                # self.logger.info(f""
                #                  f"\ndt: {self.manager.datetime}"
                #                  f"\nr1: {r1}"
                #                  f"\nr2: {r2}"
                #                  f"\npr: {pr}"
                #                  f"\nresult: {result}\n"
                #                  )

                ratio_dict[pair] = result
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
